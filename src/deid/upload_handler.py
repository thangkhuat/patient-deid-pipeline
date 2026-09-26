"""Operator-facing API Lambda, two routes behind the same Cognito authorizer.

POST /upload accepts clinical note text and writes it to input-notes,
triggering the Pipeline Lambda's S3 event asynchronously. Does not detect,
redact, or wait for processing -- that's a genuinely separate concern,
decoupled on purpose (see decision-log.md, the event-driven architecture
choice).

GET /notes/{note_id} lets the Operator collect the result afterwards, as a
short-lived presigned URL to the redacted_output object (FR-11). The
redacted text itself never passes through this function.
"""
import json
import os
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

INPUT_NOTES_BUCKET = os.environ["INPUT_NOTES_BUCKET"]
MAX_NOTE_LENGTH = 20000  # Comprehend Medical's own single-document limit
DOWNLOAD_URL_EXPIRY_SECONDS = 300


def _response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, context):
    route_key = event.get("requestContext", {}).get("routeKey")

    if route_key == "POST /upload":
        return upload_note(event)
    if route_key == "GET /notes/{note_id}":
        return get_note(event)
    return _response(404, {"error": "Not found"})


def upload_note(event):
    s3 = boto3.client("s3")

    try:
        body = json.loads(event["body"])
        note_text = body["content"]
    except (KeyError, json.JSONDecodeError, TypeError):
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Request body must be JSON with a 'content' field"}),
        }

    # Non-string content (int, null) previously reached note_text.encode()
    # uncaught -- an AttributeError the caller saw as a raw 500. Empty or
    # oversized content previously passed straight through to a 202, only
    # to fail later inside pipeline_lambda with no way back to the caller.
    if not isinstance(note_text, str) or not note_text.strip():
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "'content' must be a non-empty string"}),
        }
    if len(note_text) > MAX_NOTE_LENGTH:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"'content' must be {MAX_NOTE_LENGTH} characters or fewer"}),
        }

    # UUID, not the original filename or anything patient-derived -- same
    # "never derive a name from identifying content" principle already
    # applied to write_report()'s timestamp-based filenames.
    note_id = str(uuid.uuid4())

    s3.put_object(Bucket=INPUT_NOTES_BUCKET, Key=f"{note_id}.txt", Body=note_text.encode("utf-8"))

    return _response(202, {"status": "accepted", "note_id": note_id})


def is_valid_note_id(note_id) -> bool:
    """True only for a UUID in the exact canonical form upload_note() issues.

    uuid.UUID() alone is too lenient -- it also accepts braces, a "urn:uuid:"
    prefix, uppercase and missing hyphens, all of which would build a
    different S3 key than the one written. Requiring the round-trip to
    match means the only keys this route can ever touch are ones shaped
    exactly like ours.
    """
    if not isinstance(note_id, str):
        return False
    try:
        return str(uuid.UUID(note_id)) == note_id
    except ValueError:
        return False


def get_note(event):
    note_id = (event.get("pathParameters") or {}).get("note_id")
    if not is_valid_note_id(note_id):
        return _response(400, {"error": "note_id must be a UUID"})

    # Read lazily, not at module level -- same reason as review_backend.py:
    # a module-level read would make every upload test set this too.
    bucket = os.environ["REDACTED_OUTPUT_BUCKET"]
    key = f"{note_id}.json"  # lambda_handler.py's output_key for "<uuid>.txt"

    # SigV4 explicitly: S3 refuses presigned GETs for SSE-KMS objects signed
    # any other way, and redacted_output is SSE-KMS.
    s3 = boto3.client("s3", config=Config(signature_version="s3v4"))

    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        # 403 as well as 404: the role deliberately has no s3:ListBucket, and
        # without it S3 answers a HEAD on a missing key with 403, not 404.
        if error.response["Error"]["Code"] in ("404", "403", "NoSuchKey"):
            # One answer for "still processing" and "never existed", so the
            # endpoint can't be used to confirm whether an ID was ever valid.
            return _response(404, {"status": "processing",
                                   "message": "Not available yet -- still processing, or no such note"})
        raise

    download_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{note_id}.json"',
        },
        ExpiresIn=DOWNLOAD_URL_EXPIRY_SECONDS,
    )
    return _response(200, {"download_url": download_url})