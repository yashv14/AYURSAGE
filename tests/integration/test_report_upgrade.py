"""Phase 6 → Phase 7 additive upgrade preserves legacy reports without fabrication."""
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from backend.app.database import db, utcnow
from tests.report_support import approved_case

pytestmark = pytest.mark.mysql


def test_phase7_upgrade_preserves_legacy_report_and_refuses_release(mysql_app, monkeypatch):
    case = approved_case(mysql_app, monkeypatch)
    report_id = str(uuid4())
    with mysql_app.app_context():
        db.session.remove()
        command.downgrade(Config("alembic.ini"), "0002_doctor_review")
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO reports (id,created_at,updated_at,row_version,approval_id,version,status,object_key,retry_count) "
                                    "VALUES (:id,:now,:now,1,:approval,'legacy-synthetic','FAILED',:key,0)"),
                               {"id": report_id, "now": utcnow().replace(tzinfo=None),
                                "approval": case["approval"]["id"], "key": "synthetic-legacy-report-" + report_id})
        command.upgrade(Config("alembic.ini"), "head")
        command.check(Config("alembic.ini"))
        with db.engine.connect() as connection:
            row = connection.execute(text("SELECT status,object_key,snapshot_checksum,template_version,generation_token,lease_expires_at "
                                          "FROM reports WHERE id=:id"), {"id": report_id}).one()
            assert tuple(row) == ("FAILED", "synthetic-legacy-report-" + report_id, None, None, None, None)
    result = case["client"].get(f"/api/v1/reports/{report_id}/download", headers=case["headers"]["patient"])
    assert result.status_code == 503 and result.json["error"]["code"] == "REPORT_INTEGRITY_FAILURE"
