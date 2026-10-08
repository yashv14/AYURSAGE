# Phase 7 approved-snapshot reports — 8 October 2026

**Software implemented for synthetic verification; live clinical release is not ready.**
The verified origin is `https://github.com/yashv14/AYURSAGE.git`. Remote updates were
fetched; starting HEAD and remote main were both
`c88598eeae576ca20ee1264215ab61514dad927c`, the merged PR #7 baseline. Work is on
`phase7/approved-reports`. The supplied uncommitted `docs/phase6-review.md` was found
and preserved as local supplemental evidence; it is not assumed to be committed or
available in other sessions. Committed Phase 5/6 acceptance records govern this phase.

## Content and eligibility

ReportLab renders only the immutable, checksum-verified Phase 6 `patientView`, with
approval ID/version/UTC date and backend-controlled report ID/template version.
It does not query clinical inputs, prediction outputs, enrichment tables, review
decisions or prescription drafts to populate the PDF; it does not invoke inference.
For ACCEPT, the already approved patient projection includes its approved category
and deterministic annotation/details. For EDIT/OVERRIDE it includes only the
doctor-authored replacement. Internal change reasons, raw confidence, source snapshots,
patient input and restricted evidence are excluded. No doctor signature, qualification,
credential, clinical claim or diagnosis is fabricated. Empty optional prescription
is omitted; care notes and all four approved targets are required.

The renderer allowlists the exact patient projection and per-target public fields;
unknown fields or malformed text cause a safe generation failure. Text is XML-escaped
before ReportLab Paragraph processing, including literal HTML-like user text.
Long paragraphs/words wrap across A4 pages, headings stay with following content,
page footers identify each page. Report text is bounded to 16,000 characters per
value, 160,000 total characters and 16 MiB PDF bytes. Unsupported text fails rather
than silently replacing approved content. No mutable report content endpoint exists.

Template/report version is `approved-patient-v1`. DejaVu Sans is embedded from
`REPORT_FONT_PATH` (default `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`). Template
v1 pins font SHA-256
`57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e`.
Install the matching licensed font through the OS package manager (`fonts-dejavu-core`
on Ubuntu); do not commit font binaries. A different font/version requires a new
reviewed template. Covered LTR Latin, Greek, Cyrillic and font-covered symbols are
supported; missing glyphs, bidi/complex-script letters (including Devanagari) and
hidden format/control characters are rejected. Shaping/Indic support is future
template work, not claimed here. ReportLab invariant output and fixed projection,
report identity, template and font give reproducible retry bytes. Runtime dependency
pins are application/report pins, not evidence of V17 training dependencies.

Synthetic test configuration marks every PDF page with `SYNTHETIC TEST DATA`; sample
PDFs also say `NOT FOR CLINICAL USE`. No request field can turn on test mode or
authorize an approval. Normal approvals still require unchanged Phase 5/6 gates.

## Configuration and migration

Install `backend/requirements-dev.txt` in the existing Python environment. ReportLab,
Azure Blob/Identity SDKs and transitive dependencies are constrained; pypdf is used
only for development/test text verification. No model packages were added.

Configure local development:

```bash
export REPORT_STORAGE_BACKEND=local
export REPORT_LOCAL_ROOT=/workspace/ayursage-private-reports
export REPORT_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
```

The local root must be an operator-owned private directory, outside the repository,
static/frontend/public paths, with no group/other permissions. The adapter creates
new roots/subdirectories mode 0700 and files mode 0600, refuses symlink file entries
and nonopaque keys, and publishes files atomically with create-only hard links.
Use a local filesystem supporting these semantics; no static route serves it.
Parent directories and filesystem administrators are trusted. Do not share this
directory with untrusted users/processes or map it into a web server document root.
The service account must be able to read/write it. Configuration is server-controlled.

For an **existing** Azure setup (no resources created in this phase):

```bash
export REPORT_STORAGE_BACKEND=azure
export AZURE_REPORT_ACCOUNT_URL=https://ACCOUNT.blob.core.windows.net
export AZURE_REPORT_CONTAINER=PRIVATE-CONTAINER
```

Azure uses DefaultAzureCredential, preferably the service's managed identity and
least-privilege data-plane rights to the existing private report container.
HTTPS account endpoints only; no SAS query or credentials in URLs. The adapter
checks container privacy on reads/writes, uploads create-only, limits reads to
16 MiB, and never returns storage URLs. Do not print tokens, connection strings,
SDK exception details or content. SDK HTTP logging is disabled. Actual identity,
network, RBAC, private-container and Azure failure verification remain deployment
prerequisites; SDK-double tests are not proof that a hosted container is private.
No Azure credentials/configuration were supplied or needed for independent tests.

Apply additive migration `0003_approved_reports` after normal migration review and
backup using the intended `DATABASE_URL`:

```bash
python -m alembic upgrade head
python -m alembic current
python -m alembic check
```

This phase applied migrations only in disposable test databases, not a user database.
The migration adds nullable snapshot/template provenance and generation-token/lease
fields to existing reports; legacy rows are preserved without fabricated provenance
and cannot be released by the new API. Existing approval/report uniqueness and file
metadata remain in place. Readiness now expects `0003_approved_reports`. Downgrade
is still restricted to explicitly allowed disposable `ayursage_test_` schemas.
No startup schema creation, schema stamping, amendment, supersession or retention
automation is introduced. ORM guards make READY reports, report identity and file
metadata immutable; restricted direct SQL remains outside ORM guards.

## Identity, retries and cross-system recovery

