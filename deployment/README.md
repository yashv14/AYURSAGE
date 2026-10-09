# Phase 9 release preparation and operations

**Status: prepared and partly verified locally; never deployed or clinically approved.**
The templates are infrastructure preparation, not permission to provision paid Azure
resources. A clinic operator must approve region, sizing, access, costs, recovery
objectives, clinical policies, and the GitHub environment before deployment.

## What exists

- `Dockerfile` builds the Flask/Gunicorn release image from the pinned Python 3.12.12
  Debian base digest. The build downloads the pinned DejaVu package and verifies its
  package and font SHA-256. Runtime UID 999 is non-root. No model, report, test data,
  frontend, or local environment enters the image. Its liveness probe checks the web
  process; `/api/v1/health/ready` separately checks database schema revision.
- `azure/foundation.bicep` prepares a Standard Static Web App, Container Apps
  environment, private-network MySQL Flexible Server, Basic ACR, private Blob
  Storage with private endpoint/DNS, managed identity and container-scoped Blob Data
  Contributor plus registry AcrPull roles, and Log Analytics. Defaults are **cost
  assumptions**, not capacity recommendations: B1ms/20 GB/7-day database, Basic
  registry, LRS storage, 30-day logs, and one to three API replicas. Confirm current
  region/SKU support, quotas, HA, networking, retention, and monthly price before use.
