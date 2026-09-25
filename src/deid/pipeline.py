"""Entry point: load a note, detect PHI, redact it, write the report."""

import boto3
from pathlib import Path
from src.deid.report import (
    REVIEW_THRESHOLD,
    build_report,
    get_output_directory,
    write_report,
)
from src.deid.redact import redact
from src.deid.resolve_entities import get_all_entities
# pipeline.py is a local CLI like review_cli.py, with no Terraform-managed
# environment variable to read the key from -- so it shares that module's
# constant rather than hardcoding a second copy of the same ARN.
from src.deid.review_cli import REVIEW_ARTIFACTS_KMS_KEY_ID


# The FR-4 threshold, settled 2026-09-07 -- see docs/decision-log.md,
# "FR-4 resolved: min_score = 0.001". Derived from a stated cost ratio
# and measured scores, not a tuning knob: raising it silently leaves
# low-confidence PHI in the text. Changing it is a decision-log change.
MIN_SCORE = 0.001


def load_note(path: str) -> str:
    """Read a clinical note (plaintext) from disk.

    """
    with open(path, encoding="utf-8") as file:
        return file.read()


def main() -> None:
    session = boto3.Session(profile_name="patient-deid")
    client = session.client("comprehendmedical", region_name="ap-southeast-2")
    kms_client = session.client("kms", region_name="ap-southeast-2")
    note_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_note.txt"

    text = load_note(note_path)

    # Detection: Comprehend Medical plus the AU mobile backstop, merged.
    # Always via get_all_entities() rather than detect_phi() directly, so
    # this path cannot silently lose the backstop -- the failure mode is a
    # note that looks cleanly redacted with a phone number still in it.
    entities = get_all_entities(client, text)
    redacted_text, audit_records = redact(text, entities, min_score=MIN_SCORE)

    output_dir = get_output_directory()
    report = build_report(redacted_text, audit_records, entities,
                          kms_client, REVIEW_ARTIFACTS_KMS_KEY_ID,
                          min_score=MIN_SCORE, review_threshold=REVIEW_THRESHOLD)
    report_path = write_report(report, output_dir)

    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
