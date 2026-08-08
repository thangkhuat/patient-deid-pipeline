"""Tests for the redaction module.

See docs/technical-requirements.md, "Testing requirements".
"""

import pytest

pytestmark = pytest.mark.skip(reason="redact() not implemented yet")


def test_no_safe_harbor_categories_leak_in_output():
    """The core success criterion from functional-requirements.md:

    Zero literal instances of the 18 Safe Harbor categories remain in
    output text. Fill this in once redact() exists — load
    tests/fixtures/sample_note.txt, run it through detect + redact, and
    assert none of the known identifiers (the name, the DOB, the phone
    number, the physician's name) appear in the output.
    """


def test_redact_returns_audit_record_per_entity():
    """FR-6: every detected entity should produce a corresponding audit
    record with category, confidence score, and action taken."""
