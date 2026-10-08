# Phase 8 role frontend — 8 October 2026

UI software is implemented for the existing API contracts and synthetic browser
verification. Live clinical release and Phase 9 deployment are not ready.

## Baseline and preservation

Verified origin: `https://github.com/yashv14/AYURSAGE.git`. Remote updates were fetched.
`phase8/role-ui` starts at `77b71cd3cc7b3abe4ee034c75ff76f7fe855071b`, merged PR #8,
which includes Phase 7 `92e764b0fb12cd05a4c61108f630bec78778b5d0` and its CI font fix
`0902509ce3a9563a46caed78824264d070c80137`.
The Phase 6 merged PR #7 baseline `c88598eeae576ca20ee1264215ab61514dad927c` is an ancestor.
The pre-existing untracked `docs/phase6-review.md` was found and preserved without
including it in Phase 8 commits. Committed [Phase 5 evidence](phase5-evidence.md),
[Phase 6 acceptance](phase6-acceptance.md), [Phase 7 reports](phase7-reports.md),
[API](api-contract.md), [authorization](authorization-matrix.md), and
[governance](clinical-governance.md) contracts remain authoritative.
Original model/source files and all clinical gates remain unchanged.

## Routes and workflows

The React/Vite app uses hash routes, so navigation does not require an additional
server history fallback. Anonymous users see sign-in and patient registration.
Account roles come exclusively from authenticated backend responses.

| Route | Role | Behavior |
| --- | --- | --- |
| `#/` | Patient | Own recent consultations; create a draft |
| `#/` | Doctor | Assigned cases and paginated pending queue |
| `#/consultations/:id` | Patient | Supported input drafts/revisions, information requests, approved care and PDF |
| `#/consultations/:id` | Doctor | Assigned source inspection, review revisions, information requests, exact saved-review approval and approved PDF |
| `#/admin` | Admin | Existing verified-doctor onboarding and consultation assignment operations |

Backend authorization decides every request. Role routing never grants authority.
Unavailable, empty, loading, validation, permission, stale-version, session and
network states have explicit messages; safe request IDs support troubleshooting.
Unsaved work prompts before navigation, reload or logout, and native unload warns
when appropriate. A stale save retains typed content until the user explicitly
reloads/discards it. Admin forms track unsaved changes independently.

Patient collection categories and numeric bounds are unapproved. The screen lists
only the twelve evidenced field names and supports the existing opaque JSON draft
and provenance contract with a clinic/project-provided schema version. It does not
invent a clinical questionnaire, permitted values, numeric ranges or validation
policy. Saving creates a new input revision; it does not authorize inference.
Submission is disabled while readiness says ML unavailable. No raw prediction or
unapproved enrichment is exposed to patients as approved care.

Doctors inspect actual persisted input/provenance, raw categories, confidence when
supplied and deterministic enrichment separately from their own changes. Decisions
start undecided. ACCEPT preserves original category/enrichment; EDIT and OVERRIDE
require separate replacement text and internal reason. Each save uses expected
consultation/review revisions and the actual input/run identity. Saved history is
read-only; reopening restores the latest revision. Completed care notes are explicit;
prescription remains optional. Approval confirmation identifies the exact saved
review ID/revision and record version, with a stable idempotency key for retries of
that same request. Missing clinical policy still returns the real backend 503.

Approved screens consume only the immutable patient projection returned by the
approval API. Internal replacement reasons, raw confidence and source records are
not added to that view. The PDF action generates/reuses a report for that approval,
then downloads authenticated backend-streamed bytes. No public URL or object path
is exposed. Busy controls prevent repeated clicks. Backend snapshot/file integrity,
ownership/assignment and idempotency remain authoritative.

Admin functionality is limited to the actual POST onboarding/assignment APIs.
There is no invented account directory, PATCH verification API, clinical browsing
or approval permission. Assignment requires known IDs and expected record version
from an authorized operational workflow; obtaining these IDs remains an operational
constraint of the existing API, not an invented frontend privilege.

## Sessions and necessary backend correction

Access tokens stay in module memory; neither credentials nor clinical data are put
in localStorage/sessionStorage, browser logs or URLs. Account-specific component
state is remounted on user changes. An epoch check rejects stale in-flight responses
after session changes. Protected 401 responses trigger one single-flight refresh
and one retry; failed recovery clears the workspace. Refresh uses the established
HttpOnly rotating cookie, Strict SameSite, allowed Origin and double-submit CSRF.

The necessary backend fix moves only the readable `csrf_token` to cookie path `/`,
so the app root can read it. `refresh_token` remains HttpOnly at `/api/v1/auth`;
Secure behavior and Origin/proof verification are unchanged. Login/refresh removes
the legacy narrow CSRF cookie; logout clears both CSRF paths and revokes the existing
session chain. A regression checks these properties. Failed network logout clears
local state and offers server sign-out retry; server revocation cannot be claimed
until that request succeeds. Browser refresh after a failed offline logout may
still restore an unrevoked server session.