`(approval_id, report_version)` uniqueness is the API contract's database-enforced
idempotency equivalent; retries from either authorized actor reuse one report ID.
Report identity binds the exact approval, immutable snapshot checksum and template
version. File metadata binds opaque object key, content type, byte size and SHA-256.
Keys are random `reports/{32 hex characters}.pdf` without patient details. A previous
approval's object is never overwritten. Only the known v1 template is accepted;
client version strings cannot manufacture new versions or supersession.

Generation claims consultation/actor/approval/report locks, records GENERATING with
a random token and five-minute lease plus an audit event, then commits **before**
PDF rendering/storage calls. Concurrent requests see 409. On upload/readback success,
the service reacquires locks, rechecks current account/role/ownership/assignment,
approval integrity and the generation token, and atomically records file metadata,
READY and its audit event. Late workers with a replaced token cannot publish.
Downloads read bounded bytes and verify them before backend streaming, then recheck
authorization after storage IO. No DB transaction is held across storage IO.

| Failure | Recorded behavior / recovery |
|---|---|
| Rendering/unsupported glyph/upload/readback failure | Best-effort FAILED with safe failure code, no released file metadata. Authorized POST retries the same identity; content/unsupported-script issues require a reviewed template, not edits to immutable approval. |
| Process death or final DB/audit failure after upload | Report remains GENERATING with known object key; file stays private and unreleased. After lease expiry an authorized POST regenerates identical bytes, verifies the existing create-only object, and completes metadata. No second report or fake READY state. |
| Ambiguous commit result | Re-read through the authorized API. READY must pass snapshot/file checks; otherwise reconcile the recorded lease/key. Never delete an object in a catch block because a commit might have succeeded. |
| Actor loses authority during IO | Publication/download denied on recheck; uploaded object remains private at its recorded key for authorized lease recovery. No lost doctor/patient permission is restored by replay. |
| Existing object differs or released file is absent/tampered | 503; no overwrite and no READY repair by request. Operator investigates restore against recorded checksum. Do not rewrite approval or READY metadata. |
| Interrupted local temporary upload | `.upload-*` private temporary may remain after a hard crash. Reconcile known report keys first. Operator inventory may identify temp/unreferenced objects; deletion requires the still-unapproved retention/operator policy. No destructive automated cleanup. |

Every upload follows a committed report claim, so a file left after a database failure
has a tracked reconciliation identity. Orphan objects are not publicly exposed and
are not automatically destroyed. If storage backend/root changes, migrate private
objects preserving keys/checksums under operator review; historical data is not
automatically moved. Report failures do not revoke or mutate approvals.

Metadata and download APIs are documented in [API contract](api-contract.md#phase-7-report-transport).
Generation, READY, FAILED and successful download events record IDs/checksums and
request identity without clinical content, paths or credentials. No model/attachment
storage migration is attempted; attachments remain unavailable pending scan/quarantine
policy. Phase 8 UI and Phase 9 provisioning/deployment are out of scope.

## Verification and release limits

Use only isolated synthetic approvals; tests temporarily mock the unresolved clinical
policy inside the synthetic fixture and restore the unchanged gate immediately.
Never run fixtures against a user database or seed approvals with an operator command.

```bash
python -m pytest tests/backend -q
python -m scripts.test_mysql
(cd frontend && npm run check)
./scripts/verify-foundation.sh
git diff --check
python -m scripts.sample_report_pdfs --output /tmp/ayursage-phase7-review
/usr/bin/pdftoppm -r 100 -png /tmp/ayursage-phase7-review/short-no-prescription.pdf /tmp/ayursage-phase7-review/short
/usr/bin/pdftoppm -r 100 -png /tmp/ayursage-phase7-review/long-with-prescription.pdf /tmp/ayursage-phase7-review/long
```

The sample script uses only marked synthetic dictionaries and has no DB/model/storage
access. It verifies extracted text against every approved patient-projection value
while removing layout whitespace/known page footers. Two PDFs were generated: one
page without prescription, four pages with long care notes, a 300-character token,
literal XML/HTML-like text, Latin accents, Greek and Cyrillic. All five pages were
visually inspected using native Poppler rasterization: no clipping, missing glyphs,
overlap or incorrect content; page breaks and optional prescription were correct.
Generated artifacts remain outside Git at `/tmp/ayursage-phase7-review`.

Tests cover exact snapshot rendering despite changed draft/raw records, pending/draft
rejection, unchanged clinical gate, patient/doctor/admin isolation, inactive/unverified
actors, snapshot/file tampering and missing objects, duplicate identity, immutable
metadata, upload/DB failures and lease recovery, public-path/traversal/symlink refusal,
Unicode/escaping/long content, Azure SDK-double privacy/conflict failures, MySQL
concurrent claims, expired-lease fencing, authority revocation during IO, legacy
upgrade preservation and migration drift/round-trip compatibility.

Observed final validation: **88 backend tests passed**; **16 disposable MySQL
integration tests passed** (including five new Phase 7 migration/concurrency/recovery
checks); frontend production build, foundation safety guard, dependency consistency,
document-link and whitespace checks passed. Both sample PDFs passed projection text
verification and all five pages passed visual inspection. The MySQL wrapper removed
its unique temporary project; no user database or persistent development volume was
used for synthetic approvals.

Actual Azure connectivity/RBAC and real-model clinical end-to-end workflow were not
run. Original model is absent from this checkout, and original runtime evidence,
authorized references, approved input/collection/enrichment/operations policies and
the real enabled runtime/policy verifier remain outstanding. `ML_ENABLED=false`
and `CLINICAL_REVIEW_POLICY_UNAPPROVED` remain unchanged. Retention/amendment/clinical
release decisions are not invented. Software verification does not establish clinical
validity, live release readiness or completion of the Phase 5/6 acceptance gates.
