"""Tests for the upload Lambda handler (API Gateway -> input-notes).

Offline: S3 is a fake injected by patching boto3.client. upload_handler.py
reads INPUT_NOTES_BUCKET from os.environ at import time, so the module is
imported fresh inside the fixture after the env var is set -- same
approach as tests/test_lambda_handler.py.
"""
import importlib
import json
import re
import sys

import pytest

MODULE = "src.deid.upload_handler"
INPUT_BUCKET = "test-input-notes"
UUID_TXT_KEY = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.txt$")


class FakeS3:
    def __init__(self):
        self.puts = {}

    def put_object(self, Bucket, Key, Body):
        self.puts[(Bucket, Key)] = Body


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def upload_handler(monkeypatch, s3):
    monkeypatch.setenv("INPUT_NOTES_BUCKET", INPUT_BUCKET)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    module = importlib.import_module(MODULE)

    def fake_boto3_client(service):
        if service == "s3":
            return s3
        raise ValueError(f"test never expected boto3.client({service!r})")

    monkeypatch.setattr(module.boto3, "client", fake_boto3_client)
    return module


def api_event(content):
    return {"body": json.dumps({"content": content})}


# --- Accepted notes -------------------------------------------------------


def test_accepted_note_is_written_to_input_bucket_verbatim(upload_handler, s3):
    note = "Patient John Smith, DOB 14/03/1982.\n\nSeen 02/06/2026."

    response = upload_handler.handler(api_event(note), None)

    assert response["statusCode"] == 202
    note_id = json.loads(response["body"])["id"]
    assert s3.puts == {(INPUT_BUCKET, note_id): note.encode("utf-8")}


def test_note_key_is_a_random_uuid_not_derived_from_content(upload_handler, s3):
    """Object keys show up in S3 listings, logs and the review UI; a key
    derived from the note could carry PHI into all of them."""
    upload_handler.handler(api_event("Patient John Smith"), None)
    upload_handler.handler(api_event("Patient John Smith"), None)

    keys = [key for _, key in s3.puts]
    assert len(set(keys)) == 2
    for key in keys:
        assert UUID_TXT_KEY.match(key)
        assert "John" not in key


def test_non_ascii_note_is_stored_as_utf8(upload_handler, s3):
    """A platform-default encoding would change the byte length and so
    every offset Comprehend Medical later returns."""
    note = "Patient Zoë Müller, seen by Dr. Ngô."

    upload_handler.handler(api_event(note), None)

    assert list(s3.puts.values()) == [note.encode("utf-8")]


# --- Rejected requests ----------------------------------------------------


@pytest.mark.parametrize("event", [
    {"body": "not json"},
    {"body": json.dumps({"text": "wrong field name"})},
    {"body": None},
    {},
], ids=["invalid-json", "missing-content-field", "null-body", "no-body-key"])
def test_malformed_requests_get_400_and_write_nothing(upload_handler, s3, event):
    response = upload_handler.handler(event, None)

    assert response["statusCode"] == 400
    assert "error" in json.loads(response["body"])
    assert s3.puts == {}


@pytest.mark.parametrize("content", [
    123, None, ["a note"], {"text": "a note"}, True,
], ids=["int", "null", "list", "object", "bool"])
def test_non_string_content_gets_400_not_500(upload_handler, s3, content):
    """Used to reach note_text.encode() and raise AttributeError."""
    response = upload_handler.handler(api_event(content), None)

    assert response["statusCode"] == 400
    assert s3.puts == {}


@pytest.mark.parametrize("content", ["", "   ", "\n\t "], ids=["empty", "spaces", "whitespace"])
def test_blank_content_gets_400(upload_handler, s3, content):
    """DetectPHI rejects empty text, so an accepted blank note would fail
    later in pipeline_lambda, after the caller had already been told 202."""
    response = upload_handler.handler(api_event(content), None)

    assert response["statusCode"] == 400
    assert s3.puts == {}


def test_note_at_the_detectphi_limit_is_accepted(upload_handler, s3):
    response = upload_handler.handler(api_event("a" * upload_handler.MAX_NOTE_LENGTH), None)

    assert response["statusCode"] == 202
    assert len(s3.puts) == 1


def test_note_over_the_detectphi_limit_gets_400(upload_handler, s3):
    response = upload_handler.handler(api_event("a" * (upload_handler.MAX_NOTE_LENGTH + 1)), None)

    assert response["statusCode"] == 400
    assert s3.puts == {}


def test_limit_matches_botocores_detectphi_model(upload_handler):
    """MAX_NOTE_LENGTH mirrors a limit owned by AWS. Checked against
    botocore's own service model, so a change on AWS's side (picked up by a
    boto3 upgrade) fails here rather than silently drifting."""
    import botocore.session

    model = botocore.session.get_session().get_service_model("comprehendmedical")
    text_shape = model.operation_model("DetectPHI").input_shape.members["Text"]

    assert text_shape.metadata["max"] == upload_handler.MAX_NOTE_LENGTH
