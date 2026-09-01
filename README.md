# Patient De-Identification Pipeline

Automated, auditable redaction of protected health information (PHI) from
unstructured clinical text, against HIPAA's Safe Harbor standard — built to
demonstrate secure operationalization of an existing detection engine
(AWS Comprehend Medical), not novel PHI detection. See
`docs/decision-log.md` for why.

## Why

Healthcare has been the costliest industry for data breaches for over a
decade, and most PHI exposure happens downstream of the originating
hospital — through third-party vendors, analytics platforms, and AI
pipelines that received data secondhand. This project sits at exactly that
handoff point: making clinical text safe to share before it leaves.

Full background: `docs/functional-requirements.md`.

## Status

**Phase 2 (application) — in progress.** Requirements defined, repo
scaffolded, core `detect_phi()` / `redact()` logic not yet implemented.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1. Requirements & repo | This doc set | ✅ Done |
| 2. Application | Local `detect_phi()` + `redact()` proof of concept, no AWS infra | 🔜 In progress |
| 3. Infrastructure | Terraform: S3, IAM, KMS, VPC | Not started |
| 4. CI/CD | Automated testing + deploy pipeline | Not started |
| 5. Security hardening | Least-privilege IAM, audit logging | Not started |

## Docs

- [`docs/functional-requirements.md`](docs/functional-requirements.md) — what this does and why
- [`docs/technical-requirements.md`](docs/technical-requirements.md) — how it's built
- [`docs/decision-log.md`](docs/decision-log.md) — key decisions and rationale

## Setup

```bash
pip install -r requirements.txt
aws configure  # if not already set up — needs Comprehend Medical access
python -m src.deid.pipeline
```

## Data

`tests/fixtures/` contains synthetic clinical notes only. No real PHI has
ever been or will be committed to this repository.
