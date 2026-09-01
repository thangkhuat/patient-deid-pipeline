"""Tests for the redaction module.

See docs/technical-requirements.md, "Testing requirements".

These run against tests/fixtures/detect_phi_response.json — a real
DetectPHI response recorded from live AWS — so what they assert is what
Comprehend Medical actually does to the sample note, not what a
hand-built mock guessed it would do.

Tests that exercise threshold behaviour pass min_score explicitly rather
than relying on a project-wide default: FR-4's real threshold is still an
open decision (docs/decision-log.md), and these tests should not quietly
become the thing that settles it.
"""

import pytest

from src.deid.redact import redact
from tests.fixtures.recorded_entities import RECORDED_ENTITIES, TEXT, entity

# The threshold pipeline.py currently runs with. Provisional, not settled.
CURRENT_MIN_SCORE = 0.5


# --- FR-3 / FR-5: redacted text ------------------------------------------


def test_confidently_detected_identifiers_do_not_survive():
    """The core success criterion from functional-requirements.md.

    The phone number is deliberately absent from this list — Comprehend
    Medical mis-detects it, and that known failure is pinned by
    test_phone_number_still_leaks below rather than hidden here.
    """
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert "John Smith" not in redacted_text
    assert "14/03/1982" not in redacted_text
    assert "St Vincent" not in redacted_text
    assert "02/06/2026" not in redacted_text
    assert "Sarah Chen" not in redacted_text


def test_each_redacted_entity_becomes_its_type_placeholder():
    """FR-3: replacement is a category tag, not a surrogate value."""
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert "[NAME]" in redacted_text
    assert "[DATE]" in redacted_text
    assert "[ADDRESS]" in redacted_text


def test_non_phi_text_is_left_untouched():
    """Redaction removes identifiers, not clinical content."""
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert "chest pain" in redacted_text
    assert "Attending physician" in redacted_text


def test_offsets_are_applied_to_the_original_string():
    """The constraint in docs/technical-requirements.md.

    Placeholders differ in length from the text they replace, so applying
    offsets naively left-to-right shifts every later entity. Two DATEs of
    different surrounding length plus a long ADDRESS make that failure
    visible: if offsets shifted, the placeholders would land mid-word and
    the surrounding words would be corrupted.
    """
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert redacted_text.startswith("Patient [NAME], DOB [DATE], presented to")
    assert "on [DATE]" in redacted_text
    assert "physician: Dr. [NAME]." in redacted_text


def test_no_entities_returns_the_text_unchanged():
    redacted_text, audit_records = redact(TEXT, [], min_score=CURRENT_MIN_SCORE)

    assert redacted_text == TEXT
    assert audit_records == []


def test_entity_at_the_very_start_and_end_of_the_text():
    """Boundary case the recorded response does not contain."""
    text = "Smith presented. Seen by Chen"
    entities = [
        entity("Smith", "NAME", 0.99, text=text),
        entity("Chen", "NAME", 0.99, text=text),
    ]

    redacted_text, _ = redact(text, entities, min_score=CURRENT_MIN_SCORE)

    assert redacted_text == "[NAME] presented. Seen by [NAME]"


def test_adjacent_entities_do_not_corrupt_each_other():
    """Two entities separated by a single character, neither the same
    length as its placeholder."""
    text = "DOB 14/03/1982 02/06/2026 end"
    entities = [
        entity("14/03/1982", "DATE", 0.99, text=text),
        entity("02/06/2026", "DATE", 0.99, text=text),
    ]

    redacted_text, _ = redact(text, entities, min_score=CURRENT_MIN_SCORE)

    assert redacted_text == "DOB [DATE] [DATE] end"


def test_entities_out_of_document_order_are_still_redacted_correctly():
    """detect_phi() returns entities in document order today, but nothing
    in the contract promises that. Redaction must not depend on it."""
    shuffled = list(reversed(RECORDED_ENTITIES))

    from_shuffled, _ = redact(TEXT, shuffled, min_score=CURRENT_MIN_SCORE)
    from_ordered, _ = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert from_shuffled == from_ordered


