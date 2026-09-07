"""Tests for the combined detection entry point (FR-2 + FR-8).

get_all_entities() is a three-line composition of detect_phi() and the
regex backstop, and both halves are already covered on their own
(tests/test_detect.py, tests/test_phone_backstop.py). So these tests
deliberately do *not* re-test either half. They cover the two things
only the composition can get wrong:

  1. The wiring — the client and the note text reaching detect_phi()
     unchanged, and the regex running over that same string. Two
     different strings here would produce two sets of offsets indexing
     different texts, and redact() would cut the wrong spans.
  2. The payoff — that combining the two sources actually closes the
     Australian mobile gap documented in docs/decision-log.md, end to
     end through redact(). This is the claim the module exists to make;
     nothing below get_all_entities() can assert it.

Everything here runs against the recorded response in
tests/fixtures/detect_phi_response.json, so the API half is what
Comprehend Medical really returns for the sample note — including its
mis-typed, truncated "0412 345" span at score 0.383.
"""

import pytest

from src.deid.redact import redact
from src.deid.resolve_entities import get_all_entities
from tests.fixtures.recorded_entities import RECORDED_ENTITIES, TEXT, entity

# The project threshold, settled under FR-4 on 2026-09-07 — see
# docs/decision-log.md, "FR-4 resolved". Nothing below should depend on
# its exact value; the point of the backstop is that the phone entity
# now scores 1.0 and clears any threshold at all.
CURRENT_MIN_SCORE = 0.001

PHONE = "0412 345 678"


