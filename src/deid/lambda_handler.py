import json
import os

import boto3

from src.deid.resolve_entities import get_all_entities
from src.deid.redact import redact
from src.deid.report import build_report

MIN_SCORE = 0.001
REVIEW_THRESHOLD = 0.8
FRONTEND_URL = "https://d2tno7uvqes2o4.cloudfront.net/review.html"

REDACTED_OUTPUT_BUCKET = os.environ["REDACTED_OUTPUT_BUCKET"]
REVIEW_ARTIFACTS_BUCKET = os.environ["REVIEW_ARTIFACTS_BUCKET"]
REVIEW_ARTIFACTS_KMS_KEY_ID = os.environ["REVIEW_ARTIFACTS_KMS_KEY_ID"]
REVIEW_NOTIFICATIONS_TOPIC_ARN = os.environ["REVIEW_NOTIFICATIONS_TOPIC_ARN"]


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

    report = build_report(redacted_text, audit_records, entities, kms_client, REVIEW_ARTIFACTS_KMS_KEY_ID,
                           min_score=MIN_SCORE, review_threshold=REVIEW_THRESHOLD)

    output_key = input_key.rsplit(".", 1)[0] + ".json"

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

    if report["review_queue"]:
        # Never include entry['content'] or entry['type'] here -- see
        # decision-log.md. A notification failure must not fail an
        # otherwise-successful run, so this is deliberately isolated
        # and only logged, never raised.
        try:
            sns = boto3.client("sns")
            count = len(report["review_queue"])
            entity_word = "entity" if count == 1 else "entities"
            sns.publish(
                TopicArn=REVIEW_NOTIFICATIONS_TOPIC_ARN,
                Subject="Patient De-ID: new item awaiting review",
                Message=(
                    f"{count} flagged {entity_word} awaiting review.\n\n"
                    f"Reference: {output_key}\n\n"
                    f"Review here: {FRONTEND_URL}\n\n"
                    "No patient content is included in this notification."
                ),
            )
        except Exception as error:
            print(f"Review notification failed for {output_key}: {error}")

    return {"statusCode": 200, "body": f"Processed {input_key}"}