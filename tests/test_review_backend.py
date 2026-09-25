"""Tests for review_backend.py and the review_cli.py functions it reuses.

Offline: S3 and KMS are fake clients injected via monkeypatch, and the
events are hand-built HTTP API (payload 2.0) shapes carrying only the
fields the handler reads. The group check is the security boundary for
Reviewer-only content, so its cases are covered for every serialization
of cognito:groups the Lambda might receive.
"""
import io
import json

import pytest
from botocore.exceptions import ClientError

from src.deid import review_backend
from src.deid.report import encrypt_flagged_content
from src.deid.review_backend import handler, is_reviewer, parse_groups
from src.deid.review_cli import get_review_entries, list_pending_reviews

TEST_KEY_ID = "arn:aws:kms:ap-southeast-2:471116065597:key/test-key-id"


class FakeS3:
    """In-memory stand-in for the three S3 calls review_cli.py makes."""

    def __init__(self, objects: dict[str, dict]):
        self.objects = objects

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket):
                yield {"Contents": [{"Key": key} for key in objects]}

        return Paginator()

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode())}


class FakeKMS:
    """In-memory stand-in for the two KMS calls report.py makes -- same
    double as test_report.py's, duplicated rather than imported, since
    test files shouldn't depend on each other.
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


def make_event(route_key, groups, key=None):
    event = {
        "requestContext": {
            "routeKey": route_key,
            "authorizer": {"jwt": {"claims": {}}},
        },
    }
    if groups is not None:
        event["requestContext"]["authorizer"]["jwt"]["claims"]["cognito:groups"] = groups
    if key is not None:
        event["pathParameters"] = {"key": key}
    return event


@pytest.fixture
def fake_kms():
    return FakeKMS()


@pytest.fixture
def s3_objects(fake_kms):
    return {
        "flagged.json": {"review_queue": [{
            "type": "NAME", "score": 0.3812, "action": "flagged_low_confidence",
            "content_encrypted": encrypt_flagged_content("Zbigniew Wojcik", fake_kms, TEST_KEY_ID),
        }]},
        "clean.json": {"review_queue": []},
    }


@pytest.fixture
def fake_s3(monkeypatch, s3_objects, fake_kms):
    s3 = FakeS3(s3_objects)

    def fake_boto3_client(service):
        if service == "s3":
            return s3
        if service == "kms":
            return fake_kms
        raise ValueError(f"test never expected boto3.client({service!r})")

    monkeypatch.setattr(review_backend.boto3, "client", fake_boto3_client)
    monkeypatch.setenv("REVIEW_ARTIFACTS_KMS_KEY_ID", TEST_KEY_ID)
    return s3


# --- parse_groups / is_reviewer -----------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (["Reviewers", "Operators"], ["Reviewers", "Operators"]),
    ("[Reviewers Operators]", ["Reviewers", "Operators"]),
    ("Reviewers,Operators", ["Reviewers", "Operators"]),
    ("Reviewers", ["Reviewers"]),
    ("", []),
])
def test_parse_groups_handles_every_serialization(raw, expected):
    assert parse_groups(raw) == expected


@pytest.mark.parametrize("groups", [
    ["Reviewers"], "[Reviewers]", "[Operators Reviewers]", "Operators,Reviewers",
])
def test_is_reviewer_accepts_members(groups):
    assert is_reviewer({"cognito:groups": groups})


@pytest.mark.parametrize("groups", [
    ["ReviewersPending"], "[ReviewersPending]", "NotReviewers", "[Operators]", "",
])
def test_is_reviewer_rejects_near_miss_group_names(groups):
    assert not is_reviewer({"cognito:groups": groups})


def test_is_reviewer_rejects_missing_claim():
    assert not is_reviewer({})


# --- handler ---------------------------------------------------------------

def test_handler_returns_403_for_non_reviewer(fake_s3):
    response = handler(make_event("GET /reviews", "[Operators]"), None)
    assert response["statusCode"] == 403


def test_handler_returns_403_without_groups_claim(fake_s3):
    response = handler(make_event("GET /reviews", None), None)
    assert response["statusCode"] == 403


def test_handler_lists_only_objects_with_pending_entries(fake_s3):
    response = handler(make_event("GET /reviews", "[Reviewers]"), None)
    assert response["statusCode"] == 200
    pending = json.loads(response["body"])
    assert list(pending) == ["flagged.json"]
    assert "content_encrypted" in pending["flagged.json"][0]
    assert "Zbigniew" not in response["body"]


def test_handler_decrypts_one_review(fake_s3):
    response = handler(make_event("GET /reviews/{key}", "[Reviewers]", key="flagged.json"), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == [{
        "type": "NAME", "score": 0.3812, "action": "flagged_low_confidence",
        "content": "Zbigniew Wojcik",
    }]


def test_handler_returns_404_for_missing_key(fake_s3):
    response = handler(make_event("GET /reviews/{key}", "[Reviewers]", key="nope.json"), None)
    assert response["statusCode"] == 404


def test_handler_returns_404_for_unknown_route(fake_s3):
    response = handler(make_event("DELETE /reviews", "[Reviewers]"), None)
    assert response["statusCode"] == 404


# --- review_cli functions --------------------------------------------------

def test_list_pending_reviews_skips_empty_queues(s3_objects):
    assert list(list_pending_reviews(FakeS3(s3_objects))) == ["flagged.json"]


def test_list_pending_reviews_preserves_listing_order():
    objects = {f"{i:03}.json": {"review_queue": [{"type": "NAME"}]} for i in range(40)}
    assert list(list_pending_reviews(FakeS3(objects))) == sorted(objects)


def test_get_review_entries_decrypts_content(s3_objects, fake_kms):
    entries = get_review_entries(FakeS3(s3_objects), "flagged.json", fake_kms, TEST_KEY_ID)
    assert entries[0]["content"] == "Zbigniew Wojcik"
