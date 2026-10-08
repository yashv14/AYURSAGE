# Phase 3 persistence implementation

The application factory initializes Flask-SQLAlchemy without connecting, creating
tables, or loading ML. DATABASE_URL is required and uses `mysql+pymysql`; SQLite is
allowed only in explicitly configured unit tests. SQLAlchemy sessions are scoped
to the application context. MySQL connections use UTC, bounded connection/read/write
timeouts, pool recycling and connection checks.

## Physical schema decisions

The initial frozen Alembic revision is `0001_platform`. It defines all 18 entities
from the logical model without clinical categories, target identifiers, model rows,
credentials, or role/account seeds. IDs are UUID strings (`VARCHAR(36)`). UTC instants
use `DATETIME(6)` and return timezone-aware UTC through the ORM; naive timestamp
values are rejected. Mutable aggregates use optimistic integer `row_version` fields
and `updated_at`; all entities have `created_at`.

Application storage limits are 254 characters for normalized email, 512 for password
hashes and object keys, 64 for schema/engine/report versions and checksums, and 128
for opaque target identifiers and idempotency keys. These are storage capacities,
not claims about V17 vocabularies. Clinical inputs, original outputs, enrichment,
provenance and approval snapshots use separate JSON columns without invented defaults.
Any supplied V17 value exceeding a storage capacity requires reviewed schema evolution
rather than truncation or relabeling.

Unique constraints cover patient/doctor profiles, input revisions, target outputs,
engine versions, review decisions, approval versions, report versions, refresh hashes
and object identities. Foreign keys restrict deletion; no clinical cascade deletion
is configured. Composite keys enforce that the current revision belongs to its
consultation, reviews reference the input's consultation and the run's input, and
approvals reference the review's consultation. The cyclic current-input foreign key
is added after both tables exist. Indexes support ownership, assignment, workflow
status, input/run lookups, session expiry and audit resource/request lookups.

Checks enforce reviewed application states, positive revisions, edit/override reasons
and content, completed care notes, nonnegative file/retry sizes, and report file
presence for READY. MySQL 8.4 is required for enforced CHECK constraints; a binary
UTF-8 collation preserves opaque identifier case. Email normalization belongs to the
Phase 4 identity service before writes.

## Integrity boundaries and deferred behavior

ORM flush guards reject changes to approvals, audit records and role records,
submitted input modifications, persisted raw-output changes, and clinical-history
deletion. They do not govern direct SQL/bulk updates or in-place JSON mutations;
future services must replace JSON values, use controlled transactions and restrict
database credentials. This phase does not expose clinical write endpoints.

Account-role/profile consistency, active doctor verification/assignment, authorization,
state transitions, idempotent application operations, atomic evidenced target-set
persistence, and approval completeness remain service requirements for Phases 4–6.
They are not claimed to be satisfied by foreign keys. No target count, class label,
probability, prescription, contraindication rule or inference callable is invented.
`ML_ENABLED` accepts only false; model-version rows cannot enable inference.

Retention, anonymization, attachments, amendments and privileged onboarding policy
remain governed by [clinical governance](clinical-governance.md). No deletion route,
expiry job or amendment flow is enabled. Technical database errors return safe JSON;
integrity conflicts return 409, operational database failures 503, and unexpected
errors 500 without SQL, credentials or exception text. Request IDs are server generated.

## Evidence and operation

Phase 6 adds `0002_doctor_review` on top of `0001_platform`. Review revisions are new
rows with source snapshots/checksums; decisions and notes are immutable per revision.
Approval adds actor-scoped idempotency and request checksums. New columns are nullable
for unchanged legacy records, which are not silently promoted to verified reviews.
The new information-request table separates clinical instructions from safe audit
metadata. See [Phase 6 acceptance](phase6-acceptance.md) for transaction ordering,
concurrency evidence and policy limitations. Platform readiness now requires this
single new Alembic head.

[Local setup](local-setup.md) documents migration and disposable-test commands.
The integration suite uses real MySQL and compares live schema to ORM metadata,
tests constraints, timezone conversion and stale writes, and performs an
upgrade/downgrade/upgrade round-trip. SQLite unit tests are separate evidence.
Never run the integration account against a user-data server.

Integration follows the official [Flask-SQLAlchemy factory guidance](https://flask-sqlalchemy.palletsprojects.com/en/stable/quickstart/),
[Alembic migration environment guidance](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
and [SQLAlchemy constraint guidance](https://docs.sqlalchemy.org/en/20/core/constraints.html).
