# Decision Log

Newest first. Each entry: decision, rationale, alternatives considered.

## AWS access restored; detect.py implemented against the live API

*2026-09-01.* The account was upgraded to a paid plan and Comprehend Medical
`DetectPHI` now returns successfully in `ap-southeast-2` — the
`SubscriptionRequiredException` / `OptInRequired` block that shaped the previous
three entries is gone, and the AWS Support case is moot. `detect.py` is
implemented and verified end-to-end through `pipeline.py`.

The wrapper stays a thin pass-through returning the raw `Entities` list, as
originally planned. Now that the real shape is confirmed, the case for reshaping
into an internal representation can be judged on its merits rather than guessed:
the response carries `Id` and `Traits` in addition to the six fields anticipated,
and neither is currently used. Left unreshaped for now; revisit if a second
consumer of the entity list appears.

---
## Recorded response replaces the hand-built mock

The mock in `tests/fixtures/mock_entities.py` served its purpose and is
retired. In its place, `tests/fixtures/detect_phi_response.json` holds an actual
`DetectPHI` response for `sample_note.txt`, captured 2026-09-01, loaded by
`tests/fixtures/recorded_entities.py`.

Recording rather than calling AWS from the test suite keeps `redact()`'s tests
free, offline and deterministic, while testing against the shape and scores AWS
really produces. Considered deleting the fixture entirely and testing `redact()`
against live calls — rejected: it would put a paid, network-dependent,
non-deterministic dependency under every unit test of a pure function.

Worth recording *why* this matters, because the mock's guesses turned out to be
wrong in both directions and in the exact way its own docstring warned they
might be:

| Entity | Mock guessed | AWS actually returns |
|---|---|---|
| `St Vincent's Hospital` | `ADDRESS`, score 0.45 | `ADDRESS`, score **0.995** |
| `0412 345 678` | `PHONE_OR_FAX`, score 0.98 | `ID`, score **0.383**, span `0412 345` |

The old leakage test asserted the hospital name *survived* redaction, on the
strength of the guessed 0.45. Against real scores that assertion is simply
false. Anything else built on mock scores should be re-checked.

---
## Sample note phone number is not reliably detected (open failure)

Comprehend Medical does not recognise the Australian mobile format
`0412 345 678`. It returns the partial span `0412 345`, typed `ID` rather than
`PHONE_OR_FAX`, at score 0.383.

This produces a Safe Harbor leak against the success criterion in
`functional-requirements.md`, and it is **not fixed** — it is pinned by two
`xfail(strict=True)` tests in `tests/test_redact.py` so it stays visible and
turns green automatically when addressed:

- At the current `min_score=0.5` the entity is below threshold, so the full
  number survives untouched.
- At `min_score=0.0` it is redacted, but only over the returned span, yielding
  `[ID] 678` — the trailing digits survive. **Lowering the threshold alone does
  not fix this.**

That second point is the important one: it means the phone case needs span
handling or a format-specific backstop, not just threshold tuning. Options not
yet chosen: a regex pass for AU phone formats layered over Comprehend Medical;
widening low-confidence spans to token boundaries; or accepting it and
documenting it under FR-8. No decision made yet.

---
## Why the phone number fails: US-centric format expectations

*2026-09-01.* Root cause of the open failure recorded above. Comprehend Medical
is an English-language service trained on US clinical text, and its phone
detection keys off **US number shapes** rather than the concept of a phone
number. Australian formats that don't resemble a US number are mis-typed,
truncated, or missed entirely.

Measured directly, same sentence frame (`"Contact number X."`), live API:

| Number | Type | Score | Span returned |
|---|---|---|---|
| `415-555-0132` (US, 3-3-4) | `PHONE_OR_FAX` | 0.995 | full |
| `(415) 555-0132` (US, parens) | `PHONE_OR_FAX` | 0.737 | full |
| `(03) 9345 6789` (AU landline) | `PHONE_OR_FAX` | 0.797 | full |
| `0412345678` (AU mobile, unspaced) | `ID` | 0.999 | full |
| `0412 345 678` (AU mobile, spaced) | `ID` | 0.296 | **`0412 345` only** |
| `+61 412 345 678` (AU international) | — | — | **not detected at all** |

The nuance worth keeping: it is not "Australian numbers fail." The AU *landline*
in parenthesised form is detected correctly at 0.797 — because it looks
American. What breaks detection is the 4-3-3 spaced grouping and the leading
`0` / `+61`, neither of which occurs in US formats.

