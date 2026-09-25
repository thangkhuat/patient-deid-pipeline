"""CLI for a Reviewer to find and decrypt flagged entities in
review-artifacts. Deliberately a local tool, not a web page -- see
decision-log.md for why: this role can safely hold real AWS credentials,
unlike the Operator's public browser page, and reviewer_test's existing
IAM/KMS access already provides real per-identity accountability with
nothing new to build.

Reuses decrypt_flagged_content() from report.py directly -- this file
is purely the missing interface around a function that already existed,
tested, since several sessions back. Encryption is direct KMS
Encrypt/Decrypt, not a local secret -- see decision-log.md.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import boto3

from src.deid.report import decrypt_flagged_content

REVIEW_ARTIFACTS_BUCKET = "patient-deid-review-artifacts"
REVIEW_ARTIFACTS_KMS_KEY_ID = "arn:aws:kms:ap-southeast-2:471116065597:key/f703113a-99c3-43df-8823-7864e5a32234"
MAX_CONCURRENT_FETCHES = 16


def list_pending_reviews(s3_client) -> dict[str, list[dict]]:
    """Find every object with a non-empty review_queue, returning each
    entry's unencrypted metadata (type, score, action) alongside it --
    no decryption performed here, since only content_encrypted is
    actually encrypted.

    The review queue lives inside each object's body, so this still
    costs one GetObject per artifact; fetching them concurrently keeps
    the wall-clock time inside review_backend's Lambda timeout as the
    bucket grows. It does not reduce the number of calls -- that needs
    an index or per-object metadata written by the pipeline.
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = [
        obj["Key"]
        for page in paginator.paginate(Bucket=REVIEW_ARTIFACTS_BUCKET)
        for obj in page.get("Contents", [])
    ]

    def fetch_queue(key):
        response = s3_client.get_object(Bucket=REVIEW_ARTIFACTS_BUCKET, Key=key)
        return json.loads(response["Body"].read()).get("review_queue", [])

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FETCHES) as pool:
        queues = pool.map(fetch_queue, keys)
    return {key: queue for key, queue in zip(keys, queues) if queue}


def get_review_entries(s3_client, key: str, kms_client, key_id: str) -> list[dict]:
    """Fetch and decrypt one object's review_queue, returning structured
    data -- type, score, action, and the decrypted content -- for the
    caller to present however it needs to. Shared by both the CLI and
    the web backend; neither prints or formats anything here.
    """
    response = s3_client.get_object(Bucket=REVIEW_ARTIFACTS_BUCKET, Key=key)
    data = json.loads(response["Body"].read())
    entries = []
    for entry in data.get("review_queue", []):
        entries.append({
            "type": entry["type"],
            "score": entry["score"],
            "action": entry["action"],
            "content": decrypt_flagged_content(entry["content_encrypted"], kms_client, key_id),
        })
    return entries


def main():
    parser = argparse.ArgumentParser(description="Review flagged PHI entities.")
    parser.add_argument("--profile", default="reviewer-test")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--review", metavar="KEY")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile)
    s3 = session.client("s3")
    kms = session.client("kms")

    if args.list:
        pending = list_pending_reviews(s3)
        if not pending:
            print("No items pending review.")
        for key, entries in pending.items():
            label = "entity" if len(entries) == 1 else "entities"
            print(f"{key}  ({len(entries)} flagged {label})")
            for entry in entries:
                print(f"    {entry['type']:<12} score={entry['score']:.4f}  action={entry['action']}")
    elif args.review:
        for entry in get_review_entries(s3, args.review, kms, REVIEW_ARTIFACTS_KMS_KEY_ID):
            print(f"Type: {entry['type']}")
            print(f"Score: {entry['score']}")
            print(f"Action: {entry['action']}")
            print(f"Decrypted content: {entry['content']}")
            print("-" * 40)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
