"""Tests for the upload Lambda handler: POST /upload (API Gateway ->
input-notes) and GET /notes/{note_id} (presigned URL to redacted_output).

Offline: S3 is a fake injected by patching boto3.client. upload_handler.py
reads INPUT_NOTES_BUCKET from os.environ at import time, so the module is
imported fresh inside the fixture after the env var is set -- same
approach as tests/test_lambda_handler.py.
"""
import importlib
import json
import re
import sys
import uuid
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

MODULE = "src.deid.upload_handler"
INPUT_BUCKET = "test-input-notes"
OUTPUT_BUCKET = "test-redacted-output"
UUID_V4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
UUID_TXT_KEY = re.compile(rf"^{UUID_V4}\.txt$")


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
    monkeypatch.setenv("REDACTED_OUTPUT_BUCKET", OUTPUT_BUCKET)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    module = importlib.import_module(MODULE)

    def fake_boto3_client(service, **kwargs):
        if service == "s3":
            return s3
        raise ValueError(f"test never expected boto3.client({service!r})")

    monkeypatch.setattr(module.boto3, "client", fake_boto3_client)
    return module


def api_event(content):
    return upload_event({"body": json.dumps({"content": content})})


def upload_event(event):
    return {**event, "requestContext": {"routeKey": "POST /upload"}}


def get_note_event(note_id):
    return {
        "requestContext": {"routeKey": "GET /notes/{note_id}"},
        "pathParameters": {"note_id": note_id},
    }


# --- Accepted notes -------------------------------------------------------


def test_accepted_note_is_written_to_input_bucket_verbatim(upload_handler, s3):
    note = "Patient John Smith, DOB 14/03/1982.\n\nSeen 02/06/2026."

    response = upload_handler.handler(api_event(note), None)

    assert response["statusCode"] == 202
    body = json.loads(response["body"])
    assert body["status"] == "accepted"
    assert s3.puts == {(INPUT_BUCKET, f"{body['note_id']}.txt"): note.encode("utf-8")}


def test_note_id_is_a_bare_uuid_the_notes_route_accepts(upload_handler):
    """The ID handed back is what the Operator polls GET /notes/{note_id}
    with, so it must pass that route's own validation -- no ".txt"."""
    response = upload_handler.handler(api_event("Patient John Smith"), None)

    note_id = json.loads(response["body"])["note_id"]
    assert re.fullmatch(UUID_V4, note_id)
    assert upload_handler.is_valid_note_id(note_id)


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
    response = upload_handler.handler(upload_event(event), None)

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


# --- GET /notes/{note_id} -------------------------------------------------


@pytest.fixture
def real_s3(upload_handler, monkeypatch):
    """A real botocore S3 client with dummy credentials, HEAD stubbed.

    generate_presigned_url() is pure local signing, so leaving it real
    checks the URL boto3 actually produces -- SigV4, the expiry -- not a
    fake's idea of one. Stubber fails the test on any unexpected call.
    """
    # Via a Session: boto3.client itself is already patched by upload_handler.
    client = boto3.session.Session().client(
        "s3", region_name="ap-southeast-2",
        aws_access_key_id="testing", aws_secret_access_key="testing",
        config=upload_handler.Config(signature_version="s3v4"),
    )
    stubber = Stubber(client)
    monkeypatch.setattr(upload_handler.boto3, "client", lambda service, **kwargs: client)
    with stubber:
        yield stubber
        stubber.assert_no_pending_responses()


@pytest.mark.parametrize("note_id", [
    "not-a-uuid",
    "../input-notes/secret",
    "0f8fad5b-d9cb-469f-a165-70867728950e.txt",
    "0F8FAD5B-D9CB-469F-A165-70867728950E",
    "{0f8fad5b-d9cb-469f-a165-70867728950e}",
    "urn:uuid:0f8fad5b-d9cb-469f-a165-70867728950e",
    "0f8fad5bd9cb469fa16570867728950e",
    "",
    None,
], ids=["garbage", "path-traversal", "txt-suffix", "uppercase", "braces",
        "urn-prefix", "no-hyphens", "empty", "missing"])
def test_malformed_note_id_gets_400_before_touching_s3(upload_handler, s3, note_id):
    """FakeS3 has no head_object or generate_presigned_url -- reaching S3
    at all would raise AttributeError rather than return a 400."""
    response = upload_handler.handler(get_note_event(note_id), None)

    assert response["statusCode"] == 400
    assert "error" in json.loads(response["body"])


@pytest.mark.parametrize("error_code, http_status", [("404", 404), ("403", 403)],
                         ids=["not-found", "forbidden-without-listbucket"])
def test_unknown_or_unprocessed_note_gets_404(upload_handler, real_s3, error_code, http_status):
    """403 is what S3 really returns here: the role has no s3:ListBucket,
    so a HEAD on a missing key can't say 404."""
    note_id = str(uuid.uuid4())
    real_s3.add_client_error("head_object", service_error_code=error_code,
                             http_status_code=http_status,
                             expected_params={"Bucket": OUTPUT_BUCKET, "Key": f"{note_id}.json"})

    response = upload_handler.handler(get_note_event(note_id), None)

    assert response["statusCode"] == 404
    assert json.loads(response["body"])["status"] == "processing"


def test_processing_and_nonexistent_get_identical_responses(upload_handler, real_s3):
    """The same answer for both, so polling can't confirm an ID was ever valid."""
    responses = []
    for _ in range(2):
        real_s3.add_client_error("head_object", service_error_code="404", http_status_code=404)
        responses.append(upload_handler.handler(get_note_event(str(uuid.uuid4())), None))

    assert responses[0] == responses[1]


def test_other_s3_errors_are_not_masked_as_processing(upload_handler, real_s3):
    """Only "not there" maps to 404; anything else must surface, not leave
    the Operator polling forever."""
    real_s3.add_client_error("head_object", service_error_code="500", http_status_code=500)

    with pytest.raises(ClientError):
        upload_handler.handler(get_note_event(str(uuid.uuid4())), None)


def test_processed_note_gets_presigned_download_url(upload_handler, real_s3):
    note_id = str(uuid.uuid4())
    real_s3.add_response("head_object", {"ContentLength": 42},
                         expected_params={"Bucket": OUTPUT_BUCKET, "Key": f"{note_id}.json"})

    response = upload_handler.handler(get_note_event(note_id), None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert set(body) == {"download_url"}, "redacted text must never be returned inline"

    url = urlparse(body["download_url"])
    query = parse_qs(url.query)
    assert url.scheme == "https"
    assert OUTPUT_BUCKET in url.netloc + url.path
    assert url.path.endswith(f"/{note_id}.json")
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]  # SSE-KMS needs SigV4
    assert query["X-Amz-Expires"] == ["300"]
    assert query["response-content-disposition"] == [f'attachment; filename="{note_id}.json"']


def test_unknown_route_gets_404(upload_handler, s3):
    event = {"requestContext": {"routeKey": "DELETE /upload"}}

    response = upload_handler.handler(event, None)

    assert response["statusCode"] == 404
    assert s3.puts == {}
