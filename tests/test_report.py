"""Tests for report.py -- the redaction report builder and writer.

See docs/decision-log.md for the design this module implements: two
genuinely independent sources (redact()'s output, and the raw entity
list for review-queue purposes), an encryption key that must never be
silently generated, and output written outside OneDrive's sync scope.
"""

import json

import pytest
from cryptography.fernet import Fernet, InvalidToken
from src.deid.report import decrypt_flagged_content

from src.deid.report import (
    get_output_directory,
    load_encryption_key,
    encrypt_flagged_content,
    identify_entities_for_review,
    build_report,
    write_report,
)


# --- get_output_directory --------------------------------------------------

def test_output_directory_resolves_under_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    output_dir = get_output_directory()
    assert output_dir == tmp_path / "patient-deid-pipeline" / "output"
    assert output_dir.exists()


def test_output_directory_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    get_output_directory()
    output_dir = get_output_directory()
    assert output_dir.exists()


# --- load_encryption_key ----------------------------------------------------

def test_load_encryption_key_reads_from_environment(monkeypatch):
    real_key = Fernet.generate_key()
    monkeypatch.setenv("PATIENT_DEID_ENCRYPTION_KEY", real_key.decode())
    assert load_encryption_key() == real_key


def test_load_encryption_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("PATIENT_DEID_ENCRYPTION_KEY", raising=False)
    with pytest.raises(EnvironmentError):
        load_encryption_key()


# --- encrypt_flagged_content -------------------------------------------

def test_encrypt_flagged_content_round_trips():
    key = Fernet.generate_key()
    ciphertext = encrypt_flagged_content("Zbigniew Wojcik", key)
    assert isinstance(ciphertext, str)
    assert Fernet(key).decrypt(ciphertext.encode()).decode() == "Zbigniew Wojcik"


def test_encrypt_flagged_content_does_not_return_plaintext():
    key = Fernet.generate_key()
    ciphertext = encrypt_flagged_content("Zbigniew Wojcik", key)
    assert "Zbigniew Wojcik" not in ciphertext


# --- decrypt_flagged_content -------------------------------------------

def test_decrypt_flagged_content_round_trips():
    key = Fernet.generate_key()
    plaintext = "Zbigniew Wojcik"
    ciphertext = encrypt_flagged_content(plaintext, key)
    assert decrypt_flagged_content(ciphertext, key) == plaintext


def test_decrypt_flagged_content_fails_loudly_on_wrong_key():
    key = Fernet.generate_key()
    wrong_key = Fernet.generate_key()
    ciphertext = encrypt_flagged_content("occupational therapy department", key)
    with pytest.raises(InvalidToken):
        decrypt_flagged_content(ciphertext, wrong_key)


# --- get_output_directory --------------------------------------------------


# --- identify_entities_for_review ---------------------------------------

def test_identifies_only_entities_below_threshold():
    entities = [
        {"Type": "NAME", "Score": 0.99, "Text": "John Smith"},
        {"Type": "ADDRESS", "Score": 0.70, "Text": "physiotherapy department"},
    ]
    flagged = identify_entities_for_review(entities, review_threshold=0.8)
    assert flagged == [entities[1]]


def test_score_exactly_at_threshold_is_not_flagged():
    entities = [{"Type": "ADDRESS", "Score": 0.8, "Text": "some place"}]
    assert identify_entities_for_review(entities, review_threshold=0.8) == []


def test_empty_entity_list_returns_empty_review_queue():
    assert identify_entities_for_review([], review_threshold=0.8) == []


# --- build_report -----------------------------------------------------

def test_build_report_passes_through_redact_output_unchanged():
    key = Fernet.generate_key()
    redacted_text = "Patient [NAME]."
    audit_records = [{"type": "NAME", "score": 0.99, "action": "redacted"}]
    report = build_report(redacted_text, audit_records, entities=[], key=key,
                          min_score=0.001)
    assert report["redacted_text"] == redacted_text
    assert report["audit_records"] == audit_records


def test_build_report_review_queue_contains_only_low_score_entities():
    key = Fernet.generate_key()
    entities = [
        {"Type": "NAME", "Score": 0.99, "Text": "John Smith"},
        {"Type": "ADDRESS", "Score": 0.70, "Text": "physiotherapy department"},
    ]
    report = build_report("...", [], entities, key, min_score=0.001,
                          review_threshold=0.8)
    assert len(report["review_queue"]) == 1
    assert report["review_queue"][0]["type"] == "ADDRESS"
    assert report["review_queue"][0]["score"] == 0.70


def test_build_report_review_queue_never_contains_plaintext():
    key = Fernet.generate_key()
    entities = [{"Type": "ADDRESS", "Score": 0.70, "Text": "physiotherapy department"}]
    report = build_report("...", [], entities, key, min_score=0.001,
                          review_threshold=0.8)
    record = report["review_queue"][0]
    assert "text" not in record
    assert "physiotherapy department" not in json.dumps(report)


def test_build_report_review_content_decrypts_to_original_text():
    key = Fernet.generate_key()
    entities = [{"Type": "ADDRESS", "Score": 0.70, "Text": "physiotherapy department"}]
    report = build_report("...", [], entities, key, min_score=0.001,
                          review_threshold=0.8)
    ciphertext = report["review_queue"][0]["content_encrypted"]
    assert Fernet(key).decrypt(ciphertext.encode()).decode() == "physiotherapy department"


def test_review_record_carries_the_action_redact_took():
    key = Fernet.generate_key()
    entities = [{"Type": "ADDRESS", "Score": 0.70, "Text": "physiotherapy department"}]
    report = build_report("...", [], entities, key, min_score=0.001,
                          review_threshold=0.8)
    assert report["review_queue"][0]["action"] == "redacted"


def test_action_splits_at_min_score_not_review_threshold():
    """Both entities are flagged for review; only one of them was redacted.

    min_score and review_threshold are deliberately set apart here rather
    than at the project's own values -- the point is to characterise where
    the split falls, which a single threshold cannot show.
    """
    key = Fernet.generate_key()
    entities = [
        {"Type": "ADDRESS", "Score": 0.70, "Text": "physiotherapy department"},
        {"Type": "ADDRESS", "Score": 0.30, "Text": "interstate"},
    ]
    report = build_report("...", [], entities, key, min_score=0.5,
                          review_threshold=0.8)
    actions = {r["score"]: r["action"] for r in report["review_queue"]}
    assert actions == {0.70: "redacted", 0.30: "flagged_low_confidence"}


def test_score_exactly_at_min_score_counts_as_redacted():
    key = Fernet.generate_key()
    entities = [{"Type": "ADDRESS", "Score": 0.5, "Text": "physiotherapy department"}]
    report = build_report("...", [], entities, key, min_score=0.5,
                          review_threshold=0.8)
    assert report["review_queue"][0]["action"] == "redacted"


# --- write_report --------------------------------------------------------

def test_write_report_produces_valid_json_matching_input(tmp_path):
    report = {"redacted_text": "...", "audit_records": [], "review_queue": []}
    path = write_report(report, tmp_path)
    assert path.exists()
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == report


def test_write_report_filename_is_timestamp_based(tmp_path):
    report = {"redacted_text": "...", "audit_records": [], "review_queue": []}
    path = write_report(report, tmp_path)
    assert path.name.startswith("report_")
    assert path.suffix == ".json"