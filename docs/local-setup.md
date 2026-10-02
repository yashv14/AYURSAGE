# Local setup

## Prerequisites

- Python 3.12 or newer
- Node.js 22 or newer and npm

The current shell does not require MySQL or a model. Those dependencies will be added only in their evidence-backed phases.

## Backend

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
flask --app backend.app:create_app run --port 5000
```

Check process liveness at <http://localhost:5000/api/v1/health/live>.

Run tests from the repository root:

```bash
python -m pytest
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Build the production assets with `npm run build`.

## Foundation safety check

Run the repository guard that rejects tracked model binaries, private key files,
non-example environment files, and attempts to recreate `predict_single()`:

```bash
./scripts/verify-foundation.sh
```

## Configuration

Copy `.env.example` to `.env` for local overrides. Never commit `.env`. `ML_ENABLED` remains `false`; enabling it does not provide an implementation, and no placeholder prediction behavior exists.