# --- FR-4: threshold behaviour -------------------------------------------


def test_entities_below_min_score_are_left_in_the_text():
    """Current documented behaviour, asserted so a change to it is visible.

    This is the mechanism that causes the phone leak below. It is pinned
    here as *what the code does*, not as what it should do — FR-4's
    threshold decision is still open.
    """
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=0.5)

    assert "0412 345" in redacted_text


def test_lowering_the_threshold_redacts_the_low_confidence_entity():
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=0.0)

    assert "[ID]" in redacted_text
    assert "0412 345" not in redacted_text


def test_threshold_is_inclusive_at_the_boundary():
    """An entity scoring exactly min_score is redacted, not skipped."""
    text = "Seen by Chen"
    entities = [entity("Chen", "NAME", 0.5, text=text)]

    redacted_text, _ = redact(text, entities, min_score=0.5)

    assert redacted_text == "Seen by [NAME]"


# --- FR-6: audit records -------------------------------------------------


def test_one_audit_record_per_detected_entity():
    _, audit_records = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert len(audit_records) == len(RECORDED_ENTITIES)


def test_every_audit_record_has_the_three_FR6_fields():
    """FR-6: category, confidence score, and action taken.

    Note the naming mismatch flagged in review: FR-6 says "category", the
    record stores Comprehend Medical's `Type` under the key "type".
    Storing Type is the useful choice — `Category` is always
    PROTECTED_HEALTH_INFORMATION for DetectPHI — but the FR wording and
    the key should be reconciled.
    """
    _, audit_records = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    for record in audit_records:
        assert set(record) == {"type", "score", "action"}
        assert isinstance(record["type"], str)
        assert isinstance(record["score"], float)
        assert record["action"] in {"redacted", "flagged_low_confidence"}


def test_audit_action_reflects_whether_the_entity_was_redacted():
    _, audit_records = redact(TEXT, RECORDED_ENTITIES, min_score=0.5)

    by_type = {r["type"]: r for r in audit_records}
    assert by_type["NAME"]["action"] == "redacted"
    assert by_type["ID"]["action"] == "flagged_low_confidence"


def test_low_confidence_entities_are_recorded_not_dropped():
    """FR-6 covers every *detected* entity, including ones left in the
    text. An identifier that survives redaction unrecorded would be
    invisible to an auditor."""
    _, audit_records = redact(TEXT, RECORDED_ENTITIES, min_score=0.5)

    flagged = [r for r in audit_records if r["action"] == "flagged_low_confidence"]
    assert len(flagged) == 1
    assert flagged[0]["score"] == pytest.approx(0.383, abs=0.001)


def test_audit_scores_match_the_detected_entities():
    _, audit_records = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert sorted(r["score"] for r in audit_records) == sorted(
        e["Score"] for e in RECORDED_ENTITIES
    )


# --- Known limitations (FR-8) --------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known open failure, not yet fixed: Comprehend Medical returns the "
        "Australian mobile 0412 345 678 as the partial span '0412 345' typed "
        "ID at score 0.383. At the provisional min_score=0.5 it falls below "
        "threshold and the full number survives. See docs/decision-log.md, "
        "'Sample note phone number is not reliably detected'. This test "
        "turns green when the leak is fixed."
    ),
)
def test_phone_number_still_leaks():
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=CURRENT_MIN_SCORE)

    assert "0412 345 678" not in redacted_text


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known open failure, not yet fixed: even with the threshold at 0 the "
        "recorded span stops mid-number, so redaction yields '[ID] 678' and "
        "the trailing digits survive. Lowering min_score alone does not fix "
        "the phone case."
    ),
)
def test_lowering_the_threshold_is_not_enough_for_the_phone():
    redacted_text, _ = redact(TEXT, RECORDED_ENTITIES, min_score=0.0)

    assert "678" not in redacted_text
