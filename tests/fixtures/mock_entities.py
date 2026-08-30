"""Mock PHI entities for sample_note.txt, shaped like a real DetectPHI response.

Exists to build and test redact() without depending on live AWS access.
Offsets are computed from the actual fixture file via .index(), not
hardcoded, so they stay correct if sample_note.txt ever changes.

Types/scores are a reasonable approximation, not verified against a real
API response — the hospital name's low score in particular is a guess at
how ambiguous that entity might be for the model, not a confirmed fact.
Swap for a real detect_phi() call once Comprehend Medical access clears —
see CLAUDE.md, "Current state."
"""

from pathlib import Path

_NOTE_PATH = Path(__file__).parent / "sample_note.txt"
TEXT = _NOTE_PATH.read_text(encoding="utf-8")


def _entity(fragment: str, type_: str, score: float) -> dict:
    start = TEXT.index(fragment)
    return {
        "Text": fragment,
        "Category": "PROTECTED_HEALTH_INFORMATION",
        "Type": type_,
        "Score": score,
        "BeginOffset": start,
        "EndOffset": start + len(fragment),
    }


MOCK_ENTITIES = [
    _entity("John Smith", "NAME", 0.99),
    _entity("14/03/1982", "DATE", 0.97),
    _entity("St Vincent's Hospital", "ADDRESS", 0.45),  # deliberately low, for threshold testing
    _entity("02/06/2026", "DATE", 0.96),
    _entity("0412 345 678", "PHONE_OR_FAX", 0.98),
    _entity("Sarah Chen", "NAME", 0.93),
]