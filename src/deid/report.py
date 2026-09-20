"""Builds and writes the redaction report: redacted text plus an audit
trail, with low-confidence flagged entries' actual text encrypted.

See docs/decision-log.md for the reasoning behind this module's shape:
- Two-tier audit records: plain metadata (type/score/action) always
  present in tier 1 (redact()'s own audit_records, unmodified). Tier 2
  (review_queue) is built independently, from the raw pre-redaction
  entity list, gated at review_threshold -- NOT tied to redact()'s
  action. Each review_queue record carries its own action field too
  (recomputed against min_score), so a reviewer can tell a genuine
  leak (flagged_low_confidence) from mere over-redaction (redacted)
  without decrypting anything first. See decision-log.md.
- Output written to %LOCALAPPDATA%, deliberately outside OneDrive's
  Known Folder Move sync scope (Desktop/Documents/Pictures).
- Encryption key is read from an environment variable, never generated
  by this module -- generating one here would silently orphan every
  previously-encrypted record.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from cryptography.fernet import Fernet


def get_output_directory() -> Path:
    """Resolve the report output directory, creating it if needed.

    Must resolve to %LOCALAPPDATA%\\patient-deid-pipeline\\output\\ (via
    the LOCALAPPDATA environment variable, not a hardcoded path -- this
    needs to work under any Windows username, on any machine).

    Returns:
        The resolved, existing directory path.

    """
    output_dir = Path(os.getenv("LOCALAPPDATA")) / "patient-deid-pipeline" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def load_encryption_key() -> bytes:
    """Read the encryption key from the environment.

    Reads PATIENT_DEID_ENCRYPTION_KEY. Must NOT generate a key if the
    variable is missing -- that would silently orphan every previously
    -encrypted record with no way to recover them. Missing key is a
    setup error and should fail loudly, not degrade quietly.

    Returns:
        The key as bytes, ready to pass to Fernet(key).

    Decide explicitly what happens when the env var is
    missing -- which exception, and what message tells the operator
    exactly what to do (run the setx command from decision-log.md).
    """
    key = os.getenv("PATIENT_DEID_ENCRYPTION_KEY")
    if key is None:
        raise EnvironmentError("PATIENT_DEID_ENCRYPTION_KEY environment variable is not set. Please set it using the command: setx PATIENT_DEID_ENCRYPTION_KEY <your_key>")
    return key.encode()


def encrypt_flagged_content(text: str, key: bytes) -> str:
    """Encrypt one piece of flagged text for inclusion in a report.

    Args:
        text: the actual flagged entity text (real PHI -- this is the
            sensitive value this whole module exists to protect).
        key: the Fernet key from load_encryption_key().

    Returns:
        Ciphertext as a string, ready to drop directly into a JSON
        audit record's "content_encrypted" field.

    Fernet's encrypt() returns bytes -- decide how
    that becomes a JSON-safe string (Fernet's own output is already
    base64, so check whether an extra encode/decode step is actually
    needed or whether it's redundant).
    """
    fernet = Fernet(key)
    encrypted_bytes = fernet.encrypt(text.encode())
    return encrypted_bytes.decode()

def decrypt_flagged_content(ciphertext: str, key: bytes) -> str:
    """Decrypt one review_queue entry's content back to plaintext.

    Mirror of encrypt_flagged_content() -- same key-as-parameter
    reasoning: callable without touching the environment, and "where
    the key comes from" stays someone else's job.

    Args:
        ciphertext: a review_queue record's "content_encrypted" value.
        key: the same Fernet key used to encrypt it.

    Returns:
        The original plaintext.

    Raises:
        cryptography.fernet.InvalidToken: wrong key, or the ciphertext
        has been tampered with or corrupted.
    """
    fernet = Fernet(key)
    decrypted_bytes = fernet.decrypt(ciphertext.encode())
    return decrypted_bytes.decode()


def identify_entities_for_review(entities: list[dict], review_threshold: float) -> list[dict]:
    """Entities scoring below review_threshold, independent of redact().

    Runs on the RAW, pre-redaction entity list -- the one get_all_entities()
    returns, before it's ever passed to redact() -- which already carries
    each entity's real Text field. This is deliberately independent of
    min_score: an entity can be confidently "redacted" by redact() and
    still land here, if its score sits below review_threshold. That's
    not a contradiction -- see decision-log.md -- it's flagging "we took
    an action on shaky grounds," not "this leaked."

    Args:
        entities: the raw entity list, exactly as get_all_entities()
            returned it -- NOT audit_records, and not anything that has
            already been through redact().
        review_threshold: entities scoring below this get flagged.
            Currently 0.8 -- see decision-log.md for why.

    Returns:
        The subset of entities scoring below review_threshold, each
        still carrying its original Type, Score, and Text fields
        unchanged.

    """
    return [entity for entity in entities if entity["Score"] < review_threshold]


def build_report(redacted_text: str, audit_records: list[dict], entities: list[dict],
                  key: bytes, min_score: float, review_threshold: float = 0.8) -> dict:
    """Assemble the final report from two genuinely independent sources.

    Source 1 -- redact()'s own output, passed through unmodified:
    redacted_text and audit_records. audit_records stay exactly as
    redact() produces them -- type/score/action only, no entity text.
    That reversal is deliberate; see decision-log.md.

    Source 2 -- the RAW entity list (pre-redaction), used only to build
    the review queue via identify_entities_for_review(). For each
    flagged entity, encrypt its real text (via encrypt_flagged_content)
    and add a record: {"type", "score", "action", "content_encrypted"}.
    The plaintext itself never appears anywhere in the returned structure.

    "action" is recomputed here against min_score rather than read off
    audit_records, because the two tiers share no join key -- see
    decision-log.md. It answers what a reviewer needs before decrypting
    anything: was this left in the text, or merely over-redacted?

    Deliberately takes `key` as a parameter rather than calling
    load_encryption_key() internally -- same reasoning as detect_phi()
    taking `client` as a parameter: testable without a real environment
    variable set, and "where the key comes from" stays someone else's
    job.

    Args:
        redacted_text: redact()'s first return value, unmodified.
        audit_records: redact()'s second return value, unmodified.
        entities: the RAW entity list from get_all_entities() -- from
            BEFORE it was ever passed into redact(). Not audit_records.
        key: from load_encryption_key().
        min_score: the same threshold redact() used, so each
            review_queue record's action can be independently verified
            rather than assumed to match.
        review_threshold: see decision-log.md -- currently 0.8.

    Returns:
        {"redacted_text": ..., "audit_records": [...], "review_queue": [...]}

    """
    review_queue = []
    for entity in identify_entities_for_review(entities, review_threshold):
        action = "redacted" if entity["Score"] >= min_score else "flagged_low_confidence"
        encrypted_content = encrypt_flagged_content(entity["Text"], key)
        review_queue.append({
            "type": entity["Type"],
            "score": entity["Score"],
            "action": action,
            "content_encrypted": encrypted_content
        })

    return {
        "redacted_text": redacted_text,
        "audit_records": audit_records,
        "review_queue": review_queue
    }


def write_report(report: dict, output_dir: Path) -> Path:
    """Serialize a report to JSON and write it to disk.

    Filename must be timestamp-based (e.g. report_20260914_153022.json)
    -- never derived from anything patient-identifying. Two runs within
    the same second colliding is a known, accepted limitation, not
    something to solve here.

    Args:
        report: the dict from build_report().
        output_dir: from get_output_directory().

    Returns:
        The full path of the file actually written.

    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{timestamp}.json"
    report_path = output_dir / filename

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)

    return report_path