"""The single detection entry point: Comprehend Medical plus the regex backstop.

Comprehend Medical is the detector; the regex is a narrow backstop over
one documented gap in it, not a second opinion. See
docs/decision-log.md, "Phone detection backstop scoped to mobiles only;
landlines explicitly out", for why the backstop exists and why its scope
is as small as it is.

Callers should use this rather than detect_phi() directly, so no path
through the pipeline can silently lose the backstop.
"""

from src.deid.detect import detect_phi
from src.deid.phone_backstop import detect_au_mobile, resolve_overlaps


def get_all_entities(client, text: str) -> list[dict]:
    """Detect PHI in text using both the Comprehend Medical API and regex.

    Both detectors are run over the *same* string, which is what keeps
    the two sets of offsets comparable: BeginOffset/EndOffset from either
    source index `text` itself, so the merged list is safe to hand
    straight to redact().

    Args:
        client: a boto3 comprehendmedical client.
        text: clinical text to inspect. Subject to detect_phi()'s
            20,000 UTF-8 char cap.

    Returns:
        Entity dicts in detect_phi()'s raw AWS shape, sorted by
        BeginOffset, with no two spans overlapping. Where a regex match
        overlaps an API entity, the API entity is dropped and the
        regex's exact span kept — see resolve_overlaps() and
        docs/decision-log.md, "Overlapping entities: replace with the
        regex entity's exact span, not union".

    Raises:
        Whatever detect_phi() raises. Deliberately not caught: falling
        back to regex-only entities on an API failure would return a
        near-empty list for most notes, and a note that looks cleanly
        processed while every name and date survives is a false
        all-clear.
    """
    api_entities = detect_phi(client, text)
    regex_entities = detect_au_mobile(text)
    return resolve_overlaps(api_entities, regex_entities)