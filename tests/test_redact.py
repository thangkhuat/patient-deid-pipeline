"""Tests for the redaction module.

See docs/technical-requirements.md, "Testing requirements".
"""

from src.deid.redact import redact
from tests.fixtures.mock_entities import MOCK_ENTITIES, TEXT


def test_no_safe_harbor_categories_leak_in_output():
    """The core success criterion from functional-requirements.md:

    Zero literal instances of the 18 Safe Harbor categories remain in
    output text. Fill this in once redact() exists — load
    tests/fixtures/sample_note.txt, run it through detect + redact, and
    assert none of the known identifiers (the name, the DOB, the phone
    number, the physician's name) appear in the output.
    """
    redacted_text, audit_records = redact(TEXT, MOCK_ENTITIES, min_score = 0.5)
    assert "John Smith" not in redacted_text
    assert "14/03/1982" not in redacted_text
    assert "St Vincent's Hospital" in redacted_text
    assert "02/06/2026" not in redacted_text
    assert "0412 345 678" not in redacted_text
    assert "Sarah Chen" not in redacted_text

def test_redact_returns_audit_record_per_entity():
    """FR-6: every detected entity should produce a corresponding audit
    record with category, confidence score, and action taken."""
    redacted_text, audit_records = redact(TEXT, MOCK_ENTITIES, min_score = 0.5)
    assert len(audit_records) == len(MOCK_ENTITIES)