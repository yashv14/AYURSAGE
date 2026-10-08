"""Real MySQL transactions/locks, synthetic records, mocked clinical policy only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.app import review as service
from backend.app.database import db
from backend.app.models import Approval, AuditLog, Consultation, DoctorReview, ClinicalInput, User
from tests.review_support import seed_case, save, draft_payload, approval_payload, approve, original_records

pytestmark = pytest.mark.mysql


@pytest.fixture
def case(mysql_app):
    return seed_case(mysql_app)


@pytest.fixture
def synthetic_policy(monkeypatch):
    monkeypatch.setattr(service, "require_approval_policy", lambda source: {"syntheticTestOnly": True})


def threaded_approve(case, payload, key="synthetic-approval"):
    with case["app"].test_client() as client:
        return client.post(case["url"] + "/approve", json=payload,
            headers={**case["headers"]["doctor"], "Idempotency-Key": key})


def test_mysql_review_approval_http_and_immutable_patient_view(case, synthetic_policy):
    original = original_records(case)
    assert not case["app"].extensions["inference"].available
    draft = save(case)
    assert draft.status_code == 201
    payload = approval_payload(draft)
    result = approve(case, payload)
    assert result.status_code == 201
    assert approve(case, payload).status_code == 200
    patient = case["client"].get(case["url"] + "/approved", headers=case["headers"]["patient"])
    assert patient.status_code == 200 and patient.json["data"] == result.json["data"]
    assert case["client"].get(case["url"] + "/approved", headers=case["headers"]["other_patient"]).status_code == 404
    assert original_records(case) == original
    with case["app"].app_context():
        row = db.session.scalar(select(Approval).where(Approval.consultation_id == case["id"]))
        assert service.checksum(row.snapshot) == row.checksum
        row.snapshot = {"invalid": True}
        with pytest.raises(ValueError, match="Immutable"):
            db.session.commit()
        db.session.rollback()


def test_mysql_concurrent_duplicate_approvals_commit_once(case, monkeypatch):
    entered, release, second_started = Event(), Event(), Event()
    def slow_policy(source):
        entered.set()
        assert release.wait(15)
        return {"syntheticTestOnly": True}
    monkeypatch.setattr(service, "require_approval_policy", slow_policy)
    draft = save(case)
    payload = approval_payload(draft)
    def duplicate():
        second_started.set()
        return threaded_approve(case, payload)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(threaded_approve, case, payload)
        try:
            assert entered.wait(10)
            second = workers.submit(duplicate)
            assert second_started.wait(5)
            assert not second.done()
        finally:
            release.set()
        results = [first.result(timeout=15), second.result(timeout=15)]
    assert sorted(result.status_code for result in results) == [200, 201]
    assert results[0].json["data"]["approval"]["id"] == results[1].json["data"]["approval"]["id"]
    with case["app"].app_context():
        assert len(db.session.scalars(select(Approval).where(Approval.consultation_id == case["id"])).all()) == 1
        assert len(db.session.scalars(select(AuditLog).where(AuditLog.resource_id == case["id"], AuditLog.event == "CONSULTATION_APPROVED")).all()) == 1


def test_mysql_concurrent_save_and_approval_cannot_both_succeed(case, monkeypatch):
    draft = save(case)
    entered, release = Event(), Event()
    def slow_policy(source):
        entered.set()
        assert release.wait(15)
        return {"syntheticTestOnly": True}
    monkeypatch.setattr(service, "require_approval_policy", slow_policy)
    payload = approval_payload(draft)
    update_payload = draft_payload(case, expectedRowVersion=payload["expectedRowVersion"], expectedReviewRevision=1,
                                   careNotes="Concurrent synthetic edit")
    def competing_save():
        with case["app"].test_client() as client:
            return client.post(case["url"] + "/review", json=update_payload, headers=case["headers"]["doctor"])
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(threaded_approve, case, payload)
        try:
            assert entered.wait(10)
            second = workers.submit(competing_save)
        finally:
            release.set()
        assert first.result(timeout=15).status_code == 201
        assert second.result(timeout=15).status_code == 409
    with case["app"].app_context():
        approval = db.session.scalar(select(Approval).where(Approval.consultation_id == case["id"]))
        assert approval.snapshot["patientView"]["careNotes"] == "Synthetic doctor-authored notes."


@pytest.mark.parametrize("change, expected", [("assignment", 404), ("input", 409), ("account", 401)])
def test_mysql_waiting_approval_rechecks_authority_and_revision_after_lock(case, synthetic_policy, change, expected):
    draft = save(case)
    with case["app"].app_context():
        engine = db.engine
    attempted_lock = Event()
    def notice_lock(connection, cursor, statement, parameters, context, executemany):
        if "FROM consultations" in statement and "FOR UPDATE" in statement:
            attempted_lock.set()
    with Session(engine) as competing:
        item = competing.scalar(select(Consultation).where(Consultation.id == case["id"]).with_for_update())
        event.listen(engine, "before_cursor_execute", notice_lock)
        try:
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(threaded_approve, case, approval_payload(draft))
                try:
                    assert attempted_lock.wait(10)
                    assert not future.done()
                    if change == "assignment":
                        item.assigned_doctor_id = case["ids"]["other_doctor"]
                    elif change == "input":
                        revision = ClinicalInput(consultation_id=item.id, revision=2, schema_version="synthetic",
                            payload={}, provenance={}, actor_id=case["ids"]["patient"])
                        competing.add(revision); competing.flush()
                        item.current_input_revision = 2
                    else:
                        competing.get(User, case["ids"]["doctor"]).active = False
                finally:
                    competing.commit()
                assert future.result(timeout=15).status_code == expected
        finally:
            event.remove(engine, "before_cursor_execute", notice_lock)
    with case["app"].app_context():
        assert db.session.scalar(select(Approval).where(Approval.consultation_id == case["id"])) is None


def test_mysql_concurrent_draft_saves_use_one_revision(case):
    with ThreadPoolExecutor(max_workers=2) as workers:
        def attempt():
            with case["app"].test_client() as client:
                return client.post(case["url"] + "/review", json=draft_payload(case), headers=case["headers"]["doctor"])
        futures = [workers.submit(attempt) for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]
    assert sorted(response.status_code for response in responses) == [201, 409]
    with case["app"].app_context():
        assert len(db.session.scalars(select(DoctorReview).where(DoctorReview.consultation_id == case["id"])).all()) == 1


def test_mysql_approval_rollback_leaves_no_partial_snapshot(case, synthetic_policy):
    draft = save(case)
    def fail(mapper, connection, record):
        if record.event == "CONSULTATION_APPROVED" and record.resource_id == case["id"]:
            raise RuntimeError("synthetic audit failure")
    event.listen(AuditLog, "before_insert", fail)
    try:
        assert approve(case, approval_payload(draft)).status_code == 500
    finally:
        event.remove(AuditLog, "before_insert", fail)
    with case["app"].app_context():
        assert db.session.scalar(select(Approval).where(Approval.consultation_id == case["id"])) is None
        assert db.session.get(Consultation, case["id"]).state == "PENDING_DOCTOR_REVIEW"
        assert db.session.get(DoctorReview, draft.json["data"]["review"]["id"]).status == "COMPLETED"
    assert approve(case, approval_payload(draft)).status_code == 201
