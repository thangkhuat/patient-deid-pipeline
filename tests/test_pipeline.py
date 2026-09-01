"""Tests for the pipeline entry point.

Covers load_note() (FR-1: accept a plaintext clinical note as input).
main() is not tested here — it builds a real boto3 client and calls live
AWS, which is what tests/test_detect.py::test_live_* covers on purpose
and by opt-in.
"""

import pytest

from src.deid.pipeline import load_note
from tests.fixtures.recorded_entities import TEXT


def test_reads_the_sample_note(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("Patient John Smith presented.", encoding="utf-8")

    assert load_note(note) == "Patient John Smith presented."


def test_accepts_a_path_object_and_a_string(tmp_path):
    """main() passes a Path; the signature is annotated str. Both work,
    and this pins that so the annotation can be corrected without anyone
    wondering which one was intended."""
    note = tmp_path / "note.txt"
    note.write_text("content", encoding="utf-8")

    assert load_note(note) == load_note(str(note))


def test_content_is_returned_verbatim(tmp_path):
    """No stripping, no normalising.

    Whitespace matters here beyond tidiness: BeginOffset/EndOffset from
    Comprehend Medical index the exact string that was sent to it. If
    load_note() trimmed anything, every offset would be shifted and
    redact() would cut the wrong spans.
    """
    raw = "  Patient John Smith.\n\nSeen 02/06/2026.\n"
    note = tmp_path / "note.txt"
    note.write_text(raw, encoding="utf-8")

    assert load_note(note) == raw


def test_reads_the_real_fixture_note_unchanged(tmp_path):
    """The fixture the recorded entity offsets were captured against."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "sample_note.txt"

    assert load_note(fixture) == TEXT


def test_reads_utf8_not_the_platform_default(tmp_path):
    """Windows defaults to cp1252, which mangles non-ASCII names.

    A mangled name changes the string length, which shifts every
    subsequent offset — so an encoding slip here shows up as corrupted
    redaction much later. Commit e9abe85 fixed exactly this class of bug
    in the fixture loader.
    """
    note = tmp_path / "note.txt"
    note.write_text("Patient Zoë Müller, seen by Dr. Ngô.", encoding="utf-8")

    assert load_note(note) == "Patient Zoë Müller, seen by Dr. Ngô."


def test_empty_note_is_read_as_empty_string(tmp_path):
    note = tmp_path / "empty.txt"
    note.write_text("", encoding="utf-8")

    assert load_note(note) == ""


def test_missing_file_raises(tmp_path):
    """Fails loudly rather than returning empty text.

    Silently returning "" would flow through detect_phi() as a note with
    no PHI and produce a clean-looking empty audit record — a false
    all-clear, which is the worst failure mode this tool has.
    """
    with pytest.raises(FileNotFoundError):
        load_note(tmp_path / "does_not_exist.txt")