class FakeClient:
    """Stands in for a boto3 comprehendmedical client.

    Same shape as the fake in tests/test_detect.py, redefined rather than
    imported so the two test modules stay independently editable.
    """

    def __init__(self, response=None, error=None):
        self._response = response if response is not None else {"Entities": []}
        self._error = error
        self.calls = []

    def detect_phi(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _entities_covering(entities, fragment=PHONE, text=TEXT):
    """Every entity whose span overlaps `fragment`'s position in `text`."""
    start = text.index(fragment)
    end = start + len(fragment)
    return [e for e in entities if e["BeginOffset"] < end and e["EndOffset"] > start]


# --- Wiring ---------------------------------------------------------------


def test_sends_the_note_text_to_the_api_unchanged():
    """The API must see exactly the string the regex is run over.

    If these ever diverge — a strip(), a normalisation, a different
    variable — the two halves of the merged list would carry offsets
    into two different strings, and redact() would cut the wrong spans
    with no error to show for it.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    get_all_entities(client, TEXT)

    assert client.calls == [{"Text": TEXT}]


def test_api_errors_propagate():
    """A swallowed AWS error would leave only the regex entities, which
    on most notes means a near-empty entity list and a note that looks
    cleanly processed while every name and date survives. That is a
    false all-clear, the worst failure mode this tool has — so the
    backstop must not quietly become a fallback path.
    """
    client = FakeClient(error=RuntimeError("SubscriptionRequiredException"))

    with pytest.raises(RuntimeError, match="SubscriptionRequiredException"):
        get_all_entities(client, TEXT)


def test_api_entities_that_overlap_nothing_are_all_preserved():
    """Adding the backstop must not cost any existing detection.

    The five non-phone entities in the recorded response have no regex
    match anywhere near them and must survive the merge untouched,
    scores and types included.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    entities = get_all_entities(client, TEXT)

    untouched = [e for e in RECORDED_ENTITIES if e["Text"] != "0412 345"]
    for expected in untouched:
        assert expected in entities


def test_returns_entities_ordered_by_offset():
    """The merged list is sorted by BeginOffset.

    redact() re-sorts for itself, so this is not load-bearing for the
    redacted text — but the audit trail (FR-6) is built by walking the
    entity list, and a merged list in arbitrary order would make a
    note's audit records unstable between runs.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    entities = get_all_entities(client, TEXT)

    offsets = [e["BeginOffset"] for e in entities]
    assert offsets == sorted(offsets)


# --- The gap this module closes (FR-8) ------------------------------------


def test_truncated_api_phone_entity_is_replaced_by_the_full_span():
    """The mis-detection case from docs/decision-log.md.

    Comprehend Medical returns "0412 345" (Type ID, score 0.383) — the
    right number, the wrong span and the wrong type. After the merge
    there must be exactly ONE entity covering this number: the regex's
    full-span PHONE_OR_FAX at 1.0. Two overlapping entities here is not
    merely redundant, it corrupts the output, because redact() would
    substitute both spans.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    entities = get_all_entities(client, TEXT)
    covering = _entities_covering(entities)

    assert len(covering) == 1
    assert covering[0]["Text"] == PHONE
    assert covering[0]["Type"] == "PHONE_OR_FAX"
    assert covering[0]["Score"] == 1.0


def test_undetected_international_format_is_caught_by_the_backstop():
    """The silent-miss case: "+61 412 345 678" comes back from
    Comprehend Medical with no entity at all, so there is nothing to
    replace and nothing to lower a threshold below. The regex is the
    only source of this entity, which is why a backstop rather than a
    threshold change was the fix.
    """
    text = "Patient contact: +61 412 345 678. Follow up Monday."
    client = FakeClient({"Entities": []})

    entities = get_all_entities(client, text)

    assert [e["Text"] for e in entities] == ["+61 412 345 678"]
    assert entities[0]["Type"] == "PHONE_OR_FAX"


def test_notes_with_no_phone_number_are_unaffected():
    """The backstop is additive only. On a note the regex does not fire
    on, get_all_entities() must return precisely what the API returned —
    no extra entity, no dropped one.

    Entities are built against this note's own text rather than filtered
    out of RECORDED_ENTITIES: those carry offsets into sample_note.txt,
    which would be wrong for this shorter string. Nothing here would
    catch that today — the assertion never reaches redact() — but an
    entity whose offsets don't index the text beside it is a trap to
    leave lying around in this suite of all places.
    """
    text = "Patient John Smith, DOB 14/03/1982, seen 02/06/2026."
    api_entities = [
        entity("John Smith", "NAME", 0.9997, text=text),
        entity("14/03/1982", "DATE", 0.9999, text=text),
        entity("02/06/2026", "DATE", 0.9999, text=text),
    ]
    client = FakeClient({"Entities": api_entities})

    assert get_all_entities(client, text) == api_entities


# --- End to end through redact() ------------------------------------------


def test_phone_number_does_not_survive_redaction():
    """The whole point, asserted end to end.

    tests/test_redact.py pins the *unfixed* behaviour with two strict
    xfails: against RECORDED_ENTITIES alone, "0412 345 678" survives at
    min_score=0.5, and even at 0.0 the truncated span leaves "678"
    behind. Routed through get_all_entities() instead, neither happens —
    no digit of the number reaches the output.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    entities = get_all_entities(client, TEXT)
    redacted_text, _ = redact(TEXT, entities, min_score=CURRENT_MIN_SCORE)

    assert PHONE not in redacted_text
    assert "0412" not in redacted_text
    assert "678" not in redacted_text
    assert "[PHONE_OR_FAX]" in redacted_text


def test_the_rest_of_the_note_still_redacts_correctly():
    """The other identifiers must still go, and the surrounding clinical
    content must still stay. Guards against the merged list shifting an
    offset and cutting the wrong span elsewhere in the note.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    entities = get_all_entities(client, TEXT)
    redacted_text, _ = redact(TEXT, entities, min_score=CURRENT_MIN_SCORE)

    assert "John Smith" not in redacted_text
    assert "14/03/1982" not in redacted_text
    assert "St Vincent" not in redacted_text
    assert "02/06/2026" not in redacted_text
    assert "Sarah Chen" not in redacted_text
    assert "with chest pain" in redacted_text


def test_audit_trail_records_the_phone_as_a_redacted_phone_number():
    """FR-6: the audit record must say what was removed.

    Before the backstop, the phone produced either no record at all (the
    "+61" case) or one reading type ID, score 0.383,
    flagged_low_confidence — an audit trail that misdescribes a redacted
    phone number as an unredacted low-confidence identifier.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    entities = get_all_entities(client, TEXT)
    _, audit_records = redact(TEXT, entities, min_score=CURRENT_MIN_SCORE)

    phone_records = [r for r in audit_records if r["type"] == "PHONE_OR_FAX"]
    assert phone_records == [
        {"type": "PHONE_OR_FAX", "score": 1.0, "action": "redacted"}
    ]
    assert not any(r["type"] == "ID" for r in audit_records)
