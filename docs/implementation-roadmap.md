# AYUR-SAGE implementation roadmap

This roadmap turns the target architecture into evidence gates. A phase is complete only when its listed evidence exists; later work must not bypass the frozen V17 boundary.

## Phase 1 — Repository foundation (this change)

- Record architecture, safety boundary, and contributor instructions.
- Create Flask application factory and process-liveness endpoint.
- Create React/Vite shell with an honest “ML unavailable” status.
- Establish test, deployment, local configuration, and CI structure.
- Keep clinical prediction, database workflows, authentication, and model dependencies absent.

**Exit evidence:** backend tests pass, frontend production build succeeds, and CI runs both.

## Phase 2 — V17 evidence and design gates

- Obtain the original artifact, `predict_single()` source/helpers, dependency evidence, and provenance.
- Calculate and approve a trusted checksum without modifying the artifact.
- Statically inspect import behavior before execution; training must not run on import.
- Obtain authorized synthetic reference inputs/outputs and audit engine boundaries.
- Confirm exact feature order, categories, units, missing-value rules, target identifiers, labels, and return structure.
- Finalize ER diagram, API schemas, state diagrams, ownership/assignment matrix, provenance rules, retention, onboarding, Nadi/Prakriti/Disease ownership, and contraindication policy.

**Exit evidence:** reviewed contract and reference parity plan. No retraining or guessed dependencies.

## Phase 3 — Reproducible platform and persistence

- Add pinned application dependencies without conflating them with unknown model dependencies.
- Add SQLAlchemy, Alembic, and local/integration MySQL.
- Define versioned entities, constraints, UTC timestamps, and safe migration workflow.
- Add structured errors, request identifiers, configuration validation, readiness, and auditing foundation.

**Exit evidence:** schema migration round-trip in MySQL and healthy application startup.

## Phase 4 — Identity, authorization, and consultations

- Implement patient registration and controlled privileged-account bootstrap/onboarding.
- Implement password hashing, short access JWTs, rotating refresh sessions, logout/revocation, and origin/CSRF controls.
- Enforce active account, role, ownership, assignment, and workflow state in backend services.
- Implement patient profiles, consultation drafts, versioned inputs, assignment, state transitions, concurrency, and audit events.

**Exit evidence:** ownership, unassigned-doctor, public-role-escalation, stale-version, and session-security tests.

## Phase 5 — Frozen inference and deterministic enrichment

- Build a narrow adapter around the supplied callable; do not duplicate preprocessing.
- Verify checksum and reference inference before ML readiness.
- Persist input/model provenance and four raw target outputs atomically.
- Wrap each supplied reasoning/lifestyle/yoga engine once, version it, and represent failure explicitly.
- Add bounded synchronous processing only after measuring runtime.

**Exit evidence:** parity tests match authorized frozen cases exactly and failures cannot produce guessed output.

## Phase 6 — Human review and approval

- Implement per-target accept/edit/override and mandatory reasons for changes.
- Preserve raw output while storing revised content separately.
- Add completed care notes, optional prescription, assigned-doctor approval, immutable snapshots, idempotency, and optimistic concurrency.

**Exit evidence:** no unauthorized, incomplete, stale, or duplicate approval can succeed.

## Phase 7 — Reports and private storage

- Render ReportLab PDFs only from approval snapshots.
- Add private model/report/attachment adapters, controlled keys, checksums, authorization, lifecycle state, retries, and reconciliation.
- Constrain attachments until a verified scan/quarantine policy exists.

**Exit evidence:** report content matches its approval and failed storage operations recover without duplicate release.

## Phase 8 — Role-based UI and end-to-end milestone

- Implement public/auth, patient, assigned-doctor, and operational-admin screens.
- Clearly label patient input, raw model result, enrichment, doctor modification, and approval.
- Cover loading, empty, invalid, unauthorized, expired, failed-inference, and failed-report states accessibly.

**Exit evidence:** one synthetic consultation moves through authorized submission, frozen inference, review, approval, and authorized report download.

## Phase 9 — Azure release evidence

- Build a pinned Gunicorn container and measured worker/resource configuration.
- Provision reviewed Azure resources, managed identities, secrets, restricted networking, monitoring, and controlled migrations.
- Run smoke, load, failure, backup, and restore exercises.
- Record commit, image digest, migration revision, model checksum, and engine versions.

**Exit evidence:** deployed behavior and documentation agree; recovery objectives and operational ownership are recorded.
