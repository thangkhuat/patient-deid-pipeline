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
- Encryption is direct KMS Encrypt/Decrypt, not a local secret. This
  replaces Fernet entirely: access to decrypt is governed purely by the
  caller's own AWS/Cognito identity against the review-artifacts key's
  policy, closing the shared-secret distribution gap that made Fernet
  only ever an interim measure.
"""

import base64
import json
import os
from pathlib import Path
from datetime import datetime


# Entities scoring below this are flagged into the review queue. Settled
# value -- see docs/decision-log.md for the banding this comes from.
REVIEW_THRESHOLD = 0.8


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


def encrypt_flagged_content(text: str, kms_client, key_id: str) -> str:
    """Encrypt one piece of flagged text for inclusion in a report.

    Direct KMS Encrypt call -- no local key material at all.

    Args:
        text: the actual flagged entity text (real PHI -- this is the
            sensitive value this whole module exists to protect).
        kms_client: a boto3 KMS client (or test double).
        key_id: the review-artifacts key's ARN.

    Returns:
        Base64-encoded ciphertext, ready to drop directly into a JSON
        audit record's "content_encrypted" field. KMS's raw
        CiphertextBlob is binary, not directly JSON-safe the way
        Fernet's output was, hence the explicit encoding step.
    """
    response = kms_client.encrypt(KeyId=key_id, Plaintext=text.encode())
    return base64.b64encode(response["CiphertextBlob"]).decode()


def decrypt_flagged_content(ciphertext: str, kms_client, key_id: str) -> str:
    """Decrypt one review_queue entry's content back to plaintext.

    key_id is technically optional for a symmetric key -- KMS reads
    which key encrypted the blob from its own embedded metadata -- but
    specified anyway per AWS's stated best practice: makes decryption
    fail explicitly against an unexpected key, rather than silently
    trusting the blob's own claim.

    Args:
        ciphertext: a review_queue record's "content_encrypted" value.
        kms_client: a boto3 KMS client (or test double).
        key_id: the same key's ARN used to encrypt it.

    Returns:
        The original plaintext.

    Raises:
        botocore.exceptions.ClientError: wrong key, the caller lacks
        kms:Decrypt, or the ciphertext is not KMS ciphertext at all
        (e.g. a pre-migration Fernet entry).
    """
    ciphertext_blob = base64.b64decode(ciphertext)
    response = kms_client.decrypt(KeyId=key_id, CiphertextBlob=ciphertext_blob)
    return response["Plaintext"].decode()


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
            Defaults to REVIEW_THRESHOLD above -- see decision-log.md
            for where that value comes from.

    Returns:
        The subset of entities scoring below review_threshold, each
        still carrying its original Type, Score, and Text fields
        unchanged.
    """
    return [entity for entity in entities if entity["Score"] < review_threshold]


def build_report(redacted_text: str, audit_records: list[dict], entities: list[dict],
                  kms_client, key_id: str, min_score: float,
                  review_threshold: float = REVIEW_THRESHOLD) -> dict:
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

    Deliberately takes kms_client and key_id as parameters -- same
    reasoning as detect_phi() taking `client` as a parameter: testable
    against a fake, and "where the client and key come from" stays the
    caller's job.

    Args:
        redacted_text: redact()'s first return value, unmodified.
        audit_records: redact()'s second return value, unmodified.
        entities: the RAW entity list from get_all_entities() -- from
            BEFORE it was ever passed into redact(). Not audit_records.
        kms_client: a boto3 KMS client (or test double).
        key_id: the review-artifacts key's ARN.
        min_score: the same threshold redact() used, so each
            review_queue record's action can be independently verified
            rather than assumed to match.
        review_threshold: defaults to REVIEW_THRESHOLD above; see
            decision-log.md for where that value comes from.

    Returns:
        {"redacted_text": ..., "audit_records": [...], "review_queue": [...]}
    """
    review_queue = []
    for entity in identify_entities_for_review(entities, review_threshold):
        action = "redacted" if entity["Score"] >= min_score else "flagged_low_confidence"
        encrypted_content = encrypt_flagged_content(entity["Text"], kms_client, key_id)
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
