# Decision Log

Newest first. Each entry: decision, rationale, alternatives considered.

## Building against a mock entity list, not switching detection engines

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
