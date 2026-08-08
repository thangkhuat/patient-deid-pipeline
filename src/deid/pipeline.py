"""Entry point: load a note, detect PHI, redact it, print the result."""

import boto3

from deid.detect import detect_phi
from deid.redact import redact


def load_note(path: str) -> str:
    """Read a clinical note (plaintext) from disk.

    TODO: implement.
    """
    raise NotImplementedError


def main() -> None:
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")
    text = load_note("tests/fixtures/sample_note.txt")

    # Step 1 (do this first, alone): confirm detect_phi() works.
    entities = detect_phi(client, text)
    print(entities)

    # Step 2 (only after step 1 looks right): wire up redact().
    # redacted_text, audit = redact(text, entities, min_score=...)
    # print(redacted_text)


if __name__ == "__main__":
    main()
