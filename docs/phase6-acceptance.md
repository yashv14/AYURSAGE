# Phase 6 local doctor review and approval

**Verdict: independent software behavior implemented and tested; full clinical
acceptance is blocked. Phase 7 clinical report release is not ready.**

## Verified baseline and scope

The local checkout's origin is `https://github.com/yashv14/AYURSAGE.git`. Work started
on `phase5/frozen-inference` at `0aee06094caaba6dc39b7a3b5ccd11f4f8c9fc4a` and branches
from that commit as `phase6/local-doctor-review`. Phase 5 implementation commit
`507596c` is an ancestor. No local Phase 6 service existed at inspection. Remote
main subsequently inspected at `111d3b4` contains the merged Phase 5 work with the
same tree as the local baseline. No separate cloud Phase 6 implementation was assumed
or imported. Existing `.review-phase4` work is preserved.

The original model and source remain unchanged and the model remains ignored:

- Model SHA-256: `e0b60420eaf618e165822af5f69f8c437794c06ae0ca885e5d68df8e6a9a7c98`.
- Source SHA-256: `afc2fb4b771467e3a47045b1c3b76f9dc898716078fc47d8f930bfb5093088d3`.

Phase 6 consumes persisted Phase 5 inputs, successful runs, four original target
outputs, confidence when actually present, the `v17-deterministic` enrichment record
and model/source/adapter provenance. It neither invokes nor substitutes inference.
The four targets are Herbal Therapy Strategy, Lifestyle Recommendations,
Therapeutic Yoga Module and Follow-up Recommendation.

## Implemented behavior

An active, verified, assigned doctor can list pending cases, inspect the exact input
and newest successful prediction, inspect confidence/enrichment/provenance, and save
or retrieve review revisions. Review and approval routes reject patients and admins;
unassigned doctors receive existence-hiding 404 responses. Account, role, assignment,
verification, workflow and revision checks are repeated after acquiring the
consultation lock. No patient payloads or clinical reasons enter operational logs.

Every save inserts a new `DoctorReview` row with a monotonically increasing revision
within the consultation and new decision/notes records. Earlier content is never
updated; eligible prior review state becomes `SUPERSEDED`. Each revision captures
the complete reviewed source and its SHA-256. Decisions retain the original raw
category/confidence and enrichment, replacement text, reason, author via the parent
review, and persisted creation timestamps. Review reads expose doctor identity,
creation time and revision together with each decision set.

`ACCEPT` accepts the presented category and enrichment. `EDIT` and `OVERRIDE` preserve
distinct recorded actions and require nonempty doctor-authored replacement text and
a reason. Both replace that target's final patient-facing recommendation; no new
clinical interpretation of those action names is invented. Raw ML and enrichment
remain untouched. Care notes and optional prescription are separately stored fields.
The V17 `PENDING_DOCTOR_REVIEW` placeholder is rejected as doctor-authored content.

Partial drafts are allowed. All four distinct target decisions and explicitly
completed, nonblank care notes produce `COMPLETED`; this denotes structural draft
completeness, not approval or clinical readiness. Prescription remains optional.

The approval transaction rechecks the current review identity/revision, expected
consultation version, reviewer identity, current input and newest successful run,
full source checksum, complete decisions, original decision values, completed care
notes and complete evidenced enrichment structure. It locks the consultation, actor,
profile, source and review records before writing. MySQL run-range locks prevent
concurrent insertion into the selected input's run range. Future processing writers
must retain the consultation-first locking/optimistic-version discipline.

After policy verification, one transaction inserts an immutable approval snapshot
and checksum, binds input/run/review/model and policy provenance, records approver
and timestamp, changes consultation/review state to `APPROVED`, and appends the audit
event. A storage/audit failure rolls back all these writes. Snapshot version is 1
because amendment/version-supersession policy is not approved.

Approval idempotency keys are scoped to consultation, approving actor and approval
operation. A canonical checksum binds the entire request. Exact replay returns the
same approval (200); first approval returns 201. A changed payload with the same key
returns 409. Another key does not create a second approval. Authorization is still
checked on replay; a reassigned or deactivated doctor cannot use it to regain access.

Patients can retrieve only their approved patient projection, copied from the
immutable snapshot after checksum verification. It includes the signed final
recommendations, care notes and optional doctor prescription, plus approval/revision
identity. It excludes raw confidence, internal decision reasons, source snapshots,
model evidence and review history. Accepted recommendations are visible because the
doctor explicitly accepted them. Edited/overridden recommendations contain only the
doctor's replacement text. These responses have `Cache-Control: no-store`.

ORM guards prevent changes to approval, decision, prescription, source snapshots,
enrichment and original outputs. Direct SQL/bulk writes remain outside ORM guards;
database credentials must remain restricted. Patient reads independently verify the
approval checksum. No PDF/report endpoint or deployment work is included.

## Preserved evidence gates

`ML_ENABLED=false` remains mandatory. Submission still returns `503 ML_UNAVAILABLE`
when the existing Phase 5 evidence gate blocks inference. No test or API option enables
a production model path.

