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
        key. Each entity has Text, Category, Type, Score, BeginOffset,
        EndOffset (see AWS docs — deliberately not reshaped here yet;
        confirm the real shape first, then decide if a cleaner internal
        representation is worth introducing).

    TODO: implement. First goal is just to see this print something real
    for the sample note in tests/fixtures/ — don't build redact() until
    this is confirmed working.
    """
    raise NotImplementedError
