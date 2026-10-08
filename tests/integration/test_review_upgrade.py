"""Upgrade an existing synthetic Phase 3/5 schema without inventing history."""
import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from backend.app.database import db, utcnow
from backend.app.models import (Role, User, Patient, Consultation, ClinicalInput, ModelVersion,
                               PredictionRun, DoctorReview, Approval)

pytestmark = pytest.mark.mysql


def test_upgrade_preserves_legacy_reviews_and_approvals_without_backfill(mysql_app):
    # This module's fixture owns a newly created, uniquely named disposable schema.
    with mysql_app.app_context():
        db.session.remove()
        command.downgrade(Config("alembic.ini"), "0001_platform")
        ids = {key: str(uuid4()) for key in ("role", "user", "patient", "case", "input", "model", "run", "review", "approval")}
        now = utcnow()
        with db.engine.begin() as connection:
            connection.execute(Role.__table__.insert().values(id=ids["role"], code="PATIENT", created_at=now))
            connection.execute(User.__table__.insert().values(id=ids["user"], normalized_email="legacy@example.invalid",
                password_hash="synthetic", role_id=ids["role"], active=True, created_at=now, updated_at=now, row_version=1))
            connection.execute(Patient.__table__.insert().values(id=ids["patient"], user_id=ids["user"], profile={},
                created_at=now, updated_at=now, row_version=1))
            connection.execute(Consultation.__table__.insert().values(id=ids["case"], patient_id=ids["patient"],
                state="APPROVED", created_at=now, updated_at=now, row_version=1))
            connection.execute(ClinicalInput.__table__.insert().values(id=ids["input"], consultation_id=ids["case"],
                revision=1, schema_version="synthetic-legacy", payload={}, provenance={}, actor_id=ids["user"], created_at=now))
            connection.execute(ModelVersion.__table__.insert().values(id=ids["model"], version="synthetic-legacy",
                checksum="a"*64, object_key="synthetic-legacy", evidence={}, runtime_reference="synthetic", enabled=False, created_at=now))
            connection.execute(PredictionRun.__table__.insert().values(id=ids["run"], input_id=ids["input"],
                model_version_id=ids["model"], status="SUCCEEDED", request_id="synthetic", idempotency_key="synthetic", created_at=now))
            connection.execute(DoctorReview.__table__.insert().values(id=ids["review"], consultation_id=ids["case"],
                input_id=ids["input"], prediction_run_id=ids["run"], reviewer_id=ids["user"], status="APPROVED",
                expected_consultation_version=1, created_at=now, updated_at=now, row_version=1))
            connection.execute(Approval.__table__.insert().values(id=ids["approval"], doctor_review_id=ids["review"],
                consultation_id=ids["case"], version=1, approver_id=ids["user"], snapshot={"legacySynthetic": True},
                checksum="b"*64, approved_at=now, created_at=now))
        command.upgrade(Config("alembic.ini"), "head")
        command.check(Config("alembic.ini"))
        with db.engine.connect() as connection:
            review = connection.execute(text("SELECT revision, source_snapshot, source_checksum, status FROM doctor_reviews WHERE id=:id"), {"id": ids["review"]}).one()
            assert tuple(review) == (None, None, None, "APPROVED")
            approval = connection.execute(text("SELECT snapshot, checksum, idempotency_key, request_checksum FROM approvals WHERE id=:id"), {"id": ids["approval"]}).one()
            assert json.loads(approval.snapshot) == {"legacySynthetic": True}
            assert approval.checksum == "b"*64 and approval.idempotency_key is None and approval.request_checksum is None