Three distinct failure modes, in increasing order of severity:

1. **Mis-typed but redacted** — `0412345678` comes back as `ID` at 0.999. The
   audit record says `ID` instead of `PHONE_OR_FAX`, which is misleading but
   not a leak; the text is still redacted.
2. **Truncated span** — `0412 345 678` returns only `0412 345`. Even with the
   threshold at 0, redaction produces `[ID] 678` and the trailing digits
   survive. Lowering `min_score` does not fix this.
3. **Silent miss** — `+61 412 345 678` produces no entity at all. This is the
   worst case, and worse than a low score: with no entity there is no audit
   record either, so FR-6's trail cannot flag it. The tool reports a clean
   redaction over text that still contains a full phone number.

Also observed: the identical fragment `0412 345 678` scored 0.383 inside
`sample_note.txt` but 0.296 in the bare test sentence. Scores are
context-dependent, which is further reason not to settle the FR-4 threshold on
a single observation.

### Implications

- A confidence threshold cannot fix any of this. Modes 2 and 3 are span and
  recall problems, not ranking problems. This reinforces keeping the `min_score`
  decision separate rather than reaching for it as the remedy.
- Comprehend Medical alone does not meet the FR success criterion for
  non-US-format contact numbers. For an Australian deployment — which is the
  stated context, region `ap-southeast-2` — this is a material gap, not an
  edge case.
- The gap is systematic rather than random, which makes a deterministic
  backstop viable: AU phone formats are a small, well-defined regex family.

Options, none chosen yet:

- **Regex backstop layered over Comprehend Medical** for AU phone/mobile
  formats, unioned with the API's entities before redaction. Deterministic,
  cheap, catches all three modes. Cost: a second detection path to maintain and
  test, and it starts down the road of hand-rolled detection that
  "Detection engine: AWS Comprehend Medical, not a custom model" deliberately
  avoided — though as a narrow backstop rather than a replacement engine.
- **Widen low-confidence spans to token boundaries** before redacting. Fixes
  mode 2 only; does nothing for the silent miss.
- **Accept and document under FR-8**, restricting v1's claims to US-format
  contact numbers. Honest, but weak for the stated deployment context.

Pinned by `xfail(strict=True)` tests in `tests/test_redact.py` so the failure
stays visible and turns green when addressed.

---
## min_score stays at 0.5 provisionally, pending a formal decision

Real confidence scores are now observable, which was the precondition the
earlier correction in `technical-requirements.md` set for choosing FR-4's
threshold. Observed on the sample note: 0.383 for the mis-detected phone span,
and 0.995–0.99999 for everything else. Nothing lands in between, so on this note
any threshold in (0.383, 0.995) behaves identically.

The value stays at **0.5** for now. It is explicitly provisional, not settled:
one note is not enough evidence to fix a recall-critical parameter, and the
decision deserves its own research pass across more notes.

