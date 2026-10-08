# Local setup

## Prerequisites

- Python 3.12 or newer
- Node.js 22 or newer and npm

Docker Desktop (Linux containers) is required for the supplied local MySQL setup and
isolated integration checks. A model is neither required nor enabled.

## Backend

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
```

On Windows PowerShell, activate with `.venv/Scripts/Activate.ps1`. Application and
transitive dependencies are pinned in `backend/constraints.txt`; these pins provide
no evidence about the unknown V17 runtime. Gunicorn is for Linux deployment only.

## Local MySQL and migrations

Copy `.env.example` to an ignored `.env` and replace password placeholders locally.
Compose reads `.env`; the Flask factory reads process environment variables. Export
`DATABASE_URL` separately before Flask or Alembic commands (or use VS Code's ignored
local environment configuration). Percent-encode reserved password characters.
Do not print or commit the resulting connection string.

Start the named development project, preserving its persistent volume:

```bash
docker compose -p ayursage-dev up -d --wait
python -m alembic upgrade head
python -m alembic current
python -m alembic check
flask --app backend.app:create_app run --port 5000
```

Set `DATABASE_URL` to the example's MySQL driver/host/port/database using your local
password: in PowerShell use `$env:DATABASE_URL = '<your local URL>'`; in Bash use
`export DATABASE_URL='<your local URL>'`. No schema is created on application import
or startup. The initial migration refuses a nonempty unversioned database. Never
use `stamp` to bypass that guard. MySQL DDL is not transactionally reversible: inspect
a partial migration failure and restore from an approved backup rather than retrying
blindly. Review generated migrations and back up real data before future upgrades.

`docker compose -p ayursage-dev stop` preserves development data. Do not run volume
removal, schema reset, or downgrade against a development database containing data.
Downgrade is restricted to explicitly enabled disposable `ayursage_test_` schemas.

Check process liveness at <http://localhost:5000/api/v1/health/live>.

Run tests from the repository root:

```bash
python -m pytest
```

Without a test server, MySQL integration tests explicitly skip. Unit-test success
does not establish MySQL migration evidence. Run the complete disposable check:

```bash
python -m scripts.test_mysql
```

This creates a unique Docker project, generates temporary credentials, publishes a
loopback-only random port, and uses tmpfs storage. Tests create a fresh random schema,
apply the migration, check constraints and UTC/version behavior, verify no schema
drift, downgrade, then upgrade again. Cleanup drops only the schema whose creation
succeeded in this run and removes only its unique test project. No existing database
URL is reused. Docker must be running; failures are reported as failures, not skips.

For a separately provisioned **disposable test server**, set `MYSQL_TEST_SERVER_URL`
to a MySQL URL without a database and `REQUIRE_MYSQL_TESTS=1`, then run
`python -m pytest tests/integration`. The test account needs CREATE/DROP DATABASE on
that disposable server. Never provide production credentials. CI runs the Docker
wrapper and fails if integration checks cannot execute.

Readiness at `/api/v1/health/ready` returns `200` only when the database is reachable
and its Alembic revision is `0003_approved_reports`; otherwise it returns `503`.
The JSON always reports `ml: unavailable`. This is platform readiness, not clinical
readiness. Liveness keeps its existing `{status: "ok"}` response. Every response
includes `X-Request-ID`; safe errors include the same ID in their JSON body.

## Frontend

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Build the production assets with `npm run build`.
The Vite development server proxies `/api` to the local Flask backend.
See [Phase 8 frontend](phase8-frontend.md) for role workflows, session configuration
and disposable browser integration checks.

## Foundation safety check

Run the repository guard that rejects tracked model binaries, private key files,
non-example environment files, and attempts to recreate `predict_single()`:

```bash
./scripts/verify-foundation.sh
```

The supplied original source and reproducible inference-only extraction are the
only allowed callable locations. The guard verifies extraction syntax-tree equality against
the checksum-bound source without importing ML packages or executing training.

## Configuration

Copy `.env.example` to `.env` for local overrides. Never commit `.env`. `ML_ENABLED` remains `false`; enabling it does not provide an implementation, and no placeholder prediction behavior exists.

## Phase 4 identity configuration and bootstrap

Set a unique `JWT_SECRET` of at least 32 random characters. Access JWTs default to a
15-minute lifetime. Refresh credentials are opaque, rotating, HttpOnly cookies with
`SameSite=Strict`; production deployments must keep `COOKIE_SECURE=true`. Refresh and
logout requests must come from an exact `ALLOWED_ORIGINS` entry and send the readable
`csrf_token` cookie value in `X-CSRF-Token`. Access tokens are sent only as Bearer
credentials and are not stored in cookies.

After migration, authorize the one-time administrator bootstrap with a random
`ADMIN_BOOTSTRAP_TOKEN` of at least 32 characters, run the command below, then remove
the token from the environment. The command refuses to run once any administrator
exists and writes an audit event. It also creates the reviewed role rows if absent.

```bash
flask --app backend.app:create_app bootstrap-admin --email admin@example.test --password '<strong unique password>' --token "$ADMIN_BOOTSTRAP_TOKEN"
```

Only an authenticated administrator can onboard a verified doctor through
`POST /api/v1/admin/doctors` or assign one through the assignment endpoint. Public
registration always creates a patient and rejects any client-supplied role.

Phase 4 deliberately provides no inference, prediction viewing, clinical review,
approval, treatment, attachment, or report route. Patient clinical input is stored as
an opaque versioned object because its V17 schema remains unverified. Doctor-authored
input correction, doctor submission on behalf of a patient, post-submission
cancellation, temporary unassignment policy, and all later clinical transitions remain
unresolved and unavailable rather than being inferred here.

## Phase 5 local artifact and audit

See [Phase 5 evidence and setup](phase5-evidence.md) for ignored artifact placement,
checksum verification, the separate opt-in real-model audit, tested package versions
and required evidence filenames. The disabled factory checks artifact integrity
without deserialization. `ML_ENABLED=false` remains mandatory; training environment
evidence and approved clinical contracts/references are not replaced by audit success.

## Phase 6 review schema and checks

Apply the additive `0002_doctor_review` migration explicitly after normal backup and
review: `python -m alembic upgrade head`. It preserves old records and leaves their
new provenance fields null. It does not fabricate review revisions or historical
approval evidence. No migration runs during application startup.

Run backend checks with `python -m pytest tests/backend`; run MySQL migration,
transaction and concurrency checks with `python -m scripts.test_mysql`. The latter
starts a fresh random Docker project with disposable storage and cleans it up. It
never reuses `DATABASE_URL` as an integration-test database. Docker Desktop must be
running. Synthetic approval tests mock the missing clinical-policy verifier; that
does not enable live approval or prove real-model end-to-end readiness.

Review routes, payloads, policy blockers and amendment proposal are described in
[Phase 6 acceptance](phase6-acceptance.md) and [the API contract](api-contract.md).
Readiness includes `clinicalApproval: unavailable` and the missing-policy blocker.
There is no approval-enabling environment flag. Approved patient views return only
the immutable approved content projection. Phase 7 adds private PDF report software;
see [report configuration and acceptance](phase7-reports.md). Live clinical release
remains blocked by the existing Phase 5/6 evidence gates.
