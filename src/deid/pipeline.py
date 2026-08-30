"""Entry point: load a note, detect PHI, redact it, print the result."""

import boto3

from src.deid.detect import detect_phi
from src.deid.redact import redact
from tests.fixtures.mock_entities import MOCK_ENTITIES


def load_note(path: str) -> str:
    """Read a clinical note (plaintext) from disk.

    """
    with open(path, encoding="utf-8") as file:
        return file.read()


def main() -> None:
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")
    text = load_note("tests/fixtures/sample_note.txt")

    # # Step 1 (do this first, alone): confirm detect_phi() works.
    # entities = detect_phi(client, text)
    # print(entities)

    # Step 2 (only after step 1 looks right): wire up redact().
    redacted_text, audit = redact(text, MOCK_ENTITIES, min_score=0.5)
    print(redacted_text)


if __name__ == "__main__":
    main()
