# Functional Requirements — Patient De-Identification Tool

## Purpose

Prepare unstructured clinical text for one-way sharing with parties who should
never be able to identify the patient — researchers, third-party analytics
vendors, and AI/ML training pipelines. The tool exists because manual
redaction doesn't scale, and most PHI exposure happens downstream of the
originating hospital, not inside it.

## Scope (v1 — redaction module)

- Detect PHI in unstructured clinical text and redact it against HIPAA's
  Safe Harbor list of 18 identifier categories.
- Produce output that is anonymized, not pseudonymized: there is no path
  back to the original patient.
- Produce an audit record alongside the redacted text.

## Out of scope (v1)

- Re-identification of any kind. No mapping table is created or stored.
- Context-based re-identification risk (e.g. a rare diagnosis in a small
  town) — this is Expert Determination territory, not Safe Harbor, and is
  not attempted here. Documented as a known limitation, not silently ignored.
- Structured data (tables, database fields) — free text only in v1.
- Real-time/streaming processing — single document, batch-style only.
- Infrastructure, CI/CD, and hardening — covered in separate phase docs.

## Actors

- **Operator** — runs the tool against clinical text.
- **Downstream consumer** — receives de-identified output; by design, is
  never able to re-identify a patient from it.

## Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | System shall accept a plaintext clinical note as input. |
| FR-2 | System shall detect PHI entities using AWS Comprehend Medical's `DetectPHI` operation. |
| FR-3 | System shall redact every detected entity matching a Safe Harbor identifier category, replacing it with a category placeholder (e.g. `[NAME]`, `[DATE]`). |
| FR-4 | System shall bias detection toward recall over precision — a missed identifier is a failure; an over-redacted word is not. |
| FR-5 | System shall produce redacted text as its primary output. |
| FR-6 | System shall produce a per-document audit record listing each detected entity's category, confidence score, and the action taken. |
| FR-7 | System shall NOT retain any mapping capable of re-identifying a redacted entity. |
| FR-8 | System shall document known limitations (e.g. contextual re-identification risk) rather than implying full anonymity guarantees. |

## Success Criteria

- Zero literal instances of the 18 Safe Harbor categories remain in output
  text, verified against a test corpus.
- An audit record is generated for every processed document.
- No persistent re-identification capability exists anywhere in the system.