The existing [clinical governance](clinical-governance.md) contract requires a
clinic-approved required-engine/context/contraindication policy before approval.
That policy was not supplied. `require_approval_policy()` therefore returns
`503 CLINICAL_REVIEW_POLICY_UNAPPROVED` for otherwise eligible live approval attempts,
with no approval writes. There is no environment or request switch to waive it.
The structural engine checks do not claim clinical validation. Readiness exposes
`clinicalApproval: unavailable` and the safe blocker code independently of platform
and ML readiness.

The synthetic transaction tests mock only this unresolved policy boundary and use
explicitly synthetic persisted records. They test the approval implementation; they
do not establish that the policy or clinical workflow is approved. A separate test
asserts the unchanged default gate rejects approval and leaves storage untouched.

## Corrections and proposed amendments

Pre-approval corrections follow the existing authority/state contract: the assigned
doctor requests information with a reason, creating an immutable information-request
record and moving `PENDING_DOCTOR_REVIEW` to `NEEDS_INFORMATION`. Existing eligible
reviews become superseded. The owning patient can then use the existing input route
to create a new revision; the submitted original remains immutable. New successful
inference and a fresh review are required before approval. Live resubmission remains
blocked by Phase 5 evidence. Doctor-authored direct input correction is not enabled.

Approved consultations reject draft saves, input writes, information requests and
reassignment. Post-approval corrections are **not complete**. The following is a
concrete proposal for clinic review, not an implemented or approved policy:

1. Only the currently authorized treating doctor may open an amendment with a
   mandatory reason, linking a new consultation/revision to the prior approval.
   Decide separately whether patient requests may initiate a doctor triage queue.
2. Keep the existing approved snapshot available as the last approved version during
   re-review; label amendment status without exposing drafts or raw predictions.
   The clinic must decide whether any safety-related withdrawal requires a separate
   controlled action and what patients see during withdrawal.
3. Require fresh input provenance, inference and doctor review for changed model-bound
   input. Never edit the old approval or silently transfer old target decisions.
4. Supersede the patient-visible current approval only when the new approval commits
   atomically with explicit predecessor/successor links. Preserve access/audit history;
   decide historical patient visibility, notifications and retention before rollout.

## Migration and setup

The inspected history had one head, `0001_platform`. New revision
`0002_doctor_review` extends it without branches. New review revision/source columns,
original decision JSON and approval idempotency columns are nullable for legacy rows;
they are never backfilled with invented evidence. Legacy unversioned reviews and
legacy approval snapshots are not silently accepted by the new API. Reconciliation
requires independently reviewed historical evidence.

The new `information_requests` table stores clinical correction instructions separately
from operational audit metadata. Migration is explicit; startup does not migrate data.
After backup and normal review, apply `python -m alembic upgrade head` to the intended
database. Health requires `0002_doctor_review`. Downgrade remains restricted to freshly
owned disposable `ayursage_test_` schemas and removes new columns; it is not a recovery
procedure for user data. No existing user database was modified during this work.

## Verification and acceptance

Observed local results:

| Check | Result and scope |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/backend -q -p no:cacheprovider` | 67 passed; synthetic HTTP/service behavior, permission failures, immutable drafts/raw data, stale source checks, policy gate, idempotency, rollback and patient projection. |
| `.venv/Scripts/python.exe -m scripts.test_mysql` | 11 passed against disposable MySQL 8.4; migrations, schema equivalence, legacy preservation, HTTP approval, concurrent approval/draft writes, assignment/input/account changes during lock waits, and atomic rollback. |
| `npm run check` in `frontend` | Production build passed; no frontend source changes. |
| `.venv-v17-audit/Scripts/python.exe -I -c "import sys; sys.path.insert(0, '.'); from scripts.audit_v17 import audit; audit()"` | Real frozen-artifact candidate audit passed: three valid unapproved candidates matched the original complete output, 60 concurrent calls across eight threads were deterministic, nine invalid bundle variants were rejected. Original demo mismatch remains documented in Phase 5. |

Docker was initially stopped, then started for the disposable suite. Each temporary
project/schema was cleaned up. SQLite and mocked policy tests are not counted as
MySQL or real-model end-to-end evidence.

**The real-model consultation → inference → draft → approval → patient-view workflow
did not run and is not claimed to pass.** It remains blocked by missing original
training-runtime evidence, authorized reference outputs, reviewed input/collection
contracts and clinical enrichment policy. The tested runtime versions and evidence
placement checklist remain in [Phase 5 evidence](phase5-evidence.md).

Independent Phase 6 transaction and authorization criteria have local verification.
Full acceptance still requires the missing evidence/policy decisions, implementation
of the reviewed policy verifier, and a real-model end-to-end run through unchanged
production gates. Post-approval amendment policy is a separate unresolved decision.
Phase 7 may be designed against the immutable snapshot contract, but clinical PDF
release must not be enabled or represented as ready.
