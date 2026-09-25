# src/deid/lambda_handler.py
import json
import os

import boto3

from src.deid.resolve_entities import get_all_entities
from src.deid.redact import redact
from src.deid.report import build_report

MIN_SCORE = 0.001
REVIEW_THRESHOLD = 0.8

REDACTED_OUTPUT_BUCKET = os.environ["REDACTED_OUTPUT_BUCKET"]
REVIEW_ARTIFACTS_BUCKET = os.environ["REVIEW_ARTIFACTS_BUCKET"]
REVIEW_ARTIFACTS_KMS_KEY_ID = os.environ["REVIEW_ARTIFACTS_KMS_KEY_ID"]


def handler(event, context):
    s3 = boto3.client("s3")
    comprehend_client = boto3.client("comprehendmedical")
    kms_client = boto3.client("kms")

    record = event["Records"][0]["s3"]
    input_bucket = record["bucket"]["name"]
    input_key = record["object"]["key"]

    note = s3.get_object(Bucket=input_bucket, Key=input_key)["Body"].read().decode("utf-8")

    entities = get_all_entities(comprehend_client, note)
    redacted_text, audit_records = redact(note, entities, min_score=MIN_SCORE)

    report = build_report(redacted_text, audit_records, entities,
                          kms_client, REVIEW_ARTIFACTS_KMS_KEY_ID,
                          min_score=MIN_SCORE, review_threshold=REVIEW_THRESHOLD)

    output_key = input_key.rsplit(".", 1)[0] + ".json"

    # The FR-7 artifact split, implemented for real here -- build_report()
    # itself stays unchanged, one combined dict; this is where it actually
    # gets physically separated into two objects, in two buckets, so no
    # single file ever carries both redacted_text and review_queue together.
    s3.put_object(
        Bucket=REDACTED_OUTPUT_BUCKET,
        Key=output_key,
        Body=json.dumps({
            "redacted_text": report["redacted_text"],
            "audit_records": report["audit_records"],
        }).encode("utf-8"),
    )
    s3.put_object(
        Bucket=REVIEW_ARTIFACTS_BUCKET,
        Key=output_key,
        Body=json.dumps({"review_queue": report["review_queue"]}).encode("utf-8"),
    )

    return {"statusCode": 200, "body": f"Processed {input_key}"}