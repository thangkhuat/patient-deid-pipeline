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

import boto3

from src.deid.report import load_encryption_key, decrypt_flagged_content

REVIEW_ARTIFACTS_BUCKET = "patient-deid-review-artifacts"


import json

import boto3

from src.deid.report import load_encryption_key
from src.deid.review_cli import list_pending_reviews, get_review_entries

REVIEW_ARTIFACTS_BUCKET = "patient-deid-review-artifacts"


def is_reviewer(claims: dict) -> bool:
    return "Reviewers" in claims.get("cognito:groups", "")


def handler(event, context):
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    if not is_reviewer(claims):
        return {"statusCode": 403, "body": json.dumps({"error": "Not authorized"})}

    s3 = boto3.client("s3")
    route_key = event["requestContext"]["routeKey"]

    if route_key == "GET /reviews":
        pending = list_pending_reviews(s3)
        return {"statusCode": 200, "body": json.dumps(pending)}

    if route_key == "GET /reviews/{key}":
        key = event["pathParameters"]["key"]
        entries = get_review_entries(s3, key, load_encryption_key())
        return {"statusCode": 200, "body": json.dumps(entries)}

    return {"statusCode": 404, "body": json.dumps({"error": "Not found"})}