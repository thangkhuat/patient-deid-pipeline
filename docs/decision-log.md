# Decision Log

Newest first. Each entry: decision, rationale, alternatives considered.

## CloudTrail data-event logging added for review-artifacts, closing
## the deferred gap from the hardening pass

*2026-09-26.*

Picks up the item named and deliberately deferred in the previous
entry: every access-control layer in this project governs whether
someone *can* decrypt a flagged entity, but nothing recorded whether
they actually *did*. This closes that specifically -- not account-wide,
not even bucket-wide, just the one question that matters: who read a
given object in review-artifacts, and when.

**Pricing confirmed before designing anything, not assumed.** Verified
directly against AWS's own current CloudTrail pricing page: data events
are $0.10 per 100,000 events delivered, with no free tier -- unlike
management events, which get one free copy per region. At this
project's actual scale, this is genuinely negligible: even 10,000
GetObject calls in a month, a generous estimate given the real usage
pattern, costs one cent. The real cost isn't the per-event price; it's
the new dedicated S3 bucket CloudTrail requires for its own log
delivery, which carries its own (small) storage cost and needs the same
hardening as every other bucket in this project -- versioning, TLS
enforcement, lifecycle expiry -- as a direct follow-up, not a deferred
afterthought.

**The required CloudTrail-to-S3 bucket policy is the sixth independent
instance, this session, of the same confused-deputy scoping pattern**
(S3->pipeline_lambda, S3->CloudFront, API Gateway->upload_backend,
API Gateway->auth_handler, API Gateway->review_backend, and now
CloudTrail->its logs bucket). Confirmed against AWS's own documented
policy shape rather than improvised: GetBucketAcl scoped to the bare
bucket ARN, PutObject scoped specifically to the
AWSLogs/{accountId}/* path rather than the whole bucket, and both
statements conditioned on aws:SourceArn matching this one specific
trail -- not cloudtrail.amazonaws.com broadly. Worth taking as further
confirmation this is a core, recurring AWS idiom, not something novel
each time it resurfaces.

**A real circular dependency, resolved the same way this project
already resolved an identical one.** The bucket policy needs the
trail's ARN in its condition; the trail can't be created until that
policy is already correctly in place -- a genuine chicken-and-egg
problem, not a hypothetical one. Solved by constructing the trail's
ARN as a plain string (fully predictable from account ID, region, and
the trail's own literal name -- no need to reference the trail
resource's actual output) rather than an attribute reference, which
would otherwise force Terraform to see this as a cycle. Paired with an
explicit depends_on on the trail resource itself, since Terraform has
no way to infer this specific real-world AWS ordering requirement from
the resource graph alone -- the same pattern already used for
input_notes' S3 event trigger depending on its Lambda permission.

**Scoped deliberately narrow, not left at CloudTrail's own defaults.**
include_global_service_events and is_multi_region_trail both set to
false -- this trail exists to answer one question about one bucket, not
to become a general-purpose account audit log. The advanced_event_selector
narrows further still: Data-category events, AWS::S3::Object resources,
ARN prefix-matched to review_artifacts specifically, and eventName
limited to GetObject alone. PutObject was deliberately excluded --
already fully attributable, since pipeline_lambda is the only identity
that ever writes there, so logging it would add cost without adding
any real accountability value.

**Status: applied and confirmed working live (2026-09-26).** terraform
plan showed 4 to add (the logs bucket, its public access block, its
bucket policy, and the trail itself), and apply created them. Tested
live end to end with a real reviewer account: viewing a review file
as that reviewer produced a GetObject log entry, delivered to the
cloudtrail-logs bucket within 5 minutes of the read -- within the delay
AWS documents for CloudTrail delivery, so logs are near-real-time, not
instant. The
chicken-and-egg ordering above holds in practice, not just in the plan.
Still open: the new cloudtrail-logs bucket's own hardening (versioning,
TLS-deny, lifecycle) is the immediate next step, so it doesn't sit as
the one under-hardened bucket in an otherwise consistently hardened
system.

## Security-hardening pass 1: versioning, TLS-only buckets, Cognito
## token lifetime

*2026-09-26.*

First systematic security review of this project, done layer by layer
against the actual current codebase rather than from memory -- IAM,
KMS, S3, Cognito, API Gateway, GitHub OIDC, and the Lambda handlers.
Most of what exists checked out clean: no drift in any IAM policy, all
three KMS key policies still correctly split admin from use, every
bucket still fully public-access-blocked, both review-facing routes
still correctly Cognito-gated. The earlier wildcard `@*` sub-claim gap
in github_oidc.tf was confirmed genuinely resolved, not just patched --
both roles now carry real, verified numeric IDs.

**Four real findings from that review, all fixed on
security-hardening-pass-1.** The Terraform changes are applied; the
review_backend change ships through CI when the branch merges to main,
so until then the live Lambda still returns responses without the
header.

1. **S3 versioning, all four buckets.** Named explicitly because the
   sync --delete decision (entry below) already stated frontend had "no
   versioning to recover from" -- the same gap existed, for a different
   reason, on the three PHI-adjacent buckets: no protection against an
   accidental overwrite or delete. Once enabled, versioning can only be
   suspended, never disabled again.
2. **Deny non-TLS access, all four buckets.** New aws_s3_bucket_policy
   resources for the three data buckets (none existed before); added as
   a second statement alongside frontend's existing CloudFront OAC
   grant, not a replacement. Every current caller already uses TLS:
   the Lambdas, review_cli.py and CI all go through AWS SDKs or the
   CLI, and nothing uses presigned URLs or plain-HTTP endpoints.
   **Coupling worth knowing:** frontend's statement is safe only because
   the distribution sets viewer_protocol_policy = "redirect-to-https".
   CloudFront reaches an S3 origin with whatever protocol the viewer
   used, so changing that to "allow-all" would make every plain-HTTP
   page request fail with a 403 from S3.
3. **Cognito token lifetime tightened** -- see below; the first attempt
   at this fix was wrong.
4. **review_backend._response() now sets Content-Type: application/json**,
   matching upload_handler's existing behaviour. Covered by a new test
   checking both a 200 and a 403 response, since both paths share the
   same helper.

**The Cognito fix, worth recording precisely because the first reasoning
was wrong.** First pass: removed ALLOW_REFRESH_TOKEN_AUTH from
explicit_auth_flows, reasoning that this stopped refresh tokens being
issued and closed a real pathway for redeeming a captured one. Caught in
review: explicit_auth_flows governs the InitiateAuth/AdminInitiateAuth
API family only -- this app never calls that family at all, only ever
the Hosted UI's authorization-code grant. So the change closed a door
nobody was using. Confirmed directly against AWS's own documentation,
quoted verbatim: "Users who sign in with an authorization code grant in
managed login or through federation can always refresh their tokens
from the token endpoint" -- unconditionally, regardless of
explicit_auth_flows. The actual, effective fix, added once that was
understood: refresh_token_validity, which governs token lifetime
regardless of which grant obtained it. Reduced from the 30-day default
to 1 hour -- a short value Cognito accepted without error; not verified
as the platform's enforced floor, just confirmed short enough to serve
the purpose. enable_token_revocation is set explicitly too: AWS already
enables revocation by default on new app clients, so this records the
choice in code rather than changing behaviour. Access and ID token
validity were pinned to 1 hour in the same change -- AWS's existing
defaults, so no behaviour change, but setting a token_validity_units
block otherwise leaves the provider to fill in the other units, and
pinning them keeps plans clean. The explicit_auth_flows change was kept
anyway -- harmless, and correctly closes an unused pathway -- but the PR
description was corrected to say so honestly rather than claim it as
the fix.

Separately identified, not yet acted on: ALLOW_USER_SRP_AUTH is the
flow that's actually unused by this app (review_cli.py authenticates
with IAM user keys, not Cognito; the browser only ever uses the Hosted
UI). Worth a future look at whether explicit_auth_flows can be reduced
further, possibly to an empty list -- not verified as valid, left as a
follow-up rather than guessed at.

**Noncurrent-version expiry: 30 days, on input_notes and
review_artifacts only.** Versioning alone would have kept a deleted
note's PHI content indefinitely as an old version; this closes that gap
deliberately rather than leaving it as a silent side effect of turning
versioning on. The number is a judgement call between two pulls, not a
derived value in the way min_score is:

- A longer window gives more time to notice an accidental delete or
  overwrite and recover from it -- the whole reason versioning exists.
- A shorter window cuts how long deleted PHI stays present and readable,
  to anyone with the right access, as an old version. That cuts against
  retaining PHI no longer than its purpose requires, and it can't be
  shortened for a single object: no Terraform-managed identity holds
  s3:DeleteObjectVersion, so a note deleted for erasure reasons lingers
  for the full window (plus S3's own lag, typically up to a day) unless
  an admin intervenes outside the normal roles.

30 days sits between the two, favouring recovery margin. In normal
operation no noncurrent versions are created at all -- uploads get a
fresh UUID key, and review artifacts are only rewritten if a note is
reprocessed -- so the window only ever applies to manual deletes and
overwrites.

Implementation notes: each lifecycle configuration depends_on its
bucket's versioning resource, since nothing else orders them. Removing
expired delete markers is a second rule in the same configuration
rather than part of the noncurrent-expiry rule, as a precaution against
a reported provider drift bug with the combined form; the split
configuration was confirmed stable by a clean follow-up terraform plan
("No changes") straight after apply. That shows the split form holds
here, not that the combined form would have failed.

Alternatives considered:
- **7 days.** Still catches a same-week mistake and meaningfully cuts
  how long deleted PHI lingers. Rejected in favour of a wider recovery
  margin, since a missing note may only be noticed when something
  downstream asks for it.
- **No expiry.** Rejected: indefinite retention of deleted PHI, as a
  side effect nobody chose.
- **No versioning on the PHI buckets at all.** Rejected: leaves an
  accidental delete permanently unrecoverable.
- **Expiry on frontend and redacted_output too.** Not done: neither
  holds raw PHI, and old versions cost negligible storage at this
  scale. Their noncurrent versions are kept indefinitely.

**Not what this closes:** the Phase 3 entry's "short-retention lifecycle
policy, not yet implemented" for input_notes is a different thing. These
rules expire only old versions. The *current* raw note in input_notes
still never expires, so that gap stays open.

**Known, deliberately deferred:** S3 data-event logging (CloudTrail) on
review_artifacts, so an actual GetObject read of encrypted review
content is individually logged, not just covered by generic
management-plane logging. Real, meaningful gap given how much of this
project's design rests on "who can decrypt what" -- but genuinely new
scope (a new CloudTrail trail, ongoing cost), not a quick addition like
everything else in this pass. Left as its own future decision.

## Phase 4 closed: Lambda code deploys from CI, gated on tests, through
## a third OIDC role

*2026-09-26.*

With this, both halves of the CI/CD phase are in place: the offline test
suite runs on every push and PR to main, and every deployable artifact
ships from CI -- the frontend via deploy-frontend.yml, all three Lambdas
via a new deploy job in test.yml. Terraform stays a human-run, human-
approved step for infrastructure; it no longer ships Lambda code at all.

**A second job in test.yml, not a new workflow file.** `needs:` only
works between jobs in the same workflow, and gating on tests was the
point: deploy runs only if the test job passed, only when github.ref is
refs/heads/main, and only on a push event. Deliberately stricter than
deploy-frontend.yml, which doesn't wait for tests at all -- a broken
Lambda breaks the PHI pipeline itself; a broken page breaks a page.

Honest note on that third condition, since the reasoning first given for
it was wrong: `github.event_name == 'push'` was meant to stop a manual
re-run of the test job from also deploying. It doesn't -- a re-run keeps
the original run's event, and re-running a job re-runs the jobs that
depend on it. With only push and pull_request as triggers, it's
currently redundant with the ref check (PR runs carry refs/pull/N/merge).
Kept anyway: it becomes the check that matters if workflow_dispatch is
ever added, since a manual run from main has ref refs/heads/main but
event workflow_dispatch.

**A separate role, patient-deid-github-actions-lambda-deploy, not the
frontend role widened.** Same trust policy shape (same OIDC provider
data source, aud sts.amazonaws.com, sub restricted to this repo's main,
name-based and ID-pinned), different and narrower job: only
lambda:UpdateFunctionCode and lambda:GetFunctionConfiguration, on the
three function ARNs via Terraform references. One identity, one
purpose, as everywhere else in this project -- and the stakes justify
it: this role can replace code that runs under roles with S3 access to
PHI-holding buckets and KMS decrypt.

**One shared zip for all three functions.** Checked before relying on
it: the three handlers' full import tree is the standard library plus
boto3/botocore, which the Lambda runtime provides -- no third-party
package since the KMS migration removed cryptography -- and the three
hand-built packages each contained only src/. If a handler ever needs a
real dependency, this becomes per-function builds.

**ignore_changes = [source_code_hash] on all three functions -- a real
tradeoff, accepted.** Without it, the next terraform apply for anything
at all would see the live code's hash differ from the local zip and push
the local zip back over CI's deploy. The cost: rebuilding a local zip
and running terraform apply no longer deploys code -- it's a silent
no-op for code now. The manual path is aws lambda update-function-code
directly. The local zips still have to exist, because filebase64sha256
is still evaluated at plan time.

**`aws lambda wait function-updated` after each update, not the -v2
waiter.** update-function-code returns once AWS accepts the upload, not
once the code is live, so without a wait the job could go green on a
deploy that later failed. Both waiters succeed on LastUpdateStatus
Successful and fail on Failed; the difference is what they poll.
Checked against botocore's own waiter model: -v2 polls GetFunction,
which would have needed a broader grant (it also returns a download URL
for the function's code); the original polls GetFunctionConfiguration.
Granting that one action and using the matching waiter was the narrower
choice. Worth recording because the first spec paired the -v2 waiter
with the GetFunctionConfiguration grant -- that would have failed every
deploy with AccessDenied after the code had already been updated.

**Actions pinned to the same commit SHAs as deploy-frontend.yml** --
checkout and configure-aws-credentials, in both jobs. setup-python stays
on @v5: there was no existing pin to copy, and it only runs in the test
job, which holds no credentials.

**Known gap, left deliberately: no all-or-nothing deploy.** Runner bash
uses -e, so the loop stops at the first failed function; the ones before
it are updated, the ones after aren't. That matters because the pipeline
and review_backend share report.py's review_queue format. Recovery is
"Re-run failed jobs", which redeploys all three from the same commit.
Real atomicity needs published versions and aliases -- more machinery
than a three-function, single-maintainer project needs today.

Verified for real on the merge of this change (Actions run 36116534748):
test job passed; deploy job passed every step, 09:06:14-09:06:32 UTC,
including all three waits. Checked afterward against AWS directly, not
just the job log: all three functions show LastUpdateStatus Successful,
LastModified 09:06:23 / 09:06:25 / 09:06:28 UTC, and an identical
CodeSha256 -- the one shared package, confirmed in all three places. The
role and policy existing is confirmed by the job assuming and using
them. That first deploy also shipped the upload validation entry below,
which until then was merged but not live.

Verified afterward: a note submitted through the real frontend, confirmed
in both redacted-output and review-artifacts, and a flagged entry opened
and correctly decrypted through the Reviewer UI -- the deployed code
proven correct in actual use, not just successfully uploaded.

Phase 4 as a whole: deploy-frontend.yml's first real run (a manual
workflow_dispatch from main, run 36112205515) also passed, closing the
"not yet verified" note on the GitHub Actions / OIDC entry below.

## Upload handler rejects notes the pipeline can't process, at upload
## time rather than downstream

*2026-09-26.*

upload_handler now returns 400 for three kinds of content it used to
accept: non-strings (int, null, list -- previously an uncaught
AttributeError the caller saw as a 500), empty or whitespace-only text,
and text over 20,000 characters. Maps to FR-1 (accept a plaintext
clinical note as input): this is the input contract made explicit.

**Why at upload, not in pipeline_lambda.** The upload response is the
only thing the Operator ever sees. pipeline_lambda runs asynchronously
off an S3 event, so a note it can't process -- DetectPHI rejects empty
text and anything over its limit -- used to fail there after the caller
had already been told 202 Accepted, with no path back to tell them.

**The limit is AWS's, not ours, and a test holds it to AWS's number.**
20,000 is DetectPHI's Text limit; botocore's service model states it
(min 1, max 20000), and both it and the handler count characters, not
bytes. A test compares MAX_NOTE_LENGTH against botocore's model directly,
so an AWS-side change picked up by a boto3 upgrade fails the build rather
than drifting silently. It also matches the frontend's CHAR_LIMIT; the
browser counts some characters (e.g. emoji) as two, so it is the stricter
of the two and nothing it allows gets rejected here.

**Whitespace-only rejected too** -- stricter than DetectPHI itself, which
would accept "   ". There is nothing to redact in it, and the frontend
doesn't trim before sending.

No frontend change needed: index.html already shows the error message on
any non-2xx response.

Shipped as its own PR, not folded into the CI-tests one, since it changes
production behaviour and the CI PR had been scoped to tests and workflow
only. Tests: eleven new cases -- each rejected type, blank content, the
exact boundary (20,000 accepted, 20,001 rejected), and the botocore
cross-check -- all confirmed to fail against the previous handler. CI
passed on the PR (run 36114879607); went live with the first CI Lambda
deploy (entry above). Not yet exercised against the live endpoint with
an actual bad request.

## Offline test suite runs in CI on every push and PR to main

*2026-09-26.*

.github/workflows/test.yml runs `python -m pytest` on Python 3.10 --
the Lambda runtime's version -- on every push and pull request against
main, with no paths filter: the point is catching regressions broadly,
docs and Terraform changes included. No AWS credentials and no OIDC
role in the test job, by design: the suite was already fully offline
(fake S3/KMS/Comprehend clients; live tests deselected by pytest.ini),
and a test that needed credentials to pass would be the thing to fix,
not something to work around. The job's token is `contents: read` only.

**`python -m pytest`, not bare `pytest`** -- verified, not assumed. In a
clean venv, bare `pytest` failed to collect every test file with
"No module named 'src'": there is no conftest.py and no pythonpath
setting, and it's `-m` that puts the repo root on sys.path. Same reason
CLAUDE.md already gave for running everything with `-m` locally.

**requirements.txt split in two.** requirements.txt is runtime-only
(boto3>=1.34); requirements-dev.txt adds pytest>=8.0 on top. The
existing version floors were kept rather than dropped to bare names.
README and technical-requirements.md now install from
requirements-dev.txt.

**A real incident this surfaced: one "offline" test wasn't.**
test_empty_text_is_rejected_by_the_client builds a real botocore client
to prove DetectPHI rejects empty text before any network call. Passed in
CI's clean environment; failed locally once the default AWS profile had
moved to `aws login` -- botocore resolved credentials first, hit the
login_session provider, and raised MissingDependencyException (awscrt
not installed) before reaching the check under test. Its docstring said
"needs no credentials"; it was reading the machine's default profile.
Fixed by passing explicit dummy credentials, so the test is independent
of whatever the local profile is. Recorded as a testing requirement in
technical-requirements.md.

**Tests added for the two handlers that had none.** lambda_handler.py --
the production path -- had no tests at all, and upload_handler.py
neither. Both read os.environ at import time, so the tests set the
environment first and import them fresh. Checked that they can actually
fail: temporarily routing lambda_handler through detect_phi() instead of
get_all_entities() (dropping the phone backstop) initially broke only
one test. The "no identifier survives" check was looking for the full
number, and a truncated span leaves "[ID] 678", which doesn't contain
it. Tightened to check the surviving digits too, the same way
test_resolve_entities.py does; after that, two tests caught it.

Verified: first CI run on the PR passed (run 36114860170) with 112
passed, 2 xfailed (the expected strict ones), 1 deselected (live). The
same result locally in a clean venv with all AWS config hidden, and with
the normal local environment.

## sync --delete adopted for frontend deploys, closing the DeleteObject
## gap named at merge time

*2026-09-26.*

Supersedes a specific line from the GitHub Actions / OIDC entry below:
"Removing stale objects is still manual: aws s3 sync --delete would
need s3:ListBucket, which neither deploy identity has." That was
accurate when written -- the workflow originally shipped with
aws s3 cp site/ s3://patient-deid-frontend/ --recursive, which never
removes anything, leaving the DeleteObject permission already granted
to patient-deid-github-actions-frontend-deploy unused. Left as a
recorded, deliberate gap rather than fixed inline at merge time, since
the PR under review then was scoped to getting the workflow's first
real run passing, not to closing every gap a review surfaced in the
same pass.

**Swapped to aws s3 sync site/ s3://patient-deid-frontend/ --delete.**
Confirmed the exact permission gap the earlier entry predicted: sync
needs to read the bucket's current contents before it can compute what
to add, update, or remove -- a bucket-level s3:ListBucket call,
structurally distinct from the object-level PutObject/DeleteObject
already granted (same bucket-vs-object ARN distinction learned
repeatedly elsewhere in this project). Added as its own statement,
scoped to the bucket's own ARN, no /* suffix, since ListBucket applies
to the bucket itself rather than individual objects within it.

**Deliberately sequenced before merging the workflow change that
depends on it** -- applying the Terraform change first and confirming
success, rather than merging both together, since a workflow calling
sync without the permission already in place would be a guaranteed
failure on its very next run, not a theoretical risk.

**--delete is a real, accepted behavior change, not a side effect --
worth recording precisely what it means going forward.** The bucket
holds no versioning, so this is genuinely irreversible: from this point
on, site/ is treated as the complete, authoritative list of what
belongs in patient-deid-frontend. Anything ever placed there by hand,
outside of what site/ contains, is deleted on the next automated
deploy with no way to recover it. Confirmed safe at the moment of
adoption -- the bucket held only index.html and review.html, identical
to site/'s own contents, so the first run under the new command will
delete nothing. The risk is forward-looking: it depends on site/ remaining the
sole source of truth for this bucket's contents, an assumption worth
re-checking if that ever stops being true.

## Frontend deployment moved into GitHub Actions, authenticated via
## OIDC -- no long-lived AWS keys stored in GitHub

*2026-09-26.*

A push to main touching site/** (or a manual workflow_dispatch run from
main) now uploads site/ to patient-deid-frontend and invalidates the
CloudFront cache. The workflow assumes a dedicated role,
patient-deid-github-actions-frontend-deploy, through GitHub's OIDC
provider.

**OIDC role, not patient-deid-frontend-deployer's access keys stored as
a GitHub secret.** Stored keys are long-lived and would sit in a second
place outside AWS; the OIDC token is minted per run and expires with
it. The frontend-deployer IAM user stays for manual deploys from a
local machine -- a person with a CLI profile, the same reason it was
created as a user and not a role.

**Trust policy scoped to this repo's main branch only.** aud must be
sts.amazonaws.com; sub must match refs/heads/main, so workflows on pull
requests or any other branch cannot assume the role. The second sub
entry pins the owner and repository numeric IDs
(thangkhuat@177017208/patient-deid-pipeline@1327731147) rather than
wildcarding them -- IDs survive an account or repo rename, names don't,
and a wildcarded ID would have matched anything the name-based entry
already matched, adding nothing.

**Permissions mirror frontend-deployer, plus one addition:**
cloudfront:CreateInvalidation, scoped to this one distribution's ARN.
The distribution uses default caching (up to 24h), so without it a
deploy could succeed and still not be visible.

**Uploads all of site/ (cp --recursive), not a hardcoded file list.**
A file added to site/ would otherwise silently never deploy. Removing
stale objects is still manual: aws s3 sync --delete would need
s3:ListBucket on the bucket itself, which neither deploy identity has.

**Actions pinned to commit SHAs, not version tags.** A tag can be
repointed at different code; this job holds AWS credentials, however
narrow.

**The OIDC provider is read as a data source, not managed as a
resource.** It already existed in the account, created outside
Terraform. There is exactly one per issuer URL per account, shared by
any future role trusting GitHub, so this role's lifecycle should not
own it.

Not yet verified by a real run: merging this change doesn't touch
site/, so the push trigger won't fire; the first check is a manual
workflow_dispatch run from main after apply.

## Frontend deployer identity created -- thang-admin no longer used for
## routine site deployments

*2026-09-26.*

Closes a mismatch that had existed since the very first frontend
deployment: every site file (index.html, review.html, and every
subsequent revision of both -- the file picker, the PKCE rewrite,
review.html's own creation) had been pushed using thang-admin's full
AdministratorAccess, purely because the bucket was correctly built
fully private from the start (no identity was ever given s3:PutObject),
and thang-admin's broad access was the pragmatic fix in the moment the
first upload failed.

Worth recording why this was a genuine inconsistency, not just untidy:
every other identity in this project is narrowly scoped to exactly what
it needs, with a correspondingly bounded blast radius if compromised --
pipeline_lambda can only touch its own three buckets, upload_backend
only writes input-notes, review_backend only reads review-artifacts.
thang-admin performing a small, routine, mechanical task (copying two
static HTML files) broke that pattern completely: a compromise of those
credentials was never bounded to "someone could deface two web pages,"
it was the entire account, PHI-holding buckets included.

**A new IAM user, not a role** -- deliberate, matching an established
pattern rather than defaulting to whichever shape was more familiar.
Roles in this project are for things AWS services assume
(pipeline_lambda, upload_backend) or temporarily-assumed test access.
This identity's actual job -- a person running aws s3 cp from their own
machine, as a routine habit -- is structurally identical to
patient-deid, terraform-patient-deid, and patient-deid-reviewer-cli:
all plain IAM users with their own access keys, not roles.

Named patient-deid-frontend-deployer, deliberately avoiding both
"Operator" and "Reviewer" -- both terms already carry specific,
established meaning elsewhere in this project (FR-3/FR-10), and reusing
either here would have recreated the exact naming ambiguity the
reviewer_test rename exists to have already resolved.

Granted s3:PutObject and s3:DeleteObject, scoped to
patient-deid-frontend's object-level ARN (the /* suffix, same
bucket-vs-object distinction already learned for GetObject/PutObject
elsewhere). DeleteObject included deliberately, not just PutObject --
a file ever renamed or removed from site/ would need it to actually
clean up the stale object in the bucket; PutObject alone only ever adds
or overwrites, never removes.

**thang-admin's own scope is explicitly unchanged**, not partially
retired -- worth being precise this is a correction of what had drifted
onto it opportunistically, not a reduction of its actual intended
purpose. It remains the human operator's day-to-day console/CLI
identity: creating and managing other IAM identities, the several
Console-only policy widenings terraform-patient-deid has needed this
session, Cognito account management, and general cross-service
verification. The underlying principle, worth recording plainly: the
test for carving out a narrow identity is whether a task is narrow and
repetitive enough to justify one -- frontend deployment (one bucket, two
file types, the same action every time) passed that test cleanly;
open-ended day-to-day administration does not, since "whatever
unanticipated task comes up next" can't usefully be pre-scoped, which is
exactly why terraform-patient-deid's own policy has needed reactive
widening five separate times this session rather than being narrowed
further from the start.

Verified for real, not just trusted from a clean apply: a genuine
aws s3 cp of index.html, run with --profile frontend-deployer alone,
succeeded -- the same task thang-admin had performed every previous
time, now correctly done by an identity whose only capability is
exactly this.

## reviewer_test renamed to patient-deid-reviewer-cli -- clarifying its
## real role, not retiring it

*2026-09-25.*

Closes an ambiguity that had quietly persisted since review_cli.py and
the Cognito Reviewers group were both built: two separate identities
existed for what looked like the same job, with no decision ever made
about how they relate. Resolved by deciding plainly: any real human
Reviewer is provisioned through Cognito going forward, exclusively --
they would never need an AWS account at all, the same reasoning that
already put the Operator side behind Cognito rather than a shared
secret. reviewer_test was never actually a parallel onboarding path for
real people; it's the credential behind review_cli.py, an operator/
debugging tool for whoever runs this system, unrelated to how real
Reviewers get set up. Renamed to reflect that -- patient-deid-reviewer-cli
-- rather than a name suggesting it was ever a test version of the real
thing.

**"Operator" was deliberately avoided as a replacement name**, despite
being the more obvious fit for "the person running this system" --
FR-3/FR-10 already define Operator as the note-submitting role, a
completely different identity. Reusing the term here would have
recreated the exact ambiguity this rename exists to remove.

**The actual rename mechanics, worth recording precisely since the
first attempt to describe them was wrong on two counts, both corrected
against real evidence before executing:**

- Initially believed the KMS key policy's principal statement (naming
  this identity by ARN) would need manual editing, and that a fresh
  access key would be required. Both wrong. Confirmed against AWS's own
  IAM documentation: a user's unique ID never changes on rename, and any
  policy referencing the user as a principal (exactly what the KMS
  statement does) updates itself automatically. Access keys are tied to
  that unchanged unique ID, not the name string, so the existing key
  pair -- and the reviewer-test local AWS CLI profile built on it --
  kept working without any regeneration.
- Confirmed directly against a real terraform plan output for the exact
  same scenario (renaming an aws_iam_user's name attribute) before
  trusting it: Terraform performs a genuine in-place update via AWS's
  UpdateUser API, not a destroy-and-recreate. The Terraform resource's
  own internal address (aws_iam_user.reviewer_test) was deliberately
  left unchanged -- only the name attribute's value changed -- since
  renaming the address itself would have forced Terraform to treat it
  as an entirely different resource.
- The two inline aws_iam_user_policy resources attached to this identity
  did NOT follow the rename smoothly, despite depending on
  aws_iam_user.reviewer_test.name via a direct reference. Terraform's
  plan showed both as "must be replaced," not updated in place --
  because this resource type's composite ID is built from
  {username}:{policy-name} concatenated together; changing the username
  changes that whole ID, which this specific resource type treats as
  force-new. A real, distinct mechanism from aws_iam_user's own
  in-place-updatable name, not the same behavior propagating through a
  dependency as first assumed. Judged acceptable regardless: both
  policies get destroyed and immediately recreated with identical
  content within the same apply, and this identity serves no live
  production traffic that could be affected by the brief gap.

Verified for real afterward, not just trusted from the plan output:
`review_cli.py --list --profile reviewer-test` against the renamed
identity correctly listed and decrypted a real flagged entity,
confirming both permissions and access keys survived the rename intact.

## Fernet retired, direct KMS Encrypt/Decrypt takes over -- the
## long-deferred "real target" finally built, with several real
## incidents along the way

*2026-09-25.*

Triggered by the Fernet key distribution gap becoming concrete a second
time: review_backend.py needed the exact same PATIENT_DEID_ENCRYPTION_KEY
pipeline_lambda already held, with still no real way for a genuine
Reviewer on a different machine to obtain it. Deferred since the
encryption design was first written; this is the migration that closes
it for good.

**Direct KMS Encrypt/Decrypt chosen over envelope encryption**, the two
paths this project has held open since the original design. Both close
the distribution gap equally -- decrypt access becomes purely "does this
caller's own identity have kms:Decrypt on this key," never a shared
secret again. Direct calls won on everything else: zero schema change
(content_encrypted stays exactly the field it already was, just holding
a different kind of string), and -- the concrete win -- cryptography
drops out of pipeline_lambda's and review_backend's dependencies
entirely, letting both return to the same plain boto3-only zip packaging
upload_backend and auth_handler always used. No more platform-specific
wheel installs for either.

Two API details confirmed against AWS's own documentation before writing
any code: decrypt()'s KeyId is technically optional for a symmetric key
(KMS reads which key encrypted a ciphertext from its own embedded
metadata) but specified anyway, per AWS's stated best practice, so a
decrypt against an unexpected key fails explicitly rather than silently
trusting the blob's own claim. And CiphertextBlob is raw binary, not
directly JSON-safe the way Fernet's own output always was -- needed an
explicit base64 encode/decode step Fernet never required.

load_encryption_key() deleted outright, not deprecated -- nothing calls
it once every site is updated, and a dead function reading a variable
nothing sets anymore is worse than removing it. encrypt_flagged_content(),
decrypt_flagged_content(), and build_report() all changed from taking
key: bytes to kms_client + key_id. Every call site updated to match:
lambda_handler.py, review_cli.py, review_backend.py, and pipeline.py
(see below -- initially missed).

REVIEW_ARTIFACTS_KMS_KEY_ID supplied differently depending on the
caller: an environment variable, Terraform-managed, for the two
Lambdas; a hardcoded module constant in review_cli.py, which pipeline.py
imports rather than duplicating -- both are genuinely local CLIs with no
Terraform-managed environment to read from, matching review_cli.py's own
existing pattern for REVIEW_ARTIFACTS_BUCKET. Terraform's two environment variables both use
aws_kms_key.review_artifacts.arn specifically, not .key_id, so the
Lambda-managed value and the two hardcoded local constants reference the
key identically rather than risking a subtle format mismatch between
them.

variables.tf's encryption_key variable removed entirely, along with it
the $env:TF_VAR_encryption_key step that had to be repeated before every
single plan/apply this whole project -- the exact thing that caused an
interrupted plan earlier this session when it was forgotten. Nothing
references it anymore; there is nothing left to remember to set.

**Six real incidents surfaced building and deploying this, worth
recording precisely since each is a distinct, non-obvious failure
mode:**

1. All three Lambda zips were simply missing from disk on the first
   terraform plan. Partly explained by the repomix snapshot used to
   verify file state: its own header states binary files are never
   included, so a missing zip was invisible in that review regardless of
   whether it existed. All three needed a full, fresh build regardless,
   since even a zip that did exist would have predated this migration's
   code changes.
2. review_backend.py's REVIEW_ARTIFACTS_KMS_KEY_ID was first written as
   a module-level os.environ[...] read -- executed once at import time,
   before any test fixture could monkeypatch it. The old
   load_encryption_key() pattern had avoided this by reading lazily,
   inside handler(), at the point of actual use. Fixed by moving the
   read inside handler() the same way.
3. The existing fake_s3 fixture unconditionally returned the fake S3
   client regardless of which AWS service boto3.client() was asked for.
   Needed updating to dispatch by service name, and to share one
   FakeKMS instance between the fixture that encrypts test data and the
   one handler() picks up internally -- otherwise a ciphertext created
   in one fake KMS store wouldn't exist in the other.
4. report.py's actual changes had never been saved to disk from an
   earlier point in this session, despite having been given as code --
   caught directly by test failures showing the old two-argument
   signature was still live. Worth recording as its own class of
   mistake: code given in conversation and code saved to disk are two
   different claims, and this session's own discipline of verifying
   actual file content before editing exists precisely because of
   exactly this gap.
5. pipeline.py -- the original local CLI entry point, genuinely separate
   from lambda_handler.py -- was missed entirely in the first round of
   call-site updates. Caught not by directly inspecting it first, but by
   reasoning through test_pipeline.py's own docstring ("main() is not
   tested here") and realizing that didn't matter: `from src.deid.pipeline
   import load_note` still executes pipeline.py's entire module top level,
   including its own broken import of the now-deleted
   load_encryption_key, so the whole test file's collection would fail
   regardless of what its own tests actually exercise.
6. The zip rebuild that followed incident 4 happened before report.py's
   fix was confirmed correct -- meaning pipeline_lambda.zip and
   review_backend.zip were deployed carrying new handler code paired
   with a still-broken report.py, a mismatch invisible at import time
   and only surfacing when handler() actually tried to call
   build_report() with arguments the bundled version didn't support.
   Diagnosed by noticing both zips' deployed source_code_hash values
   were identical to each other -- strong evidence both were built from
   the same, at-that-time-still-broken source tree -- and confirmed by a
   fresh rebuild producing a new, different, now-correct hash on both.

**Genuine, still-open gap, deliberately not resolved here:** objects in
review-artifacts encrypted before this migration are still Fernet
ciphertext, not KMS. review_backend.py's new code would call KMS Decrypt
against them and get a real, hard failure (InvalidCiphertextException),
currently surfacing as an unhandled 500 -- the handler's exception
handling only translates NoSuchKey specifically. Deliberately not
migrated or specially handled; this project's test data has never been
anything but disposable, so deleting the old entries is the leading
option, but the actual call is still open.

**Also still open, surfaced but not answered:** fixing pipeline.py's
code revealed that patient-deid -- the original, tightly-scoped local
runtime identity, holding only comprehendmedical:DetectPHI since the
very start of this project -- has never been granted any KMS permission
on review_artifacts' key. Running pipeline.py locally will fail with
AccessDenied until this is deliberately decided one way or another; not
resolved by default, consistent with this identity never having gained
scope without an explicit decision behind it.

**Final verification, the actual proof this works, not just that
FakeKMS-backed tests pass:** a fresh note submitted through the real,
deployed frontend was encrypted by pipeline_lambda's new KMS code and
successfully decrypted back through review_backend's new KMS code, via
the real, authenticated Reviewer UI -- confirmed only after the stale-zip
incident above was caught and fixed. The full chain -- real Cognito
login, real API Gateway, real Lambda execution, real KMS Encrypt and
Decrypt calls against the real review-artifacts key -- proven working
together, closing out the Fernet-to-KMS migration this project named as
its real target from the very first day the encryption design was
written.

## Reviewer web UI built: Cognito Groups close the authorization gap a
## shared JWT check couldn't, review.html reuses review_cli.py's logic

*2026-09-25.*

Reopens a question deliberately settled against a webpage twice earlier
this session -- worth recording why it flipped rather than letting the
final answer look like the first one. The original reasoning (IAM
credentials can't safely live in a public browser page) was never
wrong; it just answered a narrower question than what was actually
being asked. "Easier to access than the CLI" specifically meant no
local setup at all -- which only a real backend-plus-Cognito system
provides, the same shape already built for the Operator. Reusing that
shape surfaced a genuine, new security gap worth treating as the actual
reason this became a real, justified build rather than scope creep: a
shared JWT authorizer only confirms "a valid, logged-in user of this
pool" -- with nothing to stop any Operator who simply logged in to
submit a note from also reaching Reviewer-only content.

**Confirmed, before writing any Terraform, why the fix couldn't live at
the API Gateway layer at all.** Cognito's cognito:groups claim is
included in the access token by default, confirmed against AWS's own
access-token documentation -- no extra configuration needed once a user
is in a group. But HTTP API's native JWT authorizer, confirmed against
a second source directly comparing REST and HTTP API authorizer types,
only supports OAuth scope-based checks -- structurally incapable of
inspecting an arbitrary claim like cognito:groups. The group check has
to happen inside the backend Lambda itself, reading
event["requestContext"]["authorizer"]["jwt"]["claims"] -- confirmed as
the real, documented mechanism API Gateway uses to hand decoded claims
to a Lambda integration, not a workaround.

is_reviewer() written to tolerate a real, unresolved documentation
ambiguity rather than guess: AWS's REST API authorizer is documented to
flatten cognito:groups into a comma-separated string, and it's unclear
from documentation whether HTTP API preserves the JSON array shape or
does the same flattening. The first version,
`"Reviewers" in claims.get("cognito:groups", "")`, was *not* correct
either way, despite looking it: on a string, Python's `in` is substring
containment, so a group named "ReviewersPending" or "NotReviewers"
would have passed. Caught in pre-merge review. parse_groups() now
normalises every shape -- list, "[a b]", "a,b" -- to a list of exact
names first (Cognito group names can't contain whitespace, so splitting
is lossless), and is_reviewer() checks list membership only. The
client-side hint in review.html got the same fix: Array#includes on
the decoded array, not String#includes.

**Cognito User Pool Group ("Reviewers"), not a second, parallel auth
system.** The existing test account added via admin-add-user-to-group,
same manual, administrator-driven pattern already established for
account creation itself.

**review_one() couldn't be reused as-is, and the reason is worth
recording precisely.** It printed to stdout and returned None -- correct
for a terminal, meaningless for a Lambda, which has no terminal a
browser could ever see. Refactored into get_review_entries(), returning
structured data instead of printing it; list_pending_reviews() similarly
upgraded to return each entry's unencrypted metadata (type/score/action)
rather than bare keys, once it was clear this needed to exist as real,
structured data anyway. review_cli.py's own presentation layer (the
print statements) moved into main(), the only place that actually needed
formatting. review_backend.py now genuinely reuses both functions
unchanged -- no duplicated fetch-or-decrypt logic anywhere.

**review_backend.py's own IAM role and the review_artifacts KMS key's
third statement mirror reviewer_test's existing access exactly, as a
Lambda role instead of a personal IAM user** -- s3:ListBucket,
s3:GetObject, kms:Decrypt, nothing more. Packaged with the same
platform-specific cryptography wheel pipeline_lambda needed (this
function imports report.py), not the plain-boto3-only zip that sufficed
for upload_backend and auth_handler.

**One Lambda serving two routes (GET /reviews, GET /reviews/{key}) via
event["requestContext"]["routeKey"] dispatch**, rather than splitting
into two separate functions the way pipeline_lambda and upload_backend
are split. Deliberate: both routes share the identical
authorization-and-data-access logic: confirm Reviewer membership, then
read from the same bucket. Splitting would have meant duplicating that
shared logic across two functions for no real gain.

The API Gateway→review_backend invoke permission is this session's
fifth independent instance of the same confused-deputy scoping pattern
(S3→pipeline_lambda, S3→CloudFront, API Gateway→upload_backend,
API Gateway→auth_handler, now API Gateway→review_backend) -- worth
treating as confirmation this is a core, recurring AWS idiom rather than
noting it as novel each time.

**CORS needed updating a third time this session**, for the same
underlying reason as the two times before it: the existing
configuration only ever allowed exactly what had been sent up to that
point. allow_methods gained GET (the config only listed POST, since
that's all upload_backend ever needed); review.html's calls needed
Authorization already added for index.html's upload flow, so that part
carried over for free.

**review.html duplicates index.html's entire PKCE login flow** --
generateCodeVerifier, generateCodeChallenge, the token exchange, session
storage. A real, acknowledged cost, not an oversight: with no shared JS
module or build step in this project, there was no way to share this
code between two static files without introducing tooling this project
doesn't otherwise have. Worth revisiting if a third page is ever added.

**Client-side group checking in review.html is explicitly a UI
convenience, not the security boundary** -- decodeJwtPayload() reads
cognito:groups purely to avoid showing an Operator a review UI that
would fail anyway on the first real request. The actual enforcement is
is_reviewer() running server-side, on every single call; nothing about
the client-side check is trusted for anything.

review.html's own callback URL (/review.html, not the bare root) had to
be added to the Cognito app client's callback_urls and logout_urls
alongside index.html's -- Cognito rejects any redirect target it wasn't
explicitly told about in advance, confirmed by needing exactly this fix
before the login flow would complete.

**Cross-page navigation was missing entirely until named and fixed as
its own small pass** -- neither page linked to the other; each was only
reachable by someone who already knew its exact URL. Closed with a
one-line footer link on each, placed inside the already-authenticated
view specifically, not the login screen, so it's never offered before
it would actually be useful.

Full loop verified for real, the same way as every other milestone this
session: logged in as the test account (now in the Reviewers group),
loaded the pending-review list through the browser, opened a real
flagged entry, and confirmed the decrypted content rendered correctly
-- KMS, the Fernet key, and the group-authorization check all working
together through the actual UI, not a terminal standing in for it.

## Auth gap closed: Cognito Managed Login with PKCE replaces the earlier
## shared-secret plan, full pipeline re-verified with real authentication

*2026-09-25.*

Supersedes the shared-secret Lambda authorizer design sketched a few
messages before this thread -- reconsidered and abandoned before any
code was written, on a specific argument: a shared secret cannot answer
"who actually submitted this note," and in a hospital-adjacent context
that's not a minor gap. Everyone using it would be indistinguishable
from everyone else, and revoking one person's access would mean
rotating it for all of them. This was also, on reflection, the first
place in this entire build where "prove who you specifically are" would
have been replaced by "prove you know a string" -- a real mismatch with
every other identity in this system (Operator, Reviewer, Downstream
consumer), which were all designed around specific, accountable access
from the start.

**Cognito User Pool, admin-provisioned accounts only.** Confirmed
against AWS's own security guidance before building this:
self-registration would let anyone on the internet create an account
and sign in -- no more restrictive than no auth at all for this
system's purposes. admin_create_user_config.allow_admin_create_user_only
= true closes that off; every account is created deliberately, by an
administrator, via admin-create-user.

**TOTP MFA required from the start**, not added after the fact --
mfa_configuration set before the pool held a single real account, since
retrofitting MFA onto existing users later would mean disrupting
already-active logins rather than making it the default from day one.
TOTP chosen over SMS: no per-message cost, no phone-number requirement,
and the more secure of Cognito's two mechanisms (SMS is documented as
vulnerable to SIM-swapping).

**App client has no secret** (generate_secret = false) -- this runs
entirely in browser JavaScript, and a secret embedded there would be
exactly the exposure already ruled out when the shared-secret plan was
rejected. Authorization Code Grant with PKCE used specifically because
of that: AWS's own guidance states plainly that public clients with no
secret should use PKCE, not the bare authorization code flow. PKCE adds
a locally-generated code_verifier (kept in sessionStorage, never sent
over the network) and its hashed code_challenge (sent with the initial
redirect); the token exchange must present the original verifier,
proving the party completing the login is the same one that started it.

**Access token, not ID token, sent to the API.** Confirmed against AWS's
own documentation before implementation, specifically to avoid the
"real login, still rejected" failure mode that sending the wrong token
type would produce: HTTP API's JWT authorizer validates the access
token's aud/client_id claim, not the ID token's.

**JWT authorizer added to the existing aws_apigatewayv2_api.upload**,
replacing authorization_type = NONE with JWT and the authorizer's id --
an edit to the existing route resource, not a new one, following the
same care already established after the CORS duplicate-resource
mistake. Verified directly and deliberately: the exact same
unauthenticated request that had succeeded on every previous test this
session was retried immediately after this change and correctly
returned 401 -- concrete proof the gap was closed, not just that a
resource existed.

**A second, genuinely new CORS gap surfaced by adding the Authorization
header** -- worth recording as its own finding, since it's a distinct
mechanism from the original CORS work. allow_headers only ever listed
content-type, correctly, because nothing sent anything else at the
time it was configured. Adding the Authorization header to the upload
fetch() call meant the browser's preflight OPTIONS request now asked
permission for a header the API's CORS policy never anticipated,
producing a fetch() failure indistinguishable from a real network error
-- the same "blocked before the request reaches the API" mechanism
already learned, just triggered by a header that didn't exist in the
system until this exact change. Fixed by adding "authorization"
alongside "content-type" in allow_headers.

sessionStorage used for the access token, not localStorage -- cleared
automatically when the tab closes, and AWS's own guidance specifically
flags localStorage as readable by any injected script (XSS exposure)
for anything holding real tokens.

**Known, deliberately bounded limitation:** no silent token refresh
implemented. An expired access token (roughly one hour) surfaces as a
401 on the next submit attempt, at which point the page clears the
stored token and returns to the login screen rather than transparently
using the refresh token in the background. A real, accepted scope
decision, not an oversight -- refresh-token handling would have been a
meaningful addition to an already large piece of work, worth its own
focused pass rather than folded in here.

**Full chain re-verified with real authentication in place, the same
way as every previous milestone this session:** logged in through
Managed Login, completed TOTP, submitted a note that scores below
review_threshold, and confirmed matching reference IDs landed in both
redacted-output and review-artifacts. Every layer built across this
entire project -- detection, redaction, encryption, storage, the event
trigger, the upload API, hosting, CORS, and now real, individually
accountable authentication -- proven working together end to end, not
just individually correct.

## Real frontend built and deployed; full pipeline verified end-to-end
## by an actual user through the actual UI

*2026-09-24.*

Closes out index.html as a genuine, working page -- textarea with live
character-count feedback against Comprehend Medical's 20,000-character
limit, async-honest status handling (submission confirmed, not
completion -- matches upload_backend's own 202 semantics, never implying
a result the page can't actually confirm), and a file picker layered on
top via FileReader, not a separate upload mechanism.

Deliberately kept both the file picker and the textarea rather than
replacing one with the other, considered explicitly rather than defaulted
into:
- The textarea is the only point where a person sees content before it
  submits -- FileReader loads a selected file's text into it, but
  nothing auto-submits. That gap is a real review step: catching a wrong
  file, noticing an over-limit note before it's rejected, just seeing
  what's about to leave the browser. Removing it would mean file
  selection submits blind, with no chance to check or edit first.
- Not every real note starts as a file on disk. A common clinical
  workflow is copying text directly out of another on-screen system (an
  EHR's own display, for instance) with no "save as file" step at all --
  the file picker serves "I have a file," the textarea serves "I'm
  copying this from something I'm looking at right now." Different
  input paths, not one being redundant with the other.
- Practically, every test this entire session -- from the first DevTools
  fetch() call through every verification since -- has gone through
  pasted or typed text. Removing that path would make quick testing
  meaningfully more annoying going forward, for no real gain.

fileInput.value is explicitly cleared alongside textarea.value on a
successful submission -- without it, the file input keeps showing the
previously-selected filename even after the form has visibly reset,
a small but real stale-UI-state bug worth avoiding deliberately rather
than discovering later.

**Final verification, the one this whole build has been building toward:**
a review-queue-triggering note (scoring below review_threshold, same
category as the "occupational therapy department" example used
throughout this project's threshold work) submitted through the actual
deployed form -- not a script, not a console-pasted fetch(), a real
person clicking through a real page. Confirmed present, with matching
reference IDs, in both redacted-output and review-artifacts. This is the
first time the complete chain -- browser form, CORS, API Gateway,
upload_backend, the S3 trigger, pipeline_lambda, Comprehend Medical,
redaction, the artifact split, both encryption paths -- has been
exercised entirely as an end user would, rather than through a
developer-facing substitute for one at any point in the chain.

Phase 3 and Phase 3.5 are both complete as a result: every piece
designed across this project's infrastructure work is now proven working
together, not just individually correct or reasoned about on paper.

## Frontend hosting (CloudFront + S3) built and CORS closed -- full
## browser-to-pipeline chain verified

*2026-09-24.*

**Static hosting, same private-bucket discipline as every other bucket in
this project.** patient-deid-frontend is never made public directly --
public access block applied unconditionally, same as input_notes,
redacted_output, and review_artifacts. CloudFront reaches it through
Origin Access Control (OAC), AWS's current recommended mechanism, rather
than opening the bucket to the world just because it happens to serve
web pages instead of PHI data. The bucket policy grants s3:GetObject to
cloudfront.amazonaws.com, scoped by an AWS:SourceArn condition naming
this one specific distribution -- the third independent instance this
session of the same "confused deputy" pattern already applied to the S3
event trigger's aws_lambda_permission and the API Gateway invoke
permission: a broad service principal narrowed to exactly one resource,
not trusted at the category level.

**Manual deployment gap, named rather than quietly worked around.** No
identity in this project holds s3:PutObject on this bucket -- by design,
since the bucket policy only ever grants CloudFront read access. The
placeholder index.html was uploaded using thang-admin's broad
credentials, the same identity this project's own earlier reasoning
scoped specifically for day-to-day human console/CLI work. Workable for
getting a placeholder live today, but worth being honest it doesn't
match the narrowly-scoped-identity discipline applied everywhere else in
this system. A real deployment pipeline would want its own dedicated,
narrowly-scoped "frontend deployer" identity rather than a human's admin
credentials standing in for it indefinitely -- not solved here,
deliberately deferred as Phase 4 territory rather than fixed as a
shortcut now.

**CORS added to the existing aws_apigatewayv2_api.upload resource**, not
a separate resource -- HTTP APIs configure CORS as a block directly on
the API itself. All three fields deliberately narrowed, not left at
permissive defaults: allow_origins names the exact CloudFront domain,
not a wildcard; allow_methods is POST only, since this API has exactly
one route; allow_headers is content-type only, the sole header
upload_handler.py's actual code path ever sends or checks. Same
narrow-scoping instinct already applied to every IAM policy and KMS key
statement this session, applied here to browser-origin policy instead.

**One real Terraform error along the way, worth recording precisely.**
Adding the cors_configuration block was intended as an edit to the
existing resource; a second, complete aws_apigatewayv2_api "upload"
block was pasted in alongside it instead, producing "Duplicate resource
... configuration." Fixed by merging cors_configuration into the
original declaration and deleting the accidental second block entirely
-- a copy-paste mechanics error, not a logic error, but worth recording
since it's a distinct failure mode from anything hit earlier this
session.

**The actual proof CORS works, and why it needed a genuinely different
test than anything used before:** Invoke-RestMethod, used to verify
upload_backend's HTTP path a few entries back, has no concept of CORS at
all -- it's a command-line client, not a browser, so it was structurally
incapable of catching a CORS misconfiguration even if one existed.
Verified instead with a real fetch() call, run from the browser's own
DevTools console while the page was loaded from the actual CloudFront
origin -- the only way to genuinely exercise the preflight OPTIONS
request and origin check a real frontend would trigger. Returned the
correct 202/message/id shape.

**Full chain confirmed from that one genuine browser action**, not
assumed from the API response alone: the resulting object appeared in
input_notes (upload_backend's own write succeeded) and, separately, in
redacted_output (confirming the S3 event still fired automatically and
pipeline_lambda ran the complete detect-and-redact chain end to end).
First time this entire system has been exercised by an actual webpage
rather than a developer tool or a hand-typed command standing in for
one.

**What's still genuinely unbuilt, not to be confused with what's now
proven:** index.html remains a single static placeholder line -- no
form, no real JavaScript, nothing a person could actually use to submit
a note yet. Everything verified today proves the underlying pipes work
correctly; building real, usable frontend content is separate, still-
open work.

## Frontend split from the Upload API: static site, not a combined backend service

*2026-09-24 (retroactive -- the decision itself was reasoned through and made
in an earlier session; captured here now since it was never given its own
entry, only referenced afterward as "several sessions back," a phrasing
this entry exists to replace).*

Chose a fully static frontend (S3 + CloudFront) calling a separate Upload
API (API Gateway + Lambda), over a single combined service handling both
UI-serving and uploads. Same one-identity-one-purpose principle already
applied throughout this project's IAM design, extended one layer up to
the architecture itself.

A static site has no running server code at all -- nothing to exploit,
nothing to patch, since there's no application process serving those
pages in the first place. The only thing genuinely exposed to the
internet with real logic behind it is the narrow upload endpoint,
already scoped to writing into input-notes and nothing else. Also keeps
the system consistent with the serverless, event-driven direction
already chosen for the backend, rather than mixing in one traditional
always-on service.

Known, accepted cost: the frontend and the API are genuinely different
origins, so the browser enforces CORS -- the API must explicitly declare
which origins may call it, or a real frontend's requests get blocked
before they reach this API. A JSON POST isn't a CORS "simple request",
so the browser sends a preflight OPTIONS request first; with no CORS
configuration the API never answers it correctly, and the browser
withholds the real POST entirely. Not silent in the sense of leaving no
trace -- the browser logs a CORS error and the calling code's fetch()
promise rejects -- but silent from the API's own perspective, since the
request never arrives. Not yet implemented as of the upload_backend
deployment entry below.

## upload_backend deployed: Lambda, API Gateway, and a real end-to-end HTTP test

*2026-09-24.*

Closes out the IAM foundation that's existed since Phase 3.5 was first
scoped -- see the 2026-09-20 entry, "Phase 3.5 added — frontend was
never part of the original scope" -- with nothing running under it.

upload_handler.py deliberately simple, doing exactly one job: accept JSON
text, write it to input_notes, return without waiting for processing.
Plain-text JSON body chosen over multipart/binary upload -- this
project's own scope has never involved real binary files, only
plaintext clinical notes (FR-1), so routing through API Gateway's
binary-media-type handling would have solved a problem this system
doesn't have. Response is 202, not 200: this handler's job ends at a
successful S3 write, and has no way to know whether pipeline_lambda's
detection and redaction, triggered independently and asynchronously by
the resulting S3 event, ever ran. Claiming 200 would assert something
this function can't actually confirm.

Object keys are UUID-based (uuid4().txt), not derived from any
client-supplied filename -- same "never name a file from
patient-identifying content" principle already applied to
write_report()'s timestamp-based filenames.

Lambda deployed with meaningfully smaller timeout (10s) and memory
(128MB) than pipeline_lambda's (30s/256MB): this function performs one
S3 write and returns, never calls Comprehend Medical, never does
detection or redaction work. No cryptography dependency needed either --
boto3 alone, already bundled in Lambda's runtime, covers everything this
handler does, so packaging is a plain zip with no platform-specific wheel
step.

API Gateway built as an HTTP API (protocol_type = "HTTP"), not a REST
API -- AWS's own newer, simpler, cheaper offering for exactly this
shape of single-Lambda-backed endpoint. Worth recording the naming
collision this produced: "HTTP API" is AWS's product name for this API
type, unrelated to transport encryption -- the actual invoke URL is
https-only regardless, confirmed against AWS's own SDK documentation,
which uniformly writes the default execute-api endpoint as
https://{api_id}.execute-api.{region}.amazonaws.com with no plain-HTTP
option offered anywhere.

A second aws_lambda_permission was needed, scoped with source_arn to
this specific API's execution ARN -- the same "confused deputy"
protection already applied to input_notes' S3 trigger, now against a
different calling service (apigateway.amazonaws.com instead of
s3.amazonaws.com). Same underlying AWS security pattern, second
independent instance of needing it.

Verified with a genuine external HTTP request (Invoke-RestMethod), not
just a Lambda console test event -- the console test had already proven
the handler's own logic correct (both the success path and, deliberately,
the malformed-body 400 path), but not that a real caller outside AWS
could reach it. This request round-tripped through the public internet,
API Gateway, the Lambda, an S3 write, and triggered pipeline_lambda's
existing chain automatically, confirmed by the resulting object appearing
in redacted-output.

Known, deliberately unresolved gaps, worth ranking by actual severity
rather than the order they were found: POST /upload currently has no
authorization at all -- aws_apigatewayv2_route defaults to
authorization_type = NONE when unspecified, and this route never
overrides it. Anyone who discovers the invoke URL can trigger a real,
billed DetectPHI call and real S3/KMS writes, with zero authentication.
This matters more than CORS: CORS only restricts requests originating
from a browser's own JavaScript, with no effect on curl, a script, or
any direct HTTP client -- precisely the kind of caller an unauthenticated
public endpoint is actually exposed to. CORS needs fixing before a
browser-based frontend can use this endpoint; the missing authorization
needs fixing before this endpoint is trusted with anything beyond
controlled testing, regardless of what calls it.

The handler also does not enforce Comprehend Medical's 20,000 UTF-8
character single-document limit on submitted content. An oversized note
is accepted, written to S3, and returns 202 -- success, from the caller's
perspective -- then fails inside pipeline_lambda when it actually
attempts detection, with no path back to the original caller and no
visible trace outside that Lambda's own CloudWatch logs.

CORS was flagged as a known cost when the split frontend/API architecture
was first decided -- see the entry above -- and remains open alongside
these two.

Cleanup: thang-admin's temporary trust-policy entry on upload_backend
(added solely to enable STS-based testing before this Lambda existed)
has been reverted -- the role's trust policy is back to lambda.amazonaws.com
only. reviewer_test is kept, not torn down: narrowly scoped, and useful
for testing the still-open Fernet key distribution gap whenever that
work happens. Its name honestly reflects "test identity," not "the real,
permanent Reviewer" -- a promotion decision deliberately left for later,
not resolved here.

## Fernet key distribution has no real mechanism -- surfaced by the
## first genuine Reviewer decrypt

*2026-09-23.*

reviewer_test successfully read and KMS-decrypted a review-artifacts
object -- the outer, S3/KMS layer of protection genuinely works, gated
correctly by real IAM policy. The inner layer does not have an
equivalent: decrypting the actual content_encrypted value still requires
PATIENT_DEID_ENCRYPTION_KEY, which exists only as a local environment
variable on one machine. A genuine Reviewer, on different hardware, has
no path to that value through anything built so far -- the outer lock is
now identity-based and auditable; the inner one is still "whoever has
the shared secret."

Not a new problem -- this is precisely what the KMS envelope-encryption
migration, deferred since the encryption design was first written, was
always meant to solve: tying decrypt ability to the caller's own AWS
identity rather than a distributed shared secret. Today's finding is the
first concrete evidence of the cost of not having done it yet, rather
than a new argument for doing it.

## Phase 3 completed: redacted-output, review-artifacts, and the Pipeline
## Lambda wired end-to-end

*2026-09-23.*

redacted-output and review-artifacts built to the same pattern already
proven on input-notes -- bucket, SSE-KMS, public-access block, scoped IAM
-- with one genuine difference: pipeline_lambda writes to these, so their
KMS "user" statements grant kms:GenerateDataKey and kms:Encrypt, not
kms:Decrypt. Confirmed via AWS's own docs that SSE-KMS PutObject requires
kms:GenerateDataKey on the caller specifically, the write-side mirror of
the read-side kms:Decrypt requirement already learned on input-notes.

Pipeline Lambda deployed for real, closing out the role that has existed
since early Phase 3 with nothing running under it. Packaged with the
Linux-targeted cryptography wheel (--platform manylinux2014_x86_64),
since a Windows-built wheel would fail silently at runtime, not at
packaging time. Triggered via aws_s3_bucket_notification on input-notes,
gated by a separate aws_lambda_permission scoped with source_arn to that
one bucket specifically -- without it, principal = "s3.amazonaws.com"
alone would permit invocation from any S3 bucket in any account, the
"confused deputy" pattern AWS's own security guidance names explicitly.

Fernet key supplied to the Lambda as a plain environment variable via a
sensitive Terraform variable, sourced from the same PATIENT_DEID_ENCRYPTION_KEY
already set locally via setx -- explicitly still the interim design, not
a new decision. Known, unavoidable limitation recorded here rather than
discovered later: Terraform's local state file necessarily contains this
value in plaintext, since Lambda's environment configuration is part of
the resource's tracked state. Not something the sensitive=true flag or
the TF_VAR approach avoids -- both only keep the value out of the .tf
source and out of plan/apply console output.

Getting from a deployed function to a genuinely working one took five
separate, real bugs, worth recording precisely since each is a distinct,
non-obvious failure mode:

1. Handler naming mismatch. lambda.tf declared
   "src.deid.lambda_handler.handler"; the actual file was named
   handler.py. Produced Runtime.ImportModuleError, not a permissions
   error -- worth remembering Lambda's import path is a literal string
   match, nothing fuzzy about it.
2. Missing CloudWatch Logs permissions. logs:CreateLogGroup,
   logs:CreateLogStream, and logs:PutLogEvents are not automatically
   granted to a hand-built execution role -- confirmed against AWS's own
   documentation. Without logs:CreateLogGroup specifically, AWS won't
   even auto-create the log group on first invocation, which is why the
   symptom was total silence (no log group at all) rather than an error
   inside one. This is precisely why bug 1 was invisible until this was
   fixed first.
3. Missing comprehendmedical:DetectPHI. Every S3/KMS permission
   pipeline_lambda needed had been granted; the one permission its
   actual handler code calls first was never carried over from
   patient-deid, the original IAM user this logic was built and tested
   against locally.
4. iam:CreateUser wall. terraform-patient-deid's inline policy only ever
   covered role actions (every identity built through Terraform so far
   had been a role) -- creating reviewer_test, the first IAM user this
   project's Terraform ever touched, needed a new ManagePipelineUsers
   statement added by hand through the Console, same bootstrapping
   limitation as every previous permission-widening this project has
   hit.
5. KMS decrypt gaps on both output buckets, discovered by trying to
   verify the pipeline's own output. Neither key's policy had ever named
   an identity capable of reading back what pipeline_lambda writes --
   correctly, by original design, since no Downstream consumer or
   Reviewer identity existed yet. Closed by adding thang-admin to
   redacted-output specifically (justified: content already meant to be
   safe for an external consumer is safe for the account's own trusted
   operator) and creating reviewer_test as a genuine, separate identity
   for review-artifacts (declined to extend thang-admin there --
   collapsing "account administrator" and "has legitimate clinical
   access to this patient" into one identity would undo the actual
   access-control distinction this bucket exists to enforce).

End-to-end proof, not just individually-passing pieces: the
"occupational therapy department" test note (see the 2026-09-07,
expanded 2026-09-17, ADDRESS false-positives entry) was uploaded
through the real upload_backend role via STS assumption, triggered the Lambda
automatically via the S3 event, and its review_queue entry was read back
and correctly decrypted by reviewer_test -- the first genuine,
non-manual proof that every boundary designed across this project holds
simultaneously against real infrastructure, not just in isolation.

## Phase 3 infrastructure: Terraform project and input-notes fully provisioned

*2026-09-21.*

Dedicated, separate Terraform state for this project -- not shared with
portfolio-infra, matching the one-identity-one-purpose principle already
applied to patient-deid. Local backend chosen deliberately over S3-backed
remote state: one operator, one machine, right now -- locking, multi-machine
access, and automatic version history all solve problems that don't exist
yet (CI/CD and collaboration are Phase 4 territory). State file lives at
%LOCALAPPDATA%\patient-deid-pipeline\terraform-state\, outside OneDrive's
sync scope, via an explicit backend "local" { path = ... } block -- the
default would otherwise write state into the same folder as the .tf source
files, which live inside the OneDrive-synced repo.

Provisioning identity kept separate from runtime identity: a new IAM user
(terraform-patient-deid, PowerUserAccess) dedicated purely to running
Terraform. Discovered necessary directly: patient-deid (scoped to
comprehendmedical:DetectPHI only) correctly failed with AccessDenied the
moment Terraform tried to use it to create an IAM role -- least privilege
working exactly as designed, against the wrong identity for the job.
PowerUserAccess itself excludes all iam:* actions by design (AWS's stated
purpose: prevents a PowerUser creating broader permissions for themselves),
so a narrow inline policy was added to terraform-patient-deid granting only
role-lifecycle actions plus PassRole, scoped by ARN to
patient-deid-pipeline-* -- manages every role this project creates,
structurally incapable of touching patient-deid, terraform-portfolio, or
anything unrelated.

Pipeline Lambda uses an IAM role, not a user -- the upgrade flagged as the
eventual target when patient-deid was first created. No long-lived
credentials: Lambda's service assumes the role at invocation, temporary
credentials expire on their own. Trust policy restricts assumption to
lambda.amazonaws.com exclusively.

input-notes KMS key: administrator/user split, not a single broad grant.
First draft used the common root-principal "kms:*" idiom -- caught before
applying that this would let terraform-patient-deid (via PowerUserAccess,
which does not exclude kms: actions) decrypt the key, defeating the
Lambda-only goal entirely. Replaced with two named statements:
terraform-patient-deid gets management actions only, kms:Decrypt
deliberately absent; pipeline_lambda's role gets exactly kms:Decrypt and
kms:DescribeKey, nothing else -- matches AWS's own "key administrators" vs
"key users" terminology precisely. Key rotation enabled (365-day default,
all prior generations retained automatically, nothing ever becomes
unreadable). Deletion window set to the maximum 30 days: full destruction
makes every note encrypted under this key permanently unreadable, and
there's no real cost to maximizing the window to notice and cancel an
accidental or malicious deletion first.

Accepted cost, worth stating rather than leaving implicit: without the
root-principal statement, this key has no generic account-level rescue
path if the two named grants above are ever misconfigured or accidentally
removed -- AWS's own default key policy includes that root statement
specifically to guard against this exact lockout scenario.
terraform-patient-deid's own management permissions are the sole route to
ever administering this key again; losing that identity's access would
mean losing the ability to manage the key at all, not just losing decrypt
capability. Judged acceptable here, since the alternative (broad decrypt
exposure through an overly-permissive identity) was the worse of the two
real risks -- but worth remembering if terraform-patient-deid's own
permissions are ever restructured later.

input-notes bucket: SSE-KMS referencing the key above,
aws_s3_bucket_public_access_block applied unconditionally regardless of
what any policy might otherwise permit. pipeline_lambda granted exactly
one permission here -- s3:GetObject, scoped with the object-level ARN
suffix (bucket-arn/*), not the bare bucket ARN, since S3 distinguishes
bucket-level and object-level actions by ARN shape and the wrong shape
silently matches nothing.

Known, accepted gap: this bucket's identity-paradox limitation, named when
first discussed -- the role that legitimately needs to decrypt and read it
is the same identity a breach would most likely compromise, since PHI
detection genuinely requires plaintext. No encryption scheme resolves
this; the planned mitigation is a short-retention lifecycle policy, not
yet implemented.


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
