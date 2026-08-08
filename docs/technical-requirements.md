# Technical Requirements — Patient De-Identification Tool (v1: Redaction Module)

Scope: local, no-AWS-infra proof of concept. Terraform, CI/CD, and hardening
are deliberately deferred to later phases — see `decision-log.md`.

## Stack

- Language: Python 3.x
- AWS SDK: boto3
- AWS service: Amazon Comprehend Medical, `detect_phi` operation
- Region: `ap-southeast-2` (confirmed available; matches primary infra region)
- Testing: pytest

## Module design

```
src/deid/
├── detect.py    # detect_phi(client, text) -> list[dict]
├── redact.py    # redact(text, entities, min_score) -> (str, list[dict])
└── pipeline.py  # load_note(path) -> str ; main()
```

`redact()` returns both the redacted text and the audit records (FR-5, FR-6)
in one call, since they're derived from the same pass over the entities.

## Confidence threshold

Default is **low**, biased toward recall (FR-4) — err toward flagging an
entity rather than missing it.

> Correction from the earlier sketch: the first draft of this skeleton used
> `min_score: float = 0.80` as a placeholder default. That's a
> precision-biased setting — a high bar means lower-confidence entities
> (which may still be real PHI) get filtered out and left in the text. That
> contradicts FR-4. The real default needs to be picked deliberately once
> you've seen actual confidence scores come back from `detect_phi()` on a
> few real notes — not guessed in advance.

## Redaction algorithm constraint

`BeginOffset`/`EndOffset` from Comprehend Medical are positions in the
*original* string. Replacing entities as you go (e.g. left-to-right) changes
the string length and invalidates every later offset. The implementation
must account for this — either by processing entities in an order that
doesn't invalidate remaining offsets, or by building the output in a single
pass that tracks position rather than mutating the string in place.

## Data handling

- No real PHI in this repository, ever — synthetic/test data only.
- No re-identification mapping persisted anywhere (matches FR-7).

## Explicitly out of scope for this phase

- Terraform / AWS infrastructure (Phase 2)
- CI/CD pipeline (Phase 3)
- Security hardening beyond "no real PHI, no persisted mapping" (Phase 4)

## Testing requirements

- Unit tests for `redact()` against fixtures with known entity positions.
- At least one test asserting zero Safe Harbor category leakage on a sample
  note (ties directly to the FR-level success criteria).
