"""Accepts clinical note text via API Gateway and writes it to input-notes,
triggering the Pipeline Lambda's S3 event asynchronously. Does not detect,
redact, or wait for processing -- that's a genuinely separate concern,
decoupled on purpose (see decision-log.md, the event-driven architecture
choice).
"""
import json
import os
import uuid

import boto3

INPUT_NOTES_BUCKET = os.environ["INPUT_NOTES_BUCKET"]


def handler(event, context):
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

    # UUID, not the original filename or anything patient-derived -- same
    # "never derive a name from identifying content" principle already
    # applied to write_report()'s timestamp-based filenames.
    note_key = f"{uuid.uuid4()}.txt"

    s3.put_object(Bucket=INPUT_NOTES_BUCKET, Key=note_key, Body=note_text.encode("utf-8"))

    return {
        "statusCode": 202,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"message": "Note accepted for processing", "id": note_key}),
    }