"""Entry point: load a note, detect PHI, redact it, print the result."""

import boto3
from pathlib import Path
from src.deid.redact import redact
from src.deid.resolve_entities import get_all_entities


def load_note(path: str) -> str:
    """Read a clinical note (plaintext) from disk.

    """
    with open(path, encoding="utf-8") as file:
        return file.read()


def main() -> None:
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")
    note_path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "sample_note.txt"
    text = load_note(note_path)
    print(text)
    print("----------------------------------------")

    # Detection: Comprehend Medical plus the AU mobile backstop, merged.
    # Always via get_all_entities() rather than detect_phi() directly, so
    # this path cannot silently lose the backstop.
    entities = get_all_entities(client, text)
    print(entities)
    print("----------------------------------------")

    # Redaction. 0.5 is provisional, not the FR-4 decision — see
    # docs/decision-log.md, "min_score stays at 0.5 provisionally".
    redacted_text, audit = redact(text, entities, min_score=0.5)
    print(redacted_text)


if __name__ == "__main__":
    main()