- `azure/release.bicep` defines an explicit manual migration job and an optional
  application activation using one immutable image digest. `azure/link-api.bicep`
  links the Standard Static Web App `/api` path to Container Apps after frontend/API
  deployment. The frontend uses relative `/api/v1` URLs. SWA proxies the same path,
  so Strict SameSite refresh/CSRF cookies work on one HTTPS origin. Do not use a
  second browser origin for the API. The Container App has external ingress because
  [SWA linked backends cannot be network isolated](https://learn.microsoft.com/en-us/azure/static-web-apps/apis-overview);
  app authorization still applies. Restrict direct ACA ingress with verified access
  controls before live release. SWA Standard, 45-second API limit, and no PR backend
  linking are platform constraints.

## Local setup and checks

From the repository root, with Python 3.12, Node 22+, Docker Desktop, and Git:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
cd frontend; npm ci; npm run check; npx playwright install chromium; cd ..
$env:REPORT_FONT_PATH = '<absolute path to checksum-verified DejaVuSans.ttf>'
.\.venv\Scripts\python.exe -m pytest tests/backend -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m scripts.test_mysql
$env:PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
cd frontend; npm run test:e2e; cd ..
docker build -f deployment/Dockerfile -t ayursage:phase9-local .
az bicep build --file deployment/azure/foundation.bicep
az bicep build --file deployment/azure/release.bicep
az bicep build --file deployment/azure/link-api.bicep
```

On Windows, the local report-storage implementation uses POSIX file primitives;
execute the complete report tests in Linux as CI does. The standalone font helper
`python -m scripts.prepare_report_font --output <private path>` needs `dpkg-deb`.
Do not infer Linux/ML compatibility from Windows Python tests. The image deliberately
contains no V17 runtime or artifact.

## Production configuration and secrets

Set `AYURSAGE_ENV=production`, `ML_ENABLED=false`, `COOKIE_SECURE=true`,
`ALLOWED_ORIGINS=https://<SWA-host>`, `REPORT_STORAGE_BACKEND=azure`,
`AZURE_REPORT_ACCOUNT_URL=https://<account>.blob.core.windows.net`, and
`AZURE_REPORT_CONTAINER=reports`. Supply `JWT_SECRET` (at least 32 characters) and
`DATABASE_URL` as secret values. The MySQL URL must use `mysql+pymysql`, the private
server FQDN, a runtime user, and
`ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_cert=true&ssl_verify_identity=true`.
Azure MySQL must also have `require_secure_transport=ON`. Keep migration credentials
separate from runtime credentials where practical; the current single secret URL in
the release template is a remaining least-privilege gap to resolve before live use.
Secrets must be provisioned through an approved vault/environment; never commit a
parameter file containing them. App errors remain generic; suppress proxy and
platform request/response body logging. Validate cloud logs for PHI and credentials.

The private V17 artifact requires a separate authorized channel and trusted SHA-256
manifest. Verify its bytes before any load, preserve the original callable/source,
install its independently evidenced runtime in a separate approved image variant,
and run authorized reference parity tests. This image does none of those steps;
`ML_ENABLED=false` remains enforced. Do not attach a model to the deployment until
the Phase 5 and clinical gates are complete.

## Controlled release sequence

1. Obtain GitHub `production` environment reviewer protection, branch restrictions,
   and OIDC federated credential for this repository/environment. Set environment
   secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
   `DATABASE_URL`, `JWT_SECRET`, and `SWA_DEPLOYMENT_TOKEN`. Give the deployment
   identity only the reviewed resource-group roles needed for ACR push, Container
   Apps update/jobs, and SWA publication. These settings are **not verified** here.
2. Review `az deployment group what-if` for `foundation.bicep`, cost, private DNS,
   region/SKU support, admin login, and networking. Deploy foundation only with
   explicit human approval. Create a limited runtime database login and a separately
   privileged migration login; confirm their grants and TLS connectivity from the
   Container Apps VNet. Configure backups and recovery objectives.
3. Build/push the image and record commit, immutable registry digest, Docker base
   digest, migration head (`0003_approved_reports`), font checksum, and engine
   versions. Use the manual GitHub workflow only after the foundation exists. It
   updates a manual migration job, runs it, checks success, then activates the API.
   Never publish a new API revision before compatible schema migration. The workflow
   publishes the locked frontend, then links `/api` after API activation.
4. Smoke test HTTPS login, refresh cookie path and CSRF, role authorization, 200
   liveness, 200 database readiness, and actual private Blob read/write with
   synthetic approved data. `ml=unavailable` and clinical approval unavailable are
   expected until their independent evidence gates pass. Test static assets and
   deny direct report/object access. Record Azure-side evidence separately.

The manual workflow has no `push`/`pull_request` trigger. CI builds and compiles but
does not provision, deploy, or publish. Protect the GitHub environment before use.
The frontend must be published before linked backend resolution. Examine failed job
execution logs without exposing secrets or patient payloads.

## Backup, restore, and rollback

Use MySQL's managed backups/PITR as the production recovery foundation. The logical
backup helper `python -m scripts.database_backup backup <private.sql>` reads
`BACKUP_DATABASE_URL` from the environment, requires `mysqldump`, writes a SHA-256
sidecar, and refuses overwrite. Transfer both files to a protected location. A
restore exercise uses `RESTORE_DATABASE_URL`, a **new empty** schema named
`ayursage_test_*`, and `python -m scripts.database_backup restore-disposable
<private.sql> --database ayursage_test_<id>`; it verifies SHA-256 before import.
Never point it at an existing user database. Keep all `.sql` files outside Git.

If migration fails, stop before app activation, inspect the job and restore the
previous compatible release image. A previous image may be rolled back only after
checking migration compatibility; never downgrade a user database. For an
incompatible schema or data failure, restore a managed backup into a newly created
database, verify it and plan controlled cutover with clinical owner sign-off. Record
RPO/RTO and rehearse this in Azure before calling deployment ready.

## Remaining gates

No Azure resource, OIDC identity, environment approval, TLS connection, private
endpoint, managed backup, production login throttling, privileged-role MFA, or
clinical workflow was verified by this local work. Shared login throttling and MFA
are missing release controls. V17 evidence, clinical input/enrichment/approval
policies, and real-model end-to-end acceptance remain blocked as documented in
`docs/phase5-evidence.md`, `docs/phase6-acceptance.md`,
`docs/phase7-reports.md`, and `docs/phase8-frontend.md`.
