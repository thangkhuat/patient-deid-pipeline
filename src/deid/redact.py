"""Redaction logic: entities detected -> redacted text + audit records.

See docs/decision-log.md for why this is irreversible, category-placeholder
based, and recall-biased.
"""


def redact(
    text: str,
    entities: list[dict],
    min_score: float,
) -> tuple[str, list[dict]]:
    """Redact detected PHI entities from text and produce an audit trail.

    Args:
        text: the original clinical text.
        entities: raw entity list from detect_phi().
        min_score: confidence threshold below which an entity is not
            redacted. Pick this deliberately after seeing real scores
            come back from Comprehend Medical — see the correction note
            in docs/technical-requirements.md before hardcoding a value.

    Returns:
        A tuple of (redacted_text, audit_records). audit_records is a list
        of dicts per FR-6: category, confidence score, and action taken
        ("redacted" or "flagged_low_confidence", for example) — exact
        shape is a design decision to make while building this.

    Note: BeginOffset/EndOffset in `entities` are positions in the
    *original* text. Replacing spans naively as you iterate will shift
    everything after the first replacement of a different length than the
    original. See docs/technical-requirements.md, "Redaction algorithm
    constraint" — worth sitting with this before writing the loop.

    """
    sorted_entities = sorted(entities, key=lambda x:x['BeginOffset'], reverse=True)
    redacted_text = text
    audit_records = []
    for entity in sorted_entities:
        if entity['Score'] >= min_score:
            redacted_text = redacted_text[0:entity['BeginOffset']] + f"[{entity['Type']}]" + redacted_text[entity['EndOffset']:]
            audit_record = {"type": entity['Type'], "score": entity['Score'], "action": "redacted"}
        else:
            audit_record = {"type": entity['Type'], "score": entity['Score'], "action": "flagged_low_confidence"}
        audit_records.append(audit_record)
    return (redacted_text, audit_records)