# Decision Log

Newest first. Each entry: decision, rationale, alternatives considered.

---

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
