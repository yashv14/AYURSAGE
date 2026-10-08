"""Disposable browser integration server. Never imported by production.

Persists explicitly synthetic source records; never enables or substitutes V17.
One allowlisted synthetic input has a unittest-mocked approval policy solely to
exercise snapshot/report UI. All other approvals use the actual unavailable gate.
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import secrets
import signal
import sys

from sqlalchemy import text
from backend.app import create_app, review
from backend.app.auth import hash_password
from backend.app.database import db
from backend.app.models import User
from tests.review_support import seed_case, save, approve, approval_payload


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with TemporaryDirectory(prefix="ayursage-browser-") as directory:
        app = create_app({"TESTING": True, "DATABASE_URL": f"sqlite:///{directory}/synthetic.db",
            "ML_ENABLED": "false", "JWT_SECRET": secrets.token_hex(32), "COOKIE_SECURE": False,
            "ACCESS_TOKEN_SECONDS": 3, "ALLOWED_ORIGINS": {"http://127.0.0.1:5178"},
            "REPORT_LOCAL_ROOT": f"{directory}/private-reports"})
        with app.app_context():
            db.create_all()
            db.session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            db.session.execute(text("INSERT INTO alembic_version VALUES ('0003_approved_reports')"))
            db.session.commit()
        fixtures = {}
        # Random ephemeral credentials, written outside the checkout for the runner.
        password = secrets.token_urlsafe(24)
        password_hash = hash_password(password)
        for name in ("approval", "blocked", "stale", "information", "session", "admin", "report"):
            case = seed_case(app)
            if name == "report":
                with patch.object(review, "require_approval_policy", lambda source: {"syntheticTestOnly": True}):
                    saved = save(case)
                    assert saved.status_code == 201
                    assert approve(case, approval_payload(saved)).status_code == 201
            with app.app_context():
                accounts = {}
                for role, identity in case["ids"].items():
                    user = db.session.get(User, identity)
                    user.password_hash = password_hash
                    accounts[role] = {"email": user.normalized_email, "password": password, "id": user.id}
                db.session.commit()
            fixtures[name] = {"id": case["id"], "rowVersion": case["row_version"], "accounts": accounts}
            if name == "approval":
                allowed_input = case["input_id"]
        path = Path(os.environ["PHASE8_FIXTURE_FILE"])
        path.write_text(json.dumps(fixtures))
        path.chmod(0o600)
        original = review.require_approval_policy
        def synthetic_policy(source):
            if source["input"]["id"] == allowed_input:
                return {"syntheticTestOnly": True}
            return original(source)
        # This patch lives only for this isolated test process, with no API switch.
        with patch.object(review, "require_approval_policy", synthetic_policy):
            try:
                app.run(host="127.0.0.1", port=5058, debug=False, use_reloader=False)
            finally:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
