"""Entry point: load a note, detect PHI, redact it, print the result."""

import boto3
from pathlib import Path
from src.deid.report import get_output_directory, load_encryption_key, build_report, write_report
from src.deid.redact import redact
from src.deid.resolve_entities import get_all_entities


MIN_SCORE = 0.001
REVIEW_THRESHOLD = 0.8

def load_note(path: str) -> str:
    """Read a clinical note (plaintext) from disk.

    """
    with open(path, encoding="utf-8") as file:
        return file.read()


def main():
    session = boto3.Session(profile_name="patient-deid")
    client = session.client("comprehendmedical", region_name="ap-southeast-2")
    note_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "review_queue_demo_note.txt"

    text = load_note(note_path)
    entities = get_all_entities(client, text)
    redacted_text, audit_records = redact(text, entities, min_score=MIN_SCORE)

    key = load_encryption_key()
    output_dir = get_output_directory()
    report = build_report(redacted_text, audit_records, entities, key,
                           min_score=MIN_SCORE, review_threshold=REVIEW_THRESHOLD)
    report_path = write_report(report, output_dir)

    print(f"Report written to {report_path}")

if __name__ == "__main__":
    main()
