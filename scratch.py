from deid.redact import redact
from tests.fixtures.mock_entities import MOCK_ENTITIES, TEXT

# Swap back once Comprehend Medical access is unblocked:
# import boto3
# from deid.detect import detect_phi
# client = boto3.client("comprehendmedical", region_name="ap-southeast-2")
# TEXT = open("tests/fixtures/sample_note.txt").read()
# MOCK_ENTITIES = detect_phi(client, TEXT)

redacted_text, audit = redact(TEXT, MOCK_ENTITIES, min_score=0.5)
print(redacted_text)
print(audit)