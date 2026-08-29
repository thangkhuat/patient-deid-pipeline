# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

`python` is not on PATH on this machine — use the `py` launcher (Python 3.10.8).
Neither `boto3` nor `pytest` is installed yet, and there is no virtualenv.

```powershell
py -3.10 -m pip install -r requirements.txt

# Run the pipeline (needs AWS creds with Comprehend Medical access)
$env:PYTHONPATH = "src"; py -3.10 -m deid.pipeline

# Tests
$env:PYTHONPATH = "src"; py -3.10 -m pytest
$env:PYTHONPATH = "src"; py -3.10 -m pytest tests/test_redact.py::test_no_safe_harbor_categories_leak_in_output
```

`PYTHONPATH=src` is required: the project uses a `src/` layout with no
`pyproject.toml`/`setup.py`, so `deid` is not importable from the repo root.
(README's `python -m deid.pipeline` omits this and will fail as written.)
Adding a `pyproject.toml` + `pip install -e .` would remove the need — worth
proposing, but it's a real change to the project, not a silent fix.

## Current state

Phase 2 of 5. Every function in `src/deid/` is a deliberate stub raising
`NotImplementedError` with a filled-in docstring; the docstrings are the spec.
`tests/test_redact.py` is disabled by a module-level
`pytestmark = pytest.mark.skip(...)` — remove it when `redact()` is implemented.

The intended build order is stated in `src/deid/pipeline.py`: get `detect_phi()`
returning real entities from the sample note *first*, then write `redact()`
against the observed entity shape. Don't implement both at once.

## Architecture

Single pass, three modules, no state:

`load_note()` → `detect_phi(client, text)` → `redact(text, entities, min_score)`
→ `(redacted_text, audit_records)`

- `src/deid/detect.py` — thin wrapper over boto3 `comprehendmedical.detect_phi`,
  region `ap-southeast-2`. Returns the raw AWS `Entities` list unreshaped, on
  purpose: confirm the real response shape before introducing an internal
  representation. Input cap is 20,000 UTF-8 chars.
- `src/deid/redact.py` — `redact()` returns redacted text *and* audit records
  from one pass, because both derive from the same walk over the entities
  (FR-5 + FR-6).
- `src/deid/pipeline.py` — entry point wiring the above.

## Two constraints that are easy to get wrong

Both are documented in `docs/technical-requirements.md` and are the specific
mistakes to avoid:

1. **Offsets are into the original string.** `BeginOffset`/`EndOffset` from
   Comprehend Medical index the *original* text. Replacing spans left-to-right
   as you iterate shifts every subsequent offset. Either build the output in a
   single position-tracking pass, or process in an order that doesn't
   invalidate remaining offsets.
2. **`min_score` must be recall-biased, and must not be guessed.** A high
   threshold silently leaves low-confidence (possibly real) PHI in the text,
   which contradicts FR-4. The docs explicitly retract an earlier `0.80`
   placeholder. The real value gets chosen after observing actual scores from
   `detect_phi()` — do not hardcode one before then.

## Working with the docs

`docs/` is the source of truth, and it is unusually load-bearing here:

- `functional-requirements.md` — numbered requirements FR-1..FR-8. Behavior
  changes should map to an FR; if a change has no FR, that's a signal to ask
  rather than assume.
- `decision-log.md` — newest-first, each entry recording decision + rationale +
  alternatives considered. Non-obvious design choices belong here as a new
  entry, in that format.
- `technical-requirements.md` — module design, stack, testing requirements.

Design decisions already settled (don't relitigate without being asked):
redaction is irreversible anonymization with **no** mapping table (FR-7);
placeholders are category tags like `[NAME]`/`[DATE]`, not surrogate values;
the standard is HIPAA Safe Harbor, not Expert Determination; detection is
AWS Comprehend Medical, not a custom model — the project's point is
*operationalizing* an existing engine safely, not novel NLP.

## Data handling

`tests/fixtures/` holds synthetic clinical notes only. No real PHI enters this
repository, and no re-identification mapping is persisted anywhere (FR-7).
`.gitignore` blocks `/data/` and `*.real.txt` as a backstop.

## Testing

The core success criterion (from `functional-requirements.md`): zero literal
instances of the 18 Safe Harbor categories remain in the output text. The
sample note in `tests/fixtures/sample_note.txt` has known identifiers — patient
name, DOB, hospital, visit date, phone number, physician name — and the leakage
test asserts none of them survive redaction.

## Working with this repo

The stubs in `src/deid/` are intentional — implementing them is the point of
this project, not a bug to fix. When helping here:
- Do not implement `detect_phi()`, `redact()`, or `load_note()` unless
  explicitly asked to write the implementation.
- When something breaks, explain the error and its likely cause. The repo
  owner writes the fix.
- Diagnosing environment/tooling issues (like this file's own setup) is
  fine and welcome — that's a different thing from writing core logic.

  AWS Comprehend Medical is currently blocked account-side (SubscriptionRequiredException,
AWS Support case open). redact() is being built/tested against
tests/fixtures/mock_entities.py in the meantime — see decision-log.md. detect.py
remains a deliberate stub pending live AWS access; nothing here should be "fixed" by
implementing it.