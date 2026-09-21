# Decision Log

Newest first. Each entry: decision, rationale, alternatives considered.

## Phase 3.5 added — frontend was never part of the original scope

*2026-09-20.* The original five-phase roadmap never included a user-facing
interface. Surfaced when reviewing what "the Operator has a working
interface" actually meant in practice — pipeline.py hardcodes its input
path, so processing a new note required editing source code, not just
running a command. Static frontend (S3 + CloudFront) plus a separate
Upload API (API Gateway + Lambda), kept deliberately split per the
same one-identity-one-purpose principle used throughout Phase 3.

## ADDRESS false positives on "[specialty] + [place noun]" phrases — accepted, not fixed

*2026-09-07, expanded 2026-09-17.* Round 2 of FR-4's threshold corpus (60 no-PHI sentences) surfaced one false
positive: "physiotherapy department" tagged ADDRESS at 0.7026. Round 3
isolated the exact mechanism with a 25-sentence targeted probe rather than
treating it as a one-off, and recorded here in full -- the earlier
compressed summary ("0.37-0.998") lost the individual values and produced
an incorrect downstream claim about gaps in the data; see the correction
in the review_threshold entry below.

Specialty + "department" (6/6 flagged):

| Phrase | Score |
|---|---|
| occupational therapy department | 0.3743 |
| radiology department | 0.6736 |
| physiotherapy department | 0.7026 |
| oncology department | 0.8453 |
| cardiology department | 0.9316 |
| emergency department | 0.9979 |

Specialty + other physical-space nouns (5/6 flagged -- "team" is the
control):

| Phrase | Score |
|---|---|
| physiotherapy unit | 0.4174 |
| cardiology ward | 0.7281 |
| physiotherapy clinic | 0.9520 |
| outpatient clinic | 0.9685 |
| intensive care unit | 0.9902 |
| palliative care team | not flagged (control -- "team" denotes people, not place) |

- Specialty name alone ("Cardiology reviewed the case") — never flags.
- "department" attached to a non-medical qualifier (finance, records, HR)
  — never flags.
- Bare generic facility terms with no specialty attached (reception, front
  desk, nurses' station) — never flag. Confirms the pattern is specifically
  the specialty+place combination, not generic institutional language.

Conclusion: the model appears to key on "clinical specialty term adjacent to
a place-shaped noun" and infer a location entity, even though department and
ward names identify a hospital function, not a person or an address.

Decision: documented as a known, characterized limitation. No targeted
suppression fix built, unlike the AU mobile phone backstop. The two cases
differ in kind, not just severity: the phone gap was a genuine leak of real
PHI that a threshold couldn't fix. This is over-redaction of content that
was never identifying in the first place -- squarely the "noise" category
already on record. Building a suppression mechanism here would add real
complexity to reduce a cost the project has already decided is acceptable.

Related, separate finding, not folded into this decision: "interstate" alone
flagged ADDRESS at 0.2791 in the same round. Different mechanism -- genuine
coarse geography, not a fabricated non-address -- and not investigated
further here.

Accepted cost: department, unit, ward, and clinic names will sometimes be
redacted unnecessarily in output. Does not affect detection or redaction of
genuine PHI.

## FR-7 narrowed to the trust boundary; FR-10 added for internal review

*2026-09-17.* Narrows FR-7, which until now read "System shall NOT retain any
mapping capable of re-identifying a redacted entity," and the success criterion
"No persistent re-identification capability exists anywhere in the system."

Forced by the review_queue (see the entry below): it retains the encrypted text
of flagged entities in a file that also carries the redacted output. That is
re-identification capability held inside the system, and under FR-7 as written
there was no reading where it passed. The requirement was not wrong — it was
written for a system that produced one artifact for one audience, and a second
artifact with a different audience now exists.

Why narrow rather than drop the review queue:
- FR-7's founding entry ("Redaction is irreversible", below) scopes its own
  concern to the audience: third-party vendors, researchers and ML pipelines
  "should never be able to re-identify a patient." It names the
  same-organization re-link case explicitly and sets it aside as "a real,
  different scenario" — declining to build it, not forbidding it.
- functional-requirements.md's Purpose already states the threat model in
  boundary terms: "most PHI exposure happens downstream of the originating
  hospital, not inside it." The narrowed FR-7 makes explicit what Purpose
  already assumed.
- The Reviewer holds source-note access by definition, so the review artifact
  exposes no content they cannot already read. Hence the new Reviewer actor,
  alongside Operator and Downstream consumer.

What this costs, stated plainly rather than glossed: FR-7 used to be absolute
and checkable by inspection — no mapping, anywhere, full stop. It is now
conditional on where an artifact goes. That property depends on operational
discipline (not releasing the review file) rather than on the tool's structure,
and it is a weaker guarantee than the one it replaces. Known limitation,
accepted knowingly: FR-7 can no longer be verified by inspecting the codebase
alone, and belongs in the FR-8 limitations write-up when that is written.

Alternatives considered:
- **Offsets instead of ciphertext.** review_queue carries {type, score,
  BeginOffset, EndOffset} and no content; the Reviewer opens the source note
  at that span. FR-7 and both success criteria survive verbatim, and Fernet,
  the key environment variable and the entire KMS migration disappear with
  it. This is the option that fits the original FR-7 best, and it was turned
  down on its merits rather than because it fails: an offset is only useful
  while the source note is still available and unedited, so review becomes
  dependent on a document this tool does not control and cannot verify. A
  stored offset into a note that has since been revised points confidently at
  the wrong span, which is worse than not being able to review at all.

  Noted at documentation time rather than part of the original decision: the
  ciphertext route also happens to keep the encryption and key-handling design
  that the Phase 3 KMS work builds on. A secondary observation, not the reason
  — the decision would have gone the same way without it.
- **Split the artifacts.** Emit the redacted output and the review queue as two
  files so ciphertext and redacted text are never colocated, leaving neither
  file a mapping on its own. Not adopted now, but it remains available and
  would strengthen the narrowed FR-7 structurally rather than procedurally —
  the natural thing to revisit when write_report() meets real infrastructure.

## Audit records split into two independent tiers, not one

*2026-09-17.*

Prompted by asking a question the format decision was quietly skipping over:
who actually reviews this file — the tool operator, or someone on the
originating side (a treating clinician, an internal compliance reviewer)
who already has legitimate access to the source note? Those two reviewers
need genuinely different things, which meant "what should the audit log
contain" was never answerable as a single question.

**Tier 1 — audit_records, from redact() directly, unmodified.** type/score/
action only, exactly as redact() has always produced it. Zero PHI, safe for
anyone, including the tool operator, to see.

**Tier 2 — review_queue, built independently from the raw, pre-redaction
entity list, gated at review_threshold = 0.8.** For a reviewer who already
has legitimate access to the source document, seeing the actual flagged
text exposes nothing new — "minimum necessary," applied here to the audit
trail rather than the redacted output itself. Content is Fernet-encrypted
before being written — see the report encryption/storage entry for that
design.

0.8 is taken from Liu Chen Kiow J, Massaro C, Jimenez EC, et al. (2026), "A
novel inflammatory bowel disease registry powered by artificial intelligence
and natural language processing," PLOS Digital Health 5(8): e0001603.
https://doi.org/10.1371/journal.pdig.0001603 — their confidence banding for
Comprehend Medical, arrived at following consultation with AWS, uses 0.8 as
its "high confidence" boundary. The division of labour, stated precisely
rather than as "borrowed from a paper": local evidence establishes the
*range*, and the paper fixes the *point* within it.

Citation checked against the primary source rather than taken on trust: the
DOI matches the article's own metadata, and both the banding and the
"following consultation with AWS" wording are from the paper's own
"Validation process" section, not paraphrase strengthened in the retelling.
Worth recording because this citation is load-bearing in a way FR-4's are
not — Health Canada informs min_score's reasoning but does not supply its
value, whereas 0.8 is the paper's number used directly.

**Only half the banding was adopted.** The paper bands at two thresholds,
0.8 and 0.6; this project takes the 0.8 boundary and stops there, collapsing
everything below it into one undifferentiated review queue. So an entity at
0.75 and an entity at 0.20 are treated identically here, where the source
distinguishes them. That narrowing is deliberate for now and rests on there
being no reviewer workload to triage — empty on the sample note, and at most
six entities across the entire corpus (see below) — not on a judgement that
the lower boundary is wrong.
The moment the queue holds enough to need prioritising, 0.6 is the first
thing to reach for, and it arrives with the same provenance as 0.8 rather
than needing a fresh argument.

**What the corpus does establish — the range.** The lowest-scoring real PHI
observed across all rounds is 0.9032 — the ADDRESS span "45 Collins Street,
Melbourne", from round 1's clean-baseline category
(`scripts/threshold_corpus.py`, CLEAN_BASELINE). Cited directly, the same
treatment the false positives above now get, because the whole "range is
locally derived" claim rests on it. Any threshold below that flags no
genuine detection unnecessarily, so the safe range's upper bound is locally
measured rather than borrowed, and 0.8 sits comfortably inside it rather than
near its edge.

**What the corpus cannot fully establish — the point.** False positives and
real PHI overlap in score, and not marginally: five measured false
positives score between 0.9316 and 0.9979, every one of them above the
0.9032 floor for real PHI. No threshold can therefore catch all known
false positives without also flagging real PHI -- a property of the data,
not a gap in measurement. Below that overlap zone, the picture is more
resolved than first written here: the full round-3 data (see the ADDRESS
entry above) shows measured false positives at 0.3743, 0.4174 and 0.6736
between 0.2791 and 0.7026, and at 0.7281 and 0.8453 between 0.7026 and
0.9032 -- so 0.75 and 0.80 are equivalent on local evidence (both catch
the same six known false positives), but 0.85 is measurably different,
catching a seventh (oncology department, 0.8453) that the lower two miss.
0.8 is not, therefore, an arbitrary point inside an undifferentiated
range -- it sits at the upper edge of where local evidence still agrees
with 0.75, one measured step before the data would start pulling toward
a higher value.

0.383, the truncated phone span, is excluded from that list deliberately: it
is real PHI mis-detected, not a false positive, and resolve_overlaps() drops
it before it ever reaches review_threshold on the real pipeline path. Mixing
it in would blur the two populations this paragraph exists to separate.

That overlap is the real reason a clean local derivation was never available,
and it is worth stating outright rather than leaving as an absence. The paper
is not supplying a number the project had no way to narrow toward -- local
evidence does distinguish 0.85 from the {0.75, 0.80} pair. It does not,
however, distinguish 0.75 from 0.80 from each other: both catch an identical
set of six known false positives, so the paper is choosing between two values
the local data treats as equivalent, not picking a point inside an entirely
unconstrained range.

Still weaker footing than FR-4's threshold, though less so than "borrowed
from one paper" implies, and worth keeping the difference visible: min_score
is a value computed from a stated cost ratio, whereas review_threshold is a
locally bounded range with an externally chosen point inside it. The paper's
banding was built for a different corpus and a different purpose (registry
extraction, not de-identification), which is a real caveat on the point even
though it does not touch the range. The 0.28-0.90 band already holds six measured
entities, which is enough to distinguish 0.85 from the {0.75, 0.80} pair (see
above) but not enough to separate 0.75 from 0.80 specifically -- both catch an
identical set. Further volume in this band, particularly between 0.7281 and
0.8453 where nothing is currently measured, is what would let local evidence
narrow the point itself rather than just the range. The same evidence would
either justify the paper's second band at 0.6 or show that a borrowed banding
does not transfer to this corpus at all.

Tier 2 records carry the action redact() took, alongside type and score.
Without it the queue conflates two materially different situations: an entity
scoring below min_score is left in the output text, while one between
min_score and review_threshold was redacted. The first is a possible leak,
the second at worst over-redaction, and a reviewer triaging the queue needs
to tell them apart before decrypting anything. build_report() therefore takes
min_score as well as review_threshold and records the same verdict redact()
reached for each entity.

Recorded rather than joining the two tiers after the fact, because there is
no join key to join on: audit_records carry no entity id, and phone_backstop
entities are emitted with Id: None, so ids are not unique across the two
detectors — a note containing two AU mobiles would produce two entities
sharing an id of None. Giving the tiers a real shared key means assigning ids
in the backstop and adding one to FR-6's record shape, which is a larger
change than the question warrants and would reopen redact() immediately after
it was deliberately reverted. Available later if the tiers ever need more
than this one field in common.

**First design, tried and abandoned:** tier 2 content attached directly to
redact()'s flagged_low_confidence records, requiring a change to redact()
to carry each entity's Text field through. Reverted, on separation of
concerns rather than on frequency: the actual need — "should a human look
at this" — is a different question from redact()'s "should this be
redacted," and hanging the first off the second's records couples them for
no reason. Since review_threshold (0.8) sits above min_score (0.001),
everything the redact() change could have caught is already a strict
subset of what review_threshold catches independently, so the coupling
bought nothing either. redact() was reverted to its original, untouched
three-field record.

Not offered as a reason, though it was the first one reached for: that
flagged_low_confidence "almost never fires" at min_score = 0.001. True,
but it does not separate the two designs — review_threshold at 0.8 fires
just as rarely on the real pipeline path. On the sample note, post-backstop
scores are 0.9955-1.0 across all six entities and the review queue comes
back empty; the 0.383 phone span that would have been caught is dropped by
resolve_overlaps() in favour of the backstop's 1.0 entity. Across every
round of corpus testing, the only entities 0.8 would ever have flagged are
the six ADDRESS/interstate false positives documented above (0.2791 to
0.7281) -- all false positives, none a missed identifier. Both designs are near-inert on today's evidence; the argument for
this one is that it is the right shape, not that it does more work.

## Report encryption and storage location — interim design, KMS is the real target

*2026-09-17.*

Fernet (symmetric encryption) chosen for review_queue content, explicitly
as an interim measure. The real target is AWS KMS envelope encryption once
Phase 3 infrastructure exists — a master key that never leaves KMS, a
single-use data key generated per encryption operation, and IAM-enforced,
CloudTrail-logged access control between reviewer roles. Fernet cannot
replicate the two things that actually matter for this use case: granting
decrypt access to one identity but not another without handing over the
same raw key to both, and an automatic, queryable record of who decrypted
what. Built with the same key-separation shape as KMS — ciphertext and key never
colocated — so the call sites and the trust model carry over.

What does not carry over, recorded now rather than discovered later: under
envelope encryption each record must store its own wrapped data key
alongside its ciphertext, and a review_queue record is currently {type,
score, content_encrypted} with nowhere to put one. Migrating therefore
changes the record schema, not just where the key comes from. The narrower
alternative — calling KMS Encrypt directly on each value, which stays under
the 4KB limit for entity text and needs no schema change — trades that
schema churn for a network call per entity and a hard runtime dependency on
KMS availability. Decide between them when Phase 3 lands; both are reachable
from here, which is the property this design was actually buying.

Key handling: generated once and stored as a persistent environment
variable, PATIENT_DEID_ENCRYPTION_KEY. There is deliberately no key-
generation code in the package — generating a key is a one-time setup act,
not something the pipeline should be able to do at runtime:

    py -3.10 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    setx PATIENT_DEID_ENCRYPTION_KEY <the printed key>

`setx` writes to the user environment and takes effect in new shells only;
the current shell keeps the old value.
load_encryption_key() must never generate a key itself if the variable is
missing — doing so would silently orphan every previously-encrypted record
with no way to recover them. Fails loudly instead.

Output location: %LOCALAPPDATA%\patient-deid-pipeline\output\, resolved via
the LOCALAPPDATA environment variable rather than a hardcoded path.
Deliberately outside OneDrive's Known Folder Move sync scope, confirmed to
cover only Desktop, Documents, and Pictures on this machine. Known,
accepted gap: the repository itself still sits inside OneDrive-synced
Desktop — acceptable for source code and synthetic test data, but not
something to replicate for anything carrying real content.

Note on what encryption at rest does and doesn't guarantee, kept honest
rather than overclaimed: the plaintext key necessarily exists briefly in
process memory at the moment of use, whether Fernet or KMS. Encryption
reduces blast radius (one key, one record, vs. a lifetime of encrypted
content sharing one exposure) and — once on real infrastructure — narrows
where that exposure can occur (a single-purpose Lambda execution
environment vs. a general-purpose laptop), rather than eliminating the
exposure window entirely.

## FR-4 resolved: min_score = 0.001, derived from a stated cost ratio

*2026-09-07.* Supersedes "min_score stays at 0.5 provisionally, pending a
formal decision" below, which deferred this pending real evidence.
Resolved via cost-sensitive threshold selection: t* = C_FP / (C_FP + C_FN).

Cost ratio chosen: missed PHI treated as 1000x worse than an unnecessary
redaction. Rationale, not a guess:
- FR-4's own standing principle already implied a large ratio ("a missed
  identifier is a compliance failure; an over-redacted normal word is just
  noise"), never previously quantified.
- Health Canada's clinical-information anonymization guidance (Draft
  Guidance, 5.2.3) treats this exact identifier category -- names,
  addresses, phone numbers -- as directly-identifying variables carrying
  "100% risk of re-identification (risk=1.0)," with no probabilistic
  threshold applied at all. A 1000x ratio is a bounded, usable
  approximation of that same stance, not a literal import of any number
  from that document -- their risk metric and this project's confidence
  score measure different things (population re-identification risk vs.
  per-entity detection confidence).
- Three rounds of corpus testing against live Comprehend Medical output
  support a low threshold without exposing a case where one was needed:
  round 1 (11 sentences) found 0 false positives; round 2 (60 sentences)
  found exactly 1 (an ADDRESS false positive on specialty+place-noun
  phrases, see the dedicated decision-log entry); round 3 isolated that
  pattern's mechanism precisely. No case across any round has ever scored
  between 0.0001 and 0.28 -- the practical range separating candidate
  ratios from 100x to 10000x is entirely untested territory, not a
  meaningfully different real-world outcome today.

Known limitation, stated plainly rather than glossed over: Comprehend
Medical's confidence scores are not documented by AWS as calibrated
probabilities. The cost-ratio formula assumes they are. The resulting
threshold is a principled, defensible approximation under that assumption,
not a mathematically guaranteed optimum.

Practical value used in code: 0.001 (rounded from the exact 1/1001,
consistent with the calibration caveat above -- more decimal precision
would be false precision, not more accuracy).

Reference:
Health Canada, "Public Release of Clinical Information - Draft Guidance
Document," Section 5.2.3 ("Measurement of data risk for directly-identifying
variables"). https://www.canada.ca/en/health-canada/programs/consultation-public-release-clinical-information-drug-submissions-medical-device-applications/draft-guidance.html#a5-2-3
Published 2018-04-10; explicitly a draft/consultation document, not binding
regulation -- cited here for its reasoning on identifier categories, not as
regulatory authority this project is required to follow.

## Detection goes through one entry point, `get_all_entities()`

*2026-09-06.* `src/deid/resolve_entities.py` now owns the composition of
Comprehend Medical and the regex backstop, and `pipeline.py` calls it instead of
`detect_phi()`. This is what closes the AU mobile gap in practice: the two
earlier entries below decided the backstop's *scope* and its *overlap rule*, but
neither put it on the pipeline's path.

The alternative was calling `detect_au_mobile()` and `resolve_overlaps()` inline
in `pipeline.py`. Rejected because it makes the backstop opt-in per caller:
anything that reaches for `detect_phi()` directly — a second entry point, a batch
script, a future API handler — gets unbacked detection and no error to say so.
The failure mode is a note that looks cleanly processed with a phone number still
in it, which is the worst thing this tool can do quietly. One entry point makes
using detection correctly the path of least resistance.

`detect_phi()` stays public and thinly wrapped rather than being made private:
its own tests inject a fake client at that seam, and the live fixture-drift test
in `tests/test_detect.py` needs to call the API half alone.

**Consequence for FR-4, worth noticing before the threshold research pass:** on
`sample_note.txt` the backstop replaces the 0.383 phone entity with one scoring
1.0, and every remaining entity scores 0.995 or above. That 0.383 span was the
*only* sub-threshold data point on this note — so `min_score` is now inert at any
value in (0, 0.995) on the real pipeline path. The threshold is not better
evidenced than it was before this change; it is less exercised. Whatever corpus
settles FR-4 needs notes whose low-confidence entities are something other than
the AU mobile, since that one no longer reaches the threshold at all.

*Followed up 2026-09-07:* that corpus was built (`scripts/threshold_corpus.py`,
`scripts/threshold_corpus_expanded.py`, `scripts/address_false_positive_probe.py`)
and FR-4 is now settled — see the entry at the top of this log. The observation
above still holds: `min_score = 0.001` remains inert on `sample_note.txt`, and
the decision rests on the corpus rather than on this note.

## Overlapping entities: replace with the regex entity's exact span, not union

Tested empirically via scripts/check_phone_boundaries.py against six real
Comprehend Medical calls. One case showed genuine boundary over-extension:
parentheses directly against a phone number caused the API to include the
opening bracket in its entity span -- "(0412 345 678" instead of the true
"0412 345 678".

Two options were weighed: taking the union of overlapping spans (safer
against ever losing real content, at the cost of possibly over-redacting
adjacent characters) versus pure replacement using only the regex's exact
span. The one real example available showed the API's over-extension was
harmless punctuation, not missed identifying content -- meaning pure
replacement already produces the cleaner, correct output with no added
complexity, since the discarded API entity's extra character was never
going to matter for redaction correctness.

Known limitation, explicitly not closed by this decision: this is one
example. It confirms the *mechanism* of over-extension is real, but not
that it's always limited to harmless punctuation. If a future case shows
the API's extra reach capturing real content the regex doesn't independently
cover, this decision needs revisiting with that evidence.

## Phone detection backstop scoped to mobiles only; landlines explicitly out

Comprehend Medical already detects Australian landlines correctly — confirmed
against one example, (03) 9345 6789, full span, score 0.797. Building regex
coverage for landlines anyway would create a new overlap between the regex
entity and Comprehend Medical's own correct entity, on notes that currently
redact fine — solving a problem with no demonstrated evidence behind it, at
a real cost. Landline coverage stays out of scope until a real gap is shown.

Tracked via test coverage instead of left as an assumption: landline
detection is regression-tested across multiple area codes, so a future
break in Comprehend Medical's landline handling surfaces as a failing test,
not a silent assumption going stale.

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
## Sample note phone number is not reliably detected (closed 2026-09-06)

*Superseded by the three backstop entries above; kept because it is the
measurement they rest on.*

Comprehend Medical does not recognise the Australian mobile format
`0412 345 678`. It returns the partial span `0412 345`, typed `ID` rather than
`PHONE_OR_FAX`, at score 0.383.

Against `detect_phi()` alone this produces a Safe Harbor leak, in two ways:

- At `min_score=0.5` the entity is below threshold, so the full number survives
  untouched.
- At `min_score=0.0` it is redacted, but only over the returned span, yielding
  `[ID] 678` — the trailing digits survive. **Lowering the threshold alone does
  not fix this.**

That second point is what settled the fix: the phone case needed span handling
or a format-specific backstop, not threshold tuning. Of the options weighed —
a regex pass for AU formats, widening low-confidence spans to token boundaries,
or accepting it under FR-8 — the regex backstop was chosen, and the pipeline now
routes through it (see "Detection goes through one entry point").

The two `xfail(strict=True)` tests in `tests/test_redact.py` are still there and
still strict, but they no longer pin an open defect: they feed `RECORDED_ENTITIES`
straight to `redact()`, which is the pre-backstop path, and so now characterise
*Comprehend Medical's* behaviour rather than the tool's. They are what makes the
backstop's justification falsifiable — if AWS ever fixes the truncation they fail
loudly, and the decision above needs revisiting. The end-to-end claim that the
number no longer survives is asserted in `tests/test_resolve_entities.py`.

---
## Why the phone number fails: US-centric format expectations

*2026-09-01.* Root cause of the failure recorded above. Comprehend Medical
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
## min_score stays at 0.5 provisionally, pending a formal decision (superseded 2026-09-07)

**Superseded by "FR-4 resolved: min_score = 0.001, derived from a stated cost
ratio" at the top of this log.** Kept for the reasoning it records — in
particular the argument for 0.0, which the resolving entry builds on rather
than discards. The value below is no longer what the pipeline runs with.

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

*Updated 2026-09-06:* the phone backstop removed the 0.383 span from the
pipeline's entity list, and with it the only observation on this note that the
threshold acted on at all. The numbers above still describe what `DetectPHI`
returns, but they no longer describe what reaches `redact()`. See the
consequence note under "Detection goes through one entry point" — the research
pass this entry defers now needs a corpus chosen for low-confidence entities
that are *not* AU mobiles.

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

*Scope clarified 2026-09-17 — see "FR-7 narrowed to the trust boundary" at
the top. The principle below is unchanged for anything released downstream;
what changed is that an internal review artifact is no longer covered by it.*

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
