"""Tests for the Pipeline Lambda handler -- the production path.

Offline: S3, Comprehend Medical and KMS are fakes injected by patching
boto3.client, the same approach as tests/test_review_backend.py. The
detection half runs against the recorded DetectPHI response, so what
reaches redact() here is what the real Lambda would see for the sample
note.

lambda_handler.py reads its bucket names and key ARN from os.environ at
import time, so the module can't be imported at the top of this file:
_import_with() sets the environment first, then imports it fresh.
"""
import base64
import importlib
import io
import json
import sys

import pytest
from botocore.exceptions import ClientError

from tests.fixtures.recorded_entities import RECORDED_ENTITIES, TEXT, entity

MODULE = "src.deid.lambda_handler"
INPUT_BUCKET = "test-input-notes"
OUTPUT_BUCKET = "test-redacted-output"
REVIEW_BUCKET = "test-review-artifacts"
TEST_KEY_ID = "arn:aws:kms:ap-southeast-2:471116065597:key/test-key-id"

# The known identifiers in sample_note.txt -- phone number included,
# since on this path it goes through get_all_entities() and the backstop.
SAMPLE_NOTE_IDENTIFIERS = [
    "John Smith", "14/03/1982", "St Vincent", "02/06/2026", "0412 345 678", "Sarah Chen",
]


class FakeS3:
    """In-memory stand-in for the two S3 calls the handler makes."""

    def __init__(self, objects: dict[tuple[str, str], bytes]):
        self.objects = dict(objects)
        self.puts = {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body):
        self.puts[(Bucket, Key)] = Body


class FakeComprehend:
    """Stands in for a boto3 comprehendmedical client. Same shape as the
    fakes in test_detect.py and test_resolve_entities.py, redefined
    rather than imported so test modules stay independently editable.
    """

    def __init__(self, entities=None, error=None):
        self._entities = RECORDED_ENTITIES if entities is None else entities
        self._error = error
        self.calls = []

    def detect_phi(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"Entities": self._entities}


class FakeKMS:
    """Same double as test_report.py's, duplicated rather than imported,
    since test files shouldn't depend on each other.
    """

    def __init__(self):
        self._store = {}
        self._counter = 0

    def encrypt(self, KeyId, Plaintext):
        self._counter += 1
        blob = f"fake-ciphertext-{self._counter}".encode()
        self._store[blob] = (KeyId, Plaintext)
        return {"CiphertextBlob": blob}

    def decrypt(self, KeyId, CiphertextBlob):
        if CiphertextBlob not in self._store:
            raise ClientError({"Error": {"Code": "InvalidCiphertextException"}}, "Decrypt")
        stored_key_id, plaintext = self._store[CiphertextBlob]
        if stored_key_id != KeyId:
            raise ClientError({"Error": {"Code": "IncorrectKeyException"}}, "Decrypt")
        return {"Plaintext": plaintext}


def s3_event(key, bucket=INPUT_BUCKET):
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


@pytest.fixture
def s3():
    return FakeS3({(INPUT_BUCKET, "note-1.txt"): TEXT.encode("utf-8")})


@pytest.fixture
def comprehend():
    return FakeComprehend()


@pytest.fixture
def kms():
    return FakeKMS()


def _import_with(monkeypatch, s3, comprehend, kms):
    """Import lambda_handler fresh against test env vars and fake clients.

    Re-imported per test (delitem first) because the env vars are read at
    import time; a module cached from an earlier test would keep that
    test's values.
    """
    monkeypatch.setenv("REDACTED_OUTPUT_BUCKET", OUTPUT_BUCKET)
    monkeypatch.setenv("REVIEW_ARTIFACTS_BUCKET", REVIEW_BUCKET)
    monkeypatch.setenv("REVIEW_ARTIFACTS_KMS_KEY_ID", TEST_KEY_ID)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    module = importlib.import_module(MODULE)

    clients = {"s3": s3, "comprehendmedical": comprehend, "kms": kms}

    def fake_boto3_client(service):
        if service in clients:
            return clients[service]
        raise ValueError(f"test never expected boto3.client({service!r})")

    monkeypatch.setattr(module.boto3, "client", fake_boto3_client)
    return module


@pytest.fixture
def lambda_handler(monkeypatch, s3, comprehend, kms):
    return _import_with(monkeypatch, s3, comprehend, kms)


def _put_json(s3, bucket, key):
    return json.loads(s3.puts[(bucket, key)])


# --- Wiring ---------------------------------------------------------------


def test_note_reaches_comprehend_exactly_as_stored(lambda_handler, comprehend):
    """The offsets Comprehend returns index the string it was sent; the
    same string must then be what redact() cuts. Any decode or strip
    between S3 and detection would shift every span."""
    lambda_handler.handler(s3_event("note-1.txt"), None)

    assert comprehend.calls == [{"Text": TEXT}]


def test_writes_redacted_output_and_review_artifacts_under_json_key(lambda_handler, s3):
    response = lambda_handler.handler(s3_event("note-1.txt"), None)

    assert response["statusCode"] == 200
    assert set(s3.puts) == {(OUTPUT_BUCKET, "note-1.json"), (REVIEW_BUCKET, "note-1.json")}


@pytest.mark.parametrize("input_key, output_key", [
    ("note.txt", "note.json"),
    ("2026.09.26-note.txt", "2026.09.26-note.json"),
    ("no-extension", "no-extension.json"),
])
def test_output_key_replaces_only_the_last_extension(lambda_handler, s3, input_key, output_key):
    s3.objects[(INPUT_BUCKET, input_key)] = TEXT.encode("utf-8")

    lambda_handler.handler(s3_event(input_key), None)

    assert (OUTPUT_BUCKET, output_key) in s3.puts


# --- What each bucket receives ---------------------------------------------


def test_redacted_output_holds_text_and_audit_records_only(lambda_handler, s3):
    lambda_handler.handler(s3_event("note-1.txt"), None)

    output = _put_json(s3, OUTPUT_BUCKET, "note-1.json")
    assert set(output) == {"redacted_text", "audit_records"}


def test_review_artifacts_hold_the_review_queue_only(lambda_handler, s3):
    """The redacted text and audit trail don't belong in review-artifacts;
    only the (encrypted) review queue does."""
    lambda_handler.handler(s3_event("note-1.txt"), None)

    artifact = _put_json(s3, REVIEW_BUCKET, "note-1.json")
    assert set(artifact) == {"review_queue"}


def test_no_sample_note_identifier_survives_in_either_bucket(lambda_handler, s3):
    """The core success criterion, asserted on the production path.

    Covers the phone number too: this would fail if the handler called
    detect_phi() directly instead of get_all_entities(), because the
    raw API span leaves "678" behind (see the xfails in test_redact.py).
    """
    lambda_handler.handler(s3_event("note-1.txt"), None)

    for body in s3.puts.values():
        written = body.decode("utf-8")
        for identifier in SAMPLE_NOTE_IDENTIFIERS:
            assert identifier not in written

    # The full-number check above can't see a partial leak: the raw API
    # span redacts to "[ID] 678", which no longer contains "0412 345 678".
    redacted_text = _put_json(s3, OUTPUT_BUCKET, "note-1.json")["redacted_text"]
    assert "678" not in redacted_text
    assert "[PHONE_OR_FAX]" in redacted_text


def test_low_confidence_entity_is_encrypted_in_review_artifacts(monkeypatch, s3, kms):
    """A below-review_threshold entity lands in the review queue as
    ciphertext only -- decryptable with the configured key, never
    present as plaintext in either bucket."""
    entities = [e for e in RECORDED_ENTITIES if e["Text"] != "Sarah Chen"]
    entities.append(entity("Sarah Chen", "NAME", 0.5))
    comprehend = FakeComprehend(entities=entities)
    module = _import_with(monkeypatch, s3, comprehend, kms)

    module.handler(s3_event("note-1.txt"), None)

    queue = _put_json(s3, REVIEW_BUCKET, "note-1.json")["review_queue"]
    assert [(r["type"], r["score"], r["action"]) for r in queue] == [("NAME", 0.5, "redacted")]
    ciphertext = base64.b64decode(queue[0]["content_encrypted"])
    assert kms.decrypt(KeyId=TEST_KEY_ID, CiphertextBlob=ciphertext)["Plaintext"] == b"Sarah Chen"
    for body in s3.puts.values():
        assert "Sarah Chen" not in body.decode("utf-8")


# --- Failure modes --------------------------------------------------------


def test_detection_failure_raises_and_writes_nothing(monkeypatch, s3, kms):
    """A swallowed Comprehend error would produce an empty entity list and
    an unredacted note written to the output bucket looking processed --
    the false all-clear. The handler must fail before writing anything."""
    comprehend = FakeComprehend(error=ClientError({"Error": {"Code": "ThrottlingException"}}, "DetectPHI"))
    module = _import_with(monkeypatch, s3, comprehend, kms)

    with pytest.raises(ClientError):
        module.handler(s3_event("note-1.txt"), None)

    assert s3.puts == {}
