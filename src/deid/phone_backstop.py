import re
from typing import List

# Define regex patterns for Australian mobile phone numbers
_PATTERN = re.compile(r'(?<!\d)(?:\+61[\s.-]?4|04)\d{2}[\s.-]?\d{3}[\s.-]?\d{3}(?!\d)')

def detect_au_mobile(text: str) -> List[dict]:
    """Detect Australian mobile phone numbers in text.

    Args:
        text: clinical text to inspect.

    Returns:
        A list of entity dicts, each with keys Id, BeginOffset, EndOffset, Score, Text, Category, Type, and Traits.
    """

    entities = []

    for match in _PATTERN.finditer(text):
        start, end = match.span()
        entity = {
            "Id": None,
            "BeginOffset": start,
            "EndOffset": end,
            "Score": 1.0,
            "Text": match.group(),
            "Category": "PROTECTED_HEALTH_INFORMATION",
            "Type": "PHONE_OR_FAX",
            "Traits": [],
        }
        entities.append(entity)
    return entities

def resolve_overlaps(entities: List[dict], regex_entities: List[dict]) -> List[dict]:
    """Resolve overlaps between API entities and regex entities.

    Where a Comprehend Medical entity overlaps a regex match, the API
    entity is dropped and the regex entity is kept exactly as detected.
    This is replacement, not a merged span: see docs/decision-log.md,
    "Overlapping entities: replace with the regex entity's exact span,
    not union", for why the union alternative was rejected.

    Offsets are half-open, so spans that merely touch (one EndOffset
    equal to the other BeginOffset) do not overlap and both survive.

    Args:
        entities: entity dicts as returned by detect_phi().
        regex_entities: entity dicts as returned by detect_au_mobile().

    Returns:
        A list of entity dicts sorted by BeginOffset: every regex entity,
        plus every API entity that overlapped none of them.
    """

    sorted_entities = sorted(entities, key=lambda e: e["BeginOffset"])
    regex_entities = sorted(regex_entities, key=lambda e: e["BeginOffset"])

    entities_index = 0
    regex_index = 0

    result = []
    while entities_index < len(sorted_entities) and regex_index < len(regex_entities):

        if sorted_entities[entities_index]["EndOffset"] <= regex_entities[regex_index]["BeginOffset"]:
            result.append(sorted_entities[entities_index])
            entities_index += 1
            continue
        elif sorted_entities[entities_index]["BeginOffset"] >= regex_entities[regex_index]["EndOffset"]:
            result.append(regex_entities[regex_index])
            regex_index += 1
            continue
        else:
            entities_index += 1

    while entities_index < len(sorted_entities):
        result.append(sorted_entities[entities_index])
        entities_index += 1

    while regex_index < len(regex_entities):
        result.append(regex_entities[regex_index])
        regex_index += 1

    return result
