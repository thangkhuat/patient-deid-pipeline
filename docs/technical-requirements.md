# Technical Requirements — Patient De-Identification Tool (v1: Redaction Module)

Scope: local, no-AWS-infra proof of concept. Terraform, CI/CD, and hardening
are deliberately deferred to later phases — see `decision-log.md`.

Status: `detect_phi()`, `redact()` and `load_note()` are implemented and
verified end-to-end against live Comprehend Medical as of 2026-09-01. The AU
mobile backstop and the combined detection entry point landed 2026-09-06.

## Stack

- Language: Python 3.x
- AWS SDK: boto3
- AWS service: Amazon Comprehend Medical, `detect_phi` operation
- Region: `ap-southeast-2` (confirmed available; matches primary infra region)
- Testing: pytest

## Module design

```
src/deid/
├── detect.py             # detect_phi(client, text) -> list[dict]
├── phone_backstop.py     # detect_au_mobile(text) -> list[dict]
│                         # resolve_overlaps(api, regex) -> list[dict]
├── resolve_entities.py   # get_all_entities(client, text) -> list[dict]
├── redact.py             # redact(text, entities, min_score) -> (str, list[dict])
└── pipeline.py           # load_note(path) -> str ; main()
```

Detection is two sources behind one entry point:

```
load_note() -> get_all_entities(client, text) -> redact(text, entities, min_score)
                    |                                      |
                    +-- detect_phi()  (Comprehend Medical) +-> (redacted_text, audit_records)
                    +-- detect_au_mobile()  (regex backstop)
                        merged by resolve_overlaps()
```

Callers use `get_all_entities()`, never `detect_phi()` directly — reaching for
the latter gets detection without the backstop, and fails silently rather than
loudly. See `decision-log.md`, "Detection goes through one entry point".

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

Real scores are now observable. As returned by `DetectPHI` on `sample_note.txt`
they are 0.383 for one mis-detected span and 0.995–0.99999 for every other
entity, with nothing in between — so any threshold in (0.383, 0.995) behaves
identically on this note.

Since 2026-09-06 that 0.383 span no longer reaches `redact()`: the backstop
replaces it with a full-span entity scoring 1.0. On the real pipeline path every
entity on this note now scores ≥0.995, which makes `min_score` inert at any value
in (0, 0.995). The parameter is therefore *less* exercised by this note than the
figures above suggest — a fact the FR-4 research pass has to design around, not
around the numbers alone.

`pipeline.py` currently passes **0.5**. This is provisional and explicitly not
the FR-4 decision: one note is too little evidence to fix a recall-critical
parameter. The full reasoning, including the argument for 0.0, is in
`decision-log.md` under "min_score stays at 0.5 provisionally". Until it is
settled, tests pass `min_score` explicitly rather than importing a shared
default, so no test becomes the thing that decides it by accident.

## Known detection gap: non-US phone formats

Comprehend Medical is an English-language service whose phone detection keys off
**US number shapes**. Australian formats that don't resemble a US number fail in
three distinct ways (measured live, same sentence frame):

| Number | Result |
|---|---|
| `415-555-0132`, `(415) 555-0132` (US) | `PHONE_OR_FAX`, full span |
| `(03) 9345 6789` (AU landline) | `PHONE_OR_FAX` 0.797 — works, it looks US |
| `0412345678` (AU, unspaced) | `ID` 0.999 — redacted, but mis-typed |
| `0412 345 678` (AU mobile) | `ID` 0.296, span truncated to `0412 345` |
| `+61 412 345 678` (AU international) | **not detected at all** |

The `+61` case is the dangerous one: no entity means no audit record either, so
FR-6's trail cannot flag it — the tool reports a clean redaction over text that
still contains a phone number.

**A confidence threshold cannot fix this.** Truncated spans and silent misses
are span and recall problems, not ranking problems; even `min_score=0` leaves
`[ID] 678`. That ruled out threshold tuning and led to the regex backstop in
`phone_backstop.py`; `decision-log.md` records the options weighed.

**Status: closed for AU mobiles, as of 2026-09-06.** `get_all_entities()` merges
the backstop's matches with the API's, so both the truncated-span and the
undetected-`+61` cases are redacted in full, with a `PHONE_OR_FAX` audit record.
`tests/test_resolve_entities.py` asserts this end to end.

Still open, and deliberately so:

- **Only AU mobiles are covered.** Landlines are out of scope (Comprehend
  Medical handles them; see `decision-log.md`), and no other locale's formats
  are covered at all. A note carrying a UK or NZ mobile has the same class of
  gap this section describes, unmeasured.
- **The backstop is a format list, not a solution to the underlying bias.** It
  closes the shapes that were measured. The US-centric behaviour above is
  unchanged upstream, so new formats fail the same way until someone measures
  them.

For a deployment in `ap-southeast-2` serving Australian notes, this remains the
category of gap to watch, and belongs in the FR-8 limitations write-up rather
than being treated as solved.

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
- Unit tests for `detect_phi()` against an injected fake client, and for
  `load_note()` against `tmp_path` files.
- Tests for `get_all_entities()` covering the composition only — that both
  detectors see the same string, that API errors propagate rather than
  degrading to regex-only detection, and that the merged list closes the phone
  gap end to end through `redact()`. Not a re-test of either half.
- Known, unfixed leaks are pinned with `xfail(strict=True)` rather than
  omitted, so they stay visible in the suite.
- An `xfail(strict=True)` may also pin *upstream API behaviour* that a higher
  layer compensates for — the two phone cases in `tests/test_redact.py` are
  this, not open defects. Such a test turning green means the upstream service
  changed and the decision resting on it needs review; the reason string must
  say which of the two kinds it is, since "expected failure" alone does not
  distinguish them.

### Fixtures

`tests/fixtures/detect_phi_response.json` is a real `DetectPHI` response for
`sample_note.txt`, recorded 2026-09-01, loaded via
`tests/fixtures/recorded_entities.py`. It replaced a hand-built mock whose
guessed scores turned out to be wrong — see `decision-log.md`.

### Running

```powershell
py -3.10 -m pytest            # offline, free, deterministic
py -3.10 -m pytest -m live    # opt-in; calls real AWS and bills the account
```

`pytest.ini` sets `addopts = -m "not live"`, so live tests never run by
accident.
