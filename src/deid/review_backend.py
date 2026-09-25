# src/deid/review_backend.py
"""Backend Lambda for the Reviewer web UI. Lists and decrypts flagged
entities in review-artifacts, same underlying operations as
review_cli.py, but as an HTTP API Lambda integration behind Cognito.

Group-membership checking lives here, in application code, because it
has to -- HTTP API's native JWT authorizer only supports OAuth
scope-based checks, confirmed against AWS's own documentation; it
cannot inspect an arbitrary claim like cognito:groups at all. The JWT
authorizer already guarantees "this is a genuinely valid, logged-in
user" before this code ever runs -- this function only ever needs to
answer the second, narrower question: "is this specific logged-in user
a Reviewer."
"""
import json
import os

import boto3
from botocore.exceptions import ClientError

from src.deid.review_cli import list_pending_reviews, get_review_entries

REVIEWER_GROUP = "Reviewers"


def parse_groups(raw) -> list[str]:
    """Normalise the cognito:groups claim to a list of group names.

    The raw token carries a JSON array, but API Gateway may hand it to
    the Lambda flattened into a string -- "[Reviewers Operators]" or
    "Reviewers,Operators" depending on the authorizer type. Cognito group
    names can't contain whitespace, so splitting on whitespace and commas
    recovers the exact names either way.
    """
    if isinstance(raw, list):
        return raw
    return raw.strip("[]").replace(",", " ").split()


def is_reviewer(claims: dict) -> bool:
    # Exact membership, not substring: "Reviewers" in "ReviewersPending"
    # is True for a string, which would grant access to the wrong group.
    return REVIEWER_GROUP in parse_groups(claims.get("cognito:groups", ""))


def _response(status: int, body) -> dict:
    return {"statusCode": status, "body": json.dumps(body)}


def handler(event, context):
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    if not is_reviewer(claims):
        return _response(403, {"error": "Not authorized"})

    s3 = boto3.client("s3")
    route_key = event["requestContext"]["routeKey"]

    if route_key == "GET /reviews":
        return _response(200, list_pending_reviews(s3))

    if route_key == "GET /reviews/{key}":
        key = event["pathParameters"]["key"]
        kms = boto3.client("kms")
        # Read lazily, not at module level -- a module-level os.environ[...]
        # read happens once at import time, before any test fixture runs,
        # which would make this module impossible to import in a test
        # environment. Reading it here is also what lets monkeypatch.setenv()
        # actually control this in tests.
        key_id = os.environ["REVIEW_ARTIFACTS_KMS_KEY_ID"]
        try:
            entries = get_review_entries(s3, key, kms, key_id)
        except ClientError as error:
            if error.response["Error"]["Code"] == "NoSuchKey":
                return _response(404, {"error": "Not found"})
            raise
        return _response(200, entries)

    return _response(404, {"error": "Not found"})