## Setup and configuration

Use [local backend/MySQL setup](local-setup.md) and the existing Phase 7 private
storage and checksum-pinned font configuration. No schema migration is added.

```bash
cd frontend
npm ci
npm run dev
npm run check
```

The development Vite server proxies `/api` to `http://127.0.0.1:5000` by default.
Override the backend target with `BACKEND_PROXY_TARGET` only in the development
server environment. Browser API paths remain same-origin `/api/v1`; no bearer
credential is sent to a frontend-configured third-party origin. Match Flask
`ALLOWED_ORIGINS` to the browser's actual origin. HTTP development requires
`COOKIE_SECURE=false`; HTTPS must retain Secure cookies. No credentials belong
in any `VITE_*` variable. Optional `VITE_TERMS_VERSION` can prefill a real
clinic-provided terms version; it does not approve, publish or fabricate terms.
The registration screen otherwise asks for that supplied version explicitly.
Production proxy/HTTPS/domain provisioning belongs to Phase 9 and is not implemented.

## Reproducible verification

From the repository root:

```bash
.venv/bin/python -m pytest tests/backend
.venv/bin/python -m scripts.test_mysql
./scripts/verify-foundation.sh
```

From `frontend`, with the virtual environment's Python on PATH:

```bash
npm ci
npx playwright install --with-deps chromium
npm run check
PYTHON="$(cd .. && pwd)/.venv/bin/python" npm run test:e2e
```

The test server executes from the repository root; the absolute Python path above
works for both frontend runner and backend server. For installed Chromium set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`.
For screenshots set `SCREENSHOT_DIR` to a directory outside the checkout. Tests use
ports 5058/5178 and fail rather than reusing another server on those ports.

`tests/browser_server.py` is a standalone test-only launcher, never imported by the
application. It creates a temporary SQLite database/private report store, random
short-lived fixture credentials, and persisted synthetic source records. It never
loads/enables/substitutes V17. A unittest patch allows approval solely for one
explicit synthetic input, and a separate isolated fixture prepares an approved
snapshot. Other cases use the original unavailable policy. No API/config switch
or production seeding command enables this behavior. The fixture file is outside
the checkout, mode 0600; normal runner shutdown removes it and temporary storage.

The seven backend browser journeys cover patient drafts/corrections, doctor saves
and restoration, EDIT separation, exact approval and PDF under the synthetic policy
fixture, real default approval rejection, cross-patient data/report and other-doctor
rejection, reassignment, stale records/focus, information requests, registration,
refresh rotation/restoration, expiry clearing, actual admin onboarding/assignment,
mobile overflow, labels, skip-link/keyboard navigation and long Unicode/literal text.
Two separately named UI fault-injection tests mock network/403/report-503 responses
and verify safe errors/retry, busy duplicate-click protection and reuse of the same
backend report ID. These are UI recovery evidence, not storage-failure or Azure evidence.
Backend report tests separately cover storage/database failures and tampering.

Local results: 91 backend tests passed; 16 disposable MySQL tests passed, including
migrations to actual head, schema drift and report concurrency/recovery; nine
Chromium browser journeys passed; frontend production build and foundation guard
passed. Browser PDF text was extracted with pypdf and checked for synthetic marking,
exact literal/Unicode replacement text and absence of its internal reason; private
headers and cross-patient report denial were checked. No real-model test ran.
CI now adds a browser job with the verified font helper and locked npm install.
Local Chromium evidence does not claim hosted CI execution or all-browser coverage.

## Visual evidence and remaining release blockers

Full-page synthetic screenshots were captured at desktop 1440×1000 and mobile
390×844, outside the repository: auth, patient list, patient draft, doctor review,
approved patient projection and operational administration. Labels, focus controls,
long text, Unicode and mobile wrapping were inspected. Screenshot artifacts are
local review evidence and are not committed with clinical reports or credentials.

The unresolved release requirements are unchanged: trusted V17 runtime/artifact and
reference execution evidence; approved clinical input categories/bounds/verification;
clinic required-engine/context/contraindication review policy; policy decisions for
post-approval amendments/retention; actual Azure identity/storage verification and
Phase 9 deployment/security operations. Use the committed acceptance records for
the exact required evidence and owner/clinical decisions. No live terms document
or operational administrator bootstrap is invented. The app continues to block
clinical prediction and live approval. UI completion is not full Phase 5–8 clinical
acceptance; the real-model end-to-end workflow must pass its required gates first.

## Attribution

GitHub associates existing commit `02f3c89f35f934442871a6995b2b5a4cca6776af`
with `krishnasidanale-bit`; its Git author/committer email is `krishnasidanale@gmail.com`.
This is the verified attribution source, rather than unrelated local Git configuration.
Use per-commit Shreya Sidanale identity for this phase's frontend/integration work;
the necessary backend cookie fix is separate under the requested Yash identity.
No existing history, global/system Git configuration, account or credential is changed.
No co-author is fabricated.