Recorded so the reasoning is not lost: a strict reading of FR-4 argues for
**0.0**. `DetectPHI` only returns spans it already believes are PHI, so any
threshold above zero discards information the model chose to surface — a
precision trade FR-4 rejects outright ("a missed identifier is a failure; an
over-redacted word is not"), and the audit record already distinguishes
low-confidence entities without needing the threshold to do it. Against that:
0.0 makes `min_score` dead configuration, and would want deleting rather than
defaulting. Deferred deliberately.

Until it is settled, tests pass `min_score` explicitly rather than importing a
project default, so no test quietly becomes the thing that decides this.

---
## Detection is tested against a fake client, not live AWS

`detect_phi()` is a thin wrapper, so its tests inject a `FakeClient` that records
the kwargs it receives and returns a canned response. The suite runs offline,
costs nothing, and is deterministic.

One live test, `test_live_detect_phi_matches_the_recorded_response`, is marked
`@pytest.mark.live` and deselected by default via `pytest.ini`
(`addopts = -m "not live"`); run it with `py -3.10 -m pytest -m live`. It asserts
on spans and types rather than exact scores, since scores drift between model
versions. Its job is to tell you when AWS's behaviour has moved away from the
recorded fixture — the failure mode that mocked tests structurally cannot catch.

Considered making live tests the default — rejected: it bills the account on
every run, needs credentials present, and makes a pure-function test suite
network-flaky.

---
## Building against a mock entity list, not switching detection engines

> **Superseded 2026-09-01** — AWS access was restored and the mock has been
> retired. Kept for the record; the reasoning about not switching engines
> still stands. See "AWS access restored" and "Recorded response replaces
> the hand-built mock" above.

Comprehend Medical is blocked by an account-level AWS issue (SubscriptionRequiredException),
pending AWS Support. Considered switching to Microsoft Presidio (self-hosted, no AWS
dependency) to unblock immediately — rejected, because it changes the project's actual
point: operationalizing an existing managed engine safely, with the AWS service boundary
and IAM scoping that implies. Switching detection engines to route around a support
ticket isn't worth trading that away.

Instead, `tests/fixtures/mock_entities.py` provides a hand-built entity list shaped like
a real DetectPHI response, so redact() can be built and tested now. This unblocks the
redaction *mechanics* (offset handling, threshold filtering) but not the real FR-4
threshold decision, which still needs actual confidence scores from a live call.
`detect.py` stays a stub until live access clears — it gets implemented and reviewed
against a real response then, not against the mock.

---
## PROFESSION is redacted, despite not being one of Safe Harbor's 18 categories

Comprehend Medical's `Type` enum includes `PROFESSION`, but it isn't one of
Safe Harbor's 18 identifiers. Redacting it anyway is a deliberate extension:
profession is a recognized quasi-identifier — combined with age, location, or
a specific date, it can narrow a note to one person even with zero Safe
Harbor fields present — and the cost of redacting it is low in most clinical
notes, since profession is rarely the clinically relevant content a
downstream consumer actually needs.

This is logged explicitly rather than applied silently, because it edges
toward context-based re-identification judgment — the same category of
reasoning already scoped out of v1 as Expert Determination territory. The
distinction that keeps it bounded: this is one named extension (profession,
specifically, because it's a well-established quasi-identifier), not an
open-ended license to redact anything that might be identifying in
combination. Further quasi-identifiers, if considered later, go through this
same explicit reasoning rather than getting added by default.

Known, accepted cost: for use cases where profession is the actual variable
of interest (e.g. occupational health research), this reduces output
utility. A configurable on/off option was considered and set aside as
unneeded complexity for v1.

## v1 scope is the redaction module only, not the full pipeline

Infra (Terraform), CI/CD, and hardening are real phases of this project but
are deliberately sequenced *after* the core logic works and is tested
locally. Reasoning: proving the redaction mechanic is correct is a different
kind of problem than provisioning AWS resources, and stacking both at once
makes debugging ambiguous — a failure could be the logic or the
infrastructure. Solve one, then wrap the other around it.

## Redaction is irreversible (anonymization, not pseudonymization)

The tool's audience — third-party vendors, researchers, AI/ML training
pipelines — should never be able to re-identify a patient; that's the whole
point of de-identifying before the data reaches them. A reversible mapping
would work against that goal, not support it. Reversible pseudonymization
(e.g. for longitudinal clinical trial tracking, where the *same* org needs
to re-link later) is a real, different scenario — considered and explicitly
not the one being built here.

## Standard: HIPAA Safe Harbor, not Expert Determination

Safe Harbor is a deterministic checklist (18 identifier categories) —
testable, automatable, and defensible. Expert Determination is a statistical
risk judgment call made by a qualified expert; it's the right tool for
context-based re-identification risk, but not something a first version
should attempt to automate. Named as an explicit known limitation rather
than quietly out of scope.

## Detection bias: recall over precision

A missed identifier is a compliance failure. An over-redacted normal word is
just noise. The system should err toward flagging when uncertain — set to
a low confidence threshold rather than a high one.

## Redaction technique: category placeholder, not full deletion or surrogate

`[NAME]`, `[DATE]`, etc. are simple, auditable, and show exactly what was
removed without needing to build a synthetic-value generator. Realistic
surrogate values (fake-but-consistent names) were considered — useful if
downstream analytics need natural-reading text — but add complexity not
justified for v1.

## Detection engine: AWS Comprehend Medical, not a custom model

Mature open-source (Presidio, Philter) and managed (Comprehend Medical,
Google Cloud DLP, Azure Health Data Services) tools already solve PHI
detection well. This project isn't attempting to out-build them — it
demonstrates *operationalizing* one safely: secrets handling, IAM scoping,
CI/CD, compliance mapping, audit logging. That's the actual DevOps/cloud
engineering skill being shown, not novel NLP.
