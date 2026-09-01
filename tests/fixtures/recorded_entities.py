"""A real DetectPHI response for sample_note.txt, recorded from live AWS.

Replaces the hand-built mock_entities.py that existed while Comprehend
Medical was blocked account-side. This is an actual response captured on
2026-09-01 (region ap-southeast-2), not an approximation — see
docs/decision-log.md, "Recorded response replaces the hand-built mock."

Recording it rather than calling AWS from the test suite keeps redact()'s
tests free, offline and deterministic, while still exercising the real
response shape (which includes `Id` and `Traits` — fields the old mock
did not have).

Re-record with:

    py -3.10 -m src.deid.pipeline

and copy the printed entity list, or see tests/test_detect.py::test_live_*
for the opt-in live check.
"""

import json
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent

TEXT = (_FIXTURE_DIR / "sample_note.txt").read_text(encoding="utf-8")

RECORDED_ENTITIES = json.loads(
    (_FIXTURE_DIR / "detect_phi_response.json").read_text(encoding="utf-8")
)


def entity(fragment: str, type_: str, score: float, text: str = TEXT) -> dict:
    """Build a single entity dict for a fragment of `text`.

    For constructing edge cases (overlaps, adjacency, boundaries) that the
    recorded response happens not to contain. Uses the first occurrence of
    `fragment`, so don't use it for fragments that appear twice.
    """
    start = text.index(fragment)
    return {
        "Id": 0,
        "BeginOffset": start,
        "EndOffset": start + len(fragment),
        "Score": score,
        "Text": fragment,
        "Category": "PROTECTED_HEALTH_INFORMATION",
        "Type": type_,
        "Traits": [],
    }
