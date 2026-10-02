"""Synthetic storage cases, never V17 reference cases or patient data."""
from datetime import datetime, timezone, timedelta
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.app.database import db
from backend.app.models import (Role, User, Patient, Consultation, ClinicalInput,
                                ModelVersion, PredictionRun, PredictionOutput,
                                DoctorReview, ReviewDecision, Approval)

pytestmark = pytest.mark.mysql


def test_mysql_schema_and_integrity(mysql_app):
    with mysql_app.app_context():
        assert db.engine.dialect.name == "mysql"
        schema = inspect(db.engine)
        assert set(schema.get_table_names()) == set(db.metadata.tables) | {"alembic_version"}
        assert any(fk["name"] == "fk_consultation_current_input" for fk in schema.get_foreign_keys("consultations"))
        assert db.session.execute(text("SELECT @@session.time_zone")).scalar() == "+00:00"
        role = Role(code="PATIENT")
        db.session.add(role)
        db.session.flush()
        timestamp = datetime(2026, 1, 1, 6, 0, 0, 123456, tzinfo=timezone(timedelta(hours=6)))
        user = User(normalized_email="synthetic@example.invalid", password_hash="synthetic-hash", role=role, created_at=timestamp)
        db.session.add(user)
        db.session.flush()
        patient = Patient(user=user, profile={})
        db.session.add(patient)
        db.session.flush()
        consultation = Consultation(patient=patient)
        db.session.add(consultation)
        db.session.flush()
        input_record = ClinicalInput(consultation=consultation, revision=1, schema_version="synthetic-storage-only", payload={}, provenance={}, actor=user)
        db.session.add(input_record)
        db.session.flush()
        consultation.current_input_revision = 1
        model = ModelVersion(version="synthetic-storage-only", checksum="a" * 64, object_key="synthetic", evidence={}, runtime_reference="no-inference")
        db.session.add(model)
        db.session.flush()
        run = PredictionRun(input=input_record, model_version=model, request_id="synthetic", idempotency_key="synthetic")
        db.session.add(run)
        db.session.flush()
        review = DoctorReview(consultation=consultation, input=input_record, run=run, reviewer=user, expected_consultation_version=consultation.row_version)
        db.session.add(review)
        db.session.commit()
        assert user.created_at.tzinfo == timezone.utc
        assert user.created_at == datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)

        def rejected(record):
            with pytest.raises((IntegrityError, OperationalError)) as error:
                with db.session.begin_nested():
                    db.session.add(record)
                    db.session.flush()
            assert error.value.orig.args[0] in (1062, 1451, 1452, 3819)

        rejected(User(normalized_email=user.normalized_email, password_hash="synthetic", role=role))
        rejected(Patient(user_id="nonexistent", profile={}))
        rejected(ClinicalInput(consultation_id=consultation.id, revision=1, schema_version="synthetic", payload={}, provenance={}, actor_id=user.id))
        rejected(ReviewDecision(doctor_review_id=review.id, target_code="synthetic-target", action="EDIT", content={}))
        rejected(ReviewDecision(doctor_review_id=review.id, target_code="synthetic-target", action="EDIT", content=None, reason="synthetic reason"))
        rejected(Consultation(patient_id=patient.id, state="UNKNOWN"))
        rejected(PredictionRun(input_id=input_record.id, model_version_id=model.id, request_id="other", idempotency_key="synthetic"))

        db.session.add(PredictionOutput(prediction_run_id=run.id, target_code="synthetic-target", raw_result={"storage": True}))
        db.session.commit()
        rejected(PredictionOutput(prediction_run_id=run.id, target_code="synthetic-target", raw_result={}))
        output = db.session.execute(db.select(PredictionOutput)).scalar_one()
        output.raw_result = {"changed": True}
        with pytest.raises(ValueError, match="raw output"):
            db.session.flush()
        db.session.rollback()
        input_record.submitted_at = timestamp
        db.session.commit()
        # The submission attribute is expired after commit: clearing it must still fail.
        input_record.submitted_at = None
        with pytest.raises(ValueError, match="new revision"):
            db.session.flush()
        db.session.rollback()
        approval = Approval(doctor_review_id=review.id, consultation_id=consultation.id, version=1,
                            approver_id=user.id, snapshot={"synthetic": True}, checksum="b" * 64,
                            approved_at=timestamp)
        db.session.add(approval)
        db.session.commit()
        rejected(Approval(doctor_review_id=review.id, consultation_id=consultation.id, version=1,
                          approver_id=user.id, snapshot={}, checksum="c" * 64, approved_at=timestamp))
        approval.snapshot = {"changed": True}
        with pytest.raises(ValueError, match="Immutable"):
            db.session.flush()
        db.session.rollback()
        other = Consultation(patient=patient)
        db.session.add(other)
        db.session.commit()
        rejected(DoctorReview(consultation_id=other.id, input_id=input_record.id, prediction_run_id=run.id, reviewer_id=user.id, expected_consultation_version=1))
        rejected(Approval(doctor_review_id=review.id, consultation_id=other.id, version=1, approver_id=user.id, snapshot={}, checksum="b" * 64, approved_at=user.created_at))
        with pytest.raises(IntegrityError):
            with db.session.begin_nested():
                db.session.execute(text("DELETE FROM users WHERE id=:id"), {"id": user.id})
        with pytest.raises(IntegrityError):
            with db.session.begin_nested():
                db.session.execute(text("UPDATE consultations SET current_input_revision=99 WHERE id=:id"), {"id": consultation.id})
        with pytest.raises(OperationalError) as check_error:
            with db.session.begin_nested():
                db.session.execute(text("UPDATE patients SET row_version=0 WHERE id=:id"), {"id": patient.id})
        assert check_error.value.orig.args[0] == 3819

        consultation_id = consultation.id
        db.session.rollback()  # Release FK-test locks before independent stale-write sessions.
        with Session(db.engine) as first, Session(db.engine) as second:
            a = first.get(Consultation, consultation_id)
            b = second.get(Consultation, consultation_id)
            a.state = "CANCELLED"
            first.commit()
            b.state = "SUBMITTED"
            with pytest.raises(StaleDataError):
                second.commit()
        db.session.rollback()
    assert mysql_app.test_client().get("/api/v1/health/ready").status_code == 200


def test_mysql_migration_roundtrip(mysql_app):
    # This fixture created a fresh random schema; downgrade is never run on supplied DBs.
    with mysql_app.app_context():
        db.session.remove()
        command.check(Config("alembic.ini"))
        os.environ.pop("AYURSAGE_ALLOW_TEST_DOWNGRADE")
        try:
            with pytest.raises(RuntimeError, match="restricted to disposable"):
                command.downgrade(Config("alembic.ini"), "base")
        finally:
            os.environ["AYURSAGE_ALLOW_TEST_DOWNGRADE"] = "1"
        command.downgrade(Config("alembic.ini"), "base")
        assert inspect(db.engine).get_table_names() == ["alembic_version"]
        # An unrelated unversioned table must stop upgrade even if an empty version
        # table remains from downgrade. Use only this invocation's disposable schema.
        with db.engine.begin() as connection:
            connection.execute(text("CREATE TABLE synthetic_existing (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO synthetic_existing VALUES (1)"))
        with pytest.raises(RuntimeError, match="nonempty unversioned"):
            command.upgrade(Config("alembic.ini"), "head")
        with db.engine.begin() as connection:
            assert connection.execute(text("SELECT id FROM synthetic_existing")).scalar() == 1
            connection.execute(text("DROP TABLE synthetic_existing"))
        command.upgrade(Config("alembic.ini"), "head")
        command.check(Config("alembic.ini"))
        assert set(inspect(db.engine).get_table_names()) == set(db.metadata.tables) | {"alembic_version"}
