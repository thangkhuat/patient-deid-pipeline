"""PHI detection via AWS Comprehend Medical.

See docs/technical-requirements.md for the module design and
docs/functional-requirements.md for FR-2 (this module's requirement).
"""


def detect_phi(client, text: str) -> list[dict]:
    """Call Comprehend Medical's detect_phi and return the raw entity list.

    Args:
        client: a boto3 comprehendmedical client.
        text: clinical text to inspect. Must be under 20,000 UTF-8 chars
            (Comprehend Medical's hard limit for DetectPHI).

    Returns:
        The raw list of entity dicts from the API response's "Entities"
        key, unreshaped on purpose. The real response (confirmed against
        live AWS, see tests/fixtures/detect_phi_response.json) carries
        Id, BeginOffset, EndOffset, Score, Text, Category, Type and
        Traits — two more fields than originally anticipated, neither
        currently used. Reshaping into an internal representation is
        deferred until a second consumer of this list exists; see
        docs/decision-log.md.

    Raises:
        Whatever botocore raises on failure — errors are deliberately not
        caught here. A swallowed error would look like an empty entity
        list, which redact() would treat as "no PHI in this note" and
        pass the text through unredacted: a false all-clear.
    """
    result = client.detect_phi(Text=text)
    return result["Entities"]
