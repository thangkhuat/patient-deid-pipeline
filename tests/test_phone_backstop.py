"""Tests for the Australian mobile number detection backstop.

See docs/decision-log.md for why this exists: Comprehend Medical's
documented US-EN training bias causes three failure modes on Australian
mobile numbers (mis-typed, truncated, silent miss) that no confidence
threshold can fix. Landlines are explicitly out of scope -- see
decision-log.md.
"""

import pytest

from src.deid.phone_backstop import detect_au_mobile, resolve_overlaps

text = "Patient John Doe, DOB 14/03/1982, lives at 123 Main St, contact 0412 345 678. Attending physician: Dr. Sarah Chen."

def _entity(fragment, type_, score):
    start = text.index(fragment)
    return {
        "Id": None, "BeginOffset": start, "EndOffset": start + len(fragment),
        "Score": score, "Text": fragment,
        "Category": "PROTECTED_HEALTH_INFORMATION", "Type": type_, "Traits": [],
    }

# --- Positive cases: every real format variation should be caught ---------

@pytest.mark.parametrize("text", [
    "0412 345 678",
    "0412345678",
    "0412-345-678",
    "0412.345.678",
    "+61 412 345 678",
    "+61412345678",
    "+61-412-345-678",
])
def test_detects_au_mobile_format_variations(text):
    """Spaces, dashes, dots, no separator, both prefixes -- all should
    be detected as a single complete entity covering the whole number.
    """
    assert detect_au_mobile(text) == [{"Id": None, "BeginOffset": 0, "EndOffset": len(text), "Score": 1.0, "Text": text, "Category": "PROTECTED_HEALTH_INFORMATION", "Type": "PHONE_OR_FAX", "Traits": []}]

def test_detects_au_mobile_embedded_in_sentence():
    """A phone number surrounded by real text -- the only way this
    function will ever actually be used -- should be found at its
    correct, non-zero position. Every case in the parametrized test
    above happens to have BeginOffset == 0 trivially, since the input
    there is only ever the phone number alone; this is the one case
    that would actually catch the regex matching the wrong slice of a
    larger string.
    """
    entities = detect_au_mobile(text)
    assert entities == [_entity("0412 345 678", "PHONE_OR_FAX", 1.0)]


# --- Negative cases: should NOT fire on things outside scope ---------------

@pytest.mark.parametrize("text", [
    "415-555-0132",       # US format
    "(415) 555-0132",     # US format
    "(03) 9345 6789",     # AU landline -- explicitly out of scope
])
def test_does_not_match_non_mobile_formats(text):
    """US numbers and AU landlines are out of scope -- Comprehend
    Medical already handles them correctly.
    """
    assert detect_au_mobile(text) == []

# --- Entity shape -----------------------------------------------------

def test_regex_entities_have_correct_score_and_type():
    """Score == 1.0 (deterministic match, not a confidence guess).
    Type == "PHONE_OR_FAX" -- matches Comprehend Medical's own label,
    deliberately not a distinct backstop-specific type (see
    decision-log.md on why a separate type would leak through the
    audit trail).
    """
    assert detect_au_mobile("0412 345 678") == [{"Id": None, "BeginOffset": 0, "EndOffset": len("0412 345 678"), "Score": 1.0, "Text": "0412 345 678", "Category": "PROTECTED_HEALTH_INFORMATION", "Type": "PHONE_OR_FAX", "Traits": []}]

# --- Overlap resolution ----------------------------------------------
def test_regex_entity_replaces_overlapping_api_entity():
    """Given Comprehend Medical's real broken entity for "0412 345"
    (Type ID, offset 117-125, score 0.383) alongside a regex match
    covering the full "0412 345 678", the resolved list should contain
    exactly ONE entity for this phone number -- the regex's -- not
    both. Two overlapping entities here reproduces the ADDRESS/CITY
    corruption bug, on data already known to trigger it.
    """
    api_entities = [
        _entity("0412 345", "ID", 0.383),
    ]

    regex_entities = detect_au_mobile(text)

    resolved = resolve_overlaps(api_entities, regex_entities)
    assert resolved == [regex_entities[0]]

def test_resolve_leaves_non_overlapping_entities_untouched():
    """Entities that don't overlap any regex match (NAME, DATE,
    ADDRESS from the sample note) should pass through unchanged.
    """

    api_entities = [
        _entity("John Doe", "NAME", 0.99),
        _entity("14/03/1982", "DATE", 0.95),
        _entity("123 Main St", "ADDRESS", 0.90),
    ]

    regex_entities = detect_au_mobile(text)
    resolved = resolve_overlaps(api_entities, regex_entities)
    assert resolved == api_entities + regex_entities

def test_non_overlapping_entity_after_an_overlap_is_preserved():
    """A real bug, caught by hand: the pointer-advancement logic could
    silently skip an entity immediately following an overlapping one.
    Regression coverage for that specific failure mode.
    """
    api_entities = [
        _entity("0412 345", "ID", 0.383),
        {"Id": None, "BeginOffset": text.index("Sarah Chen"),
         "EndOffset": text.index("Sarah Chen") + len("Sarah Chen"),
         "Score": 0.93, "Text": "Sarah Chen",
         "Category": "PROTECTED_HEALTH_INFORMATION", "Type": "NAME", "Traits": []},
    ]
    regex_entities = detect_au_mobile(text)
    resolved = resolve_overlaps(api_entities, regex_entities)
    assert any(e["Text"] == "Sarah Chen" for e in resolved)
