"""Tests for the PHI detection wrapper (FR-2).

detect_phi() is a thin pass-through over boto3's comprehendmedical
client, so most of these use a fake client: the suite stays free,
offline and deterministic. Being honest about what that buys — mocking a
pass-through mostly tests the mock. The tests kept here are the ones
that catch a real regression (a swallowed error, a renamed kwarg, a
"tidied" response shape); the tautological ones were removed.

The actual risk in this module is that AWS's behaviour drifts away from
tests/fixtures/detect_phi_response.json. That is what the `live` test at
the bottom is for: it re-runs detection and diffs the whole response
against the fixture. It is deselected by default — run it with
`py -3.10 -m pytest -m live`. See docs/decision-log.md, "Detection is
tested against a fake client, not live AWS."
"""

import warnings

import pytest

from src.deid.detect import detect_phi
from tests.fixtures.recorded_entities import RECORDED_ENTITIES, TEXT

# Scores drift between Comprehend Medical model versions. Structural
# changes (spans, types) are failures; score movement beyond this is
# reported as a warning so it is visible without breaking the build.
SCORE_DRIFT_TOLERANCE = 0.05


class FakeClient:
    """Stands in for a boto3 comprehendmedical client.

    Records the kwargs it was called with so tests can assert on the
    request, and returns a canned response.
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


def test_passes_the_text_as_the_Text_parameter():
    """DetectPHI takes the note under the `Text` key and nothing else."""
    client = FakeClient()

    detect_phi(client, TEXT)

    assert client.calls == [{"Text": TEXT}]


def test_returns_entities_unreshaped():
    """The raw AWS shape is returned on purpose (see detect.py's docstring).

    Guards against someone "tidying" the response into an internal
    representation without that being a deliberate, logged decision:
    every key AWS sent must survive the call, `Id` and `Traits` included,
    and the dicts must be the same objects rather than copies.
    """
    client = FakeClient({"Entities": RECORDED_ENTITIES})

    entities = detect_phi(client, TEXT)

    assert entities == RECORDED_ENTITIES
    assert entities[0] is RECORDED_ENTITIES[0]
    assert set(entities[0]) == {
        "Id",
        "BeginOffset",
        "EndOffset",
        "Score",
        "Text",
        "Category",
        "Type",
        "Traits",
    }


def test_ignores_other_keys_in_the_response():
    """Real responses carry ResponseMetadata and ModelVersion alongside
    Entities; only Entities is of interest here."""
    client = FakeClient(
        {
            "Entities": RECORDED_ENTITIES,
            "ModelVersion": "0.0.0",
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }
    )

    assert detect_phi(client, TEXT) == RECORDED_ENTITIES


def test_api_errors_propagate():
    """detect_phi() does not swallow AWS failures.

    A silently-swallowed error would mean an empty entity list, which
    redact() would happily treat as "this note contains no PHI" and pass
    the note through unredacted. Failing loudly is the recall-biased
    behaviour FR-4 asks for. This cannot be tested against live AWS —
    you cannot make the service fail on demand — which is precisely why
    the fake client earns its place.
    """
    client = FakeClient(error=RuntimeError("SubscriptionRequiredException"))

    with pytest.raises(RuntimeError, match="SubscriptionRequiredException"):
        detect_phi(client, TEXT)


def test_empty_text_is_rejected_by_the_client():
    """DetectPHI requires Text of length >= 1.

    Uses a real botocore client rather than the fake, because this is a
    real constraint the fake does not model — an earlier version of this
    test asserted that empty text returned `[]`, which no real client
    ever does. Makes no network call and needs no credentials: botocore
    validates parameters before signing or sending anything.
    """
    boto3 = pytest.importorskip("boto3")
    from botocore.exceptions import ParamValidationError

    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")

    with pytest.raises(ParamValidationError, match="min length: 1"):
        detect_phi(client, "")


# --- Live contract check --------------------------------------------------


def _signature(entities):
    """The structural part of a response — what must not drift silently."""
    return [(e["BeginOffset"], e["EndOffset"], e["Text"], e["Type"]) for e in entities]


def _describe(diffs):
    return "\n".join(f"  - {d}" for d in diffs)


@pytest.mark.live
def test_live_response_still_matches_the_recorded_fixture():
    """Opt-in: calls real Comprehend Medical and bills the account.

    Run with `py -3.10 -m pytest -m live`. This is the only test that can
    catch AWS's behaviour moving away from
    tests/fixtures/detect_phi_response.json — the failure mode mocked
    tests structurally cannot see.

    On failure it reports exactly which spans, texts or types moved, so
    the fix is either "re-record the fixture" or "a real regression",
    and you can tell which from the message. Score drift is reported as a
    warning rather than a failure, since scores move between model
    versions without the contract changing.
    """
    boto3 = pytest.importorskip("boto3")
    client = boto3.client("comprehendmedical", region_name="ap-southeast-2")

    live = detect_phi(client, TEXT)

    live_sig = _signature(live)
    recorded_sig = _signature(RECORDED_ENTITIES)

    diffs = []
    if len(live) != len(RECORDED_ENTITIES):
        diffs.append(
            f"entity count changed: recorded {len(RECORDED_ENTITIES)}, live {len(live)}"
        )
    for recorded, actual in zip(recorded_sig, live_sig):
        if recorded != actual:
            diffs.append(f"recorded {recorded} -> live {actual}")
    for extra in live_sig[len(recorded_sig):]:
        diffs.append(f"new entity not in fixture: {extra}")
    for missing in recorded_sig[len(live_sig):]:
        diffs.append(f"entity no longer detected: {missing}")

    assert not diffs, (
        "Live DetectPHI no longer matches the recorded fixture.\n"
        + _describe(diffs)
        + "\n\nIf this is an intentional AWS change, re-record "
        "tests/fixtures/detect_phi_response.json and re-check the "
        "known-limitation xfails in tests/test_redact.py."
    )

    drifted = [
        f"{r['Text']!r} ({r['Type']}): recorded {r['Score']:.3f} -> live {a['Score']:.3f}"
        for r, a in zip(RECORDED_ENTITIES, live)
        if abs(r["Score"] - a["Score"]) > SCORE_DRIFT_TOLERANCE
    ]
    if drifted:
        warnings.warn(
            "Confidence scores have drifted beyond "
            f"{SCORE_DRIFT_TOLERANCE} since the fixture was recorded:\n"
            + _describe(drifted)
            + "\nThis does not change the contract, but it does bear on the "
            "open FR-4 threshold decision — see docs/decision-log.md.",
            stacklevel=2,
        )
