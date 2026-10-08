"""Phase 6 HTTP tests: synthetic persisted records and a mocked clinical policy.

The default policy gate is separately tested. No inference gate is changed.
"""
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import event, select, update

from backend.app import review as service
from backend.app.database import db, utcnow
from backend.app.models import (User, Consultation, ClinicalInput, PredictionRun, PredictionOutput,
    DoctorReview, ReviewDecision, Prescription, Approval, AuditLog, EnrichmentResult)
from backend.app.inference import TARGETS
from tests.review_support import seed_case, save, draft_payload, approval_payload, approve, original_records


@pytest.fixture(autouse=True)
def schema(app):
    with app.app_context():
        db.create_all()
    yield
    with app.app_context():
        db.session.remove()
        with db.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        db.drop_all()


@pytest.fixture
def case(app):
    return seed_case(app)


@pytest.fixture
def synthetic_policy(monkeypatch):
    monkeypatch.setattr(service, "require_approval_policy", lambda source: {"syntheticTestOnly": True})


def test_assigned_doctor_queue_context_and_forbidden_roles(case):
    c, url, headers = case["client"], case["url"], case["headers"]
    assert c.get("/api/v1/doctor/review-queue", headers=headers["doctor"]).json["data"]["items"][0]["id"] == case["id"]
    assert c.get("/api/v1/doctor/review-queue", headers=headers["other_doctor"]).json["data"]["items"] == []
    context = c.get(url + "/review-context", headers=headers["doctor"])
    assert context.status_code == 200
    source = context.json["data"]["source"]
    assert source["input"]["id"] == case["input_id"] and source["prediction"]["id"] == case["run_id"]
    assert set(source["prediction"]["originalOutputs"]) == set(TARGETS)
    for actor in ("patient", "other_patient", "admin", "other_doctor"):
        expected = 404 if actor == "other_doctor" else 403
        assert c.get(url + "/review-context", headers=headers[actor]).status_code == expected
        assert c.get(url + "/review", headers=headers[actor]).status_code == expected
        assert c.post(url + "/review", headers=headers[actor], json=draft_payload(case)).status_code == expected
        assert approve(case, {"expectedRowVersion": 1, "reviewId": "synthetic", "reviewRevision": 1}, actor=actor).status_code == expected
    assert c.get(url + "/review-context").status_code == 401
    assert c.get(url + "/approved", headers=headers["patient"]).status_code == 404


def test_drafts_are_new_immutable_revisions_with_stale_save_rejected(case):
    before = original_records(case)
    first = save(case, decisions=[], careNotes="", careNotesCompleted=False)
    assert first.status_code == 201 and first.json["data"]["review"]["status"] == "IN_PROGRESS"
    assert save(case).status_code == 409
    second = save(case, expectedRowVersion=first.json["data"]["consultation"]["rowVersion"], expectedReviewRevision=1,
        decisions=[{"targetCode": TARGETS[0], "action": "EDIT", "content": "Synthetic replacement", "reason": "Synthetic rationale"}])
    assert second.status_code == 201 and second.json["data"]["review"]["revision"] == 2
    old = case["client"].get(case["url"] + "/review?revision=1", headers=case["headers"]["doctor"])
    assert old.json["data"]["review"]["status"] == "SUPERSEDED"
    assert old.json["data"]["review"]["careNotes"] == ""
    assert second.json["data"]["review"]["decisions"][0]["original"]["raw"]["category"] == "synthetic persisted category"
    assert original_records(case) == before


@pytest.mark.parametrize("changes", [
    {"decisions": [{"targetCode": TARGETS[0], "action": "EDIT", "content": "replacement"}]},
    {"decisions": [{"targetCode": TARGETS[0], "action": "OVERRIDE", "reason": "reason"}]},
    {"decisions": [{"targetCode": TARGETS[0], "action": "ACCEPT", "content": "replacement"}]},
    {"decisions": [{"targetCode": TARGETS[0], "action": "ACCEPT"}] * 2},
    {"decisions": [{"targetCode": "invented", "action": "ACCEPT"}]},
    {"prescription": "PENDING_DOCTOR_REVIEW"}, {"careNotes": "", "careNotesCompleted": True},
    {"expectedReviewRevision": True}, {"careNotesCompleted": "true"}, {"ownerId": "arbitrary"},
])
def test_invalid_decisions_notes_and_unknown_fields(case, changes):
    assert save(case, **changes).status_code == 422


def test_incomplete_review_and_default_policy_block_approval(case):
    partial = save(case, decisions=[])
    assert approve(case, approval_payload(partial)).status_code == 409
    complete = save(case, expectedReviewRevision=1, expectedRowVersion=partial.json["data"]["consultation"]["rowVersion"])
    response = approve(case, approval_payload(complete))
    assert response.status_code == 503 and response.json["error"]["code"] == "CLINICAL_REVIEW_POLICY_UNAPPROVED"
    with case["app"].app_context():
        assert db.session.scalar(select(Approval)) is None
        assert not case["app"].extensions["inference"].available


def test_approval_snapshot_idempotency_and_patient_projection(case, synthetic_policy):
    before = original_records(case)
    decisions = [{"targetCode": target, "action": "ACCEPT"} for target in TARGETS]
    decisions[0] = {"targetCode": TARGETS[0], "action": "EDIT", "content": "Synthetic edited recommendation", "reason": "Internal synthetic rationale"}
    decisions[1] = {"targetCode": TARGETS[1], "action": "OVERRIDE", "content": "Synthetic override", "reason": "Internal synthetic override reason"}
    draft = save(case, decisions=decisions, prescription="Synthetic doctor-authored prescription text")
    payload = approval_payload(draft)
    result = approve(case, payload)
    assert result.status_code == 201
    assert approve(case, payload).status_code == 200
    assert approve(case, {**payload, "reviewRevision": 999}).status_code == 409
    assert approve(case, payload, key="another-key").status_code == 409
    assert original_records(case) == before
    patient = case["client"].get(case["url"] + "/approved", headers=case["headers"]["patient"])
    assert patient.status_code == 200
    approved = patient.json["data"]["approval"]["approvedContent"]
    assert approved["recommendations"][TARGETS[0]] == {"text": "Synthetic edited recommendation"}
    assert approved["prescription"] == "Synthetic doctor-authored prescription text"
    assert all(name not in patient.text for name in ("originalOutputs", "sourceChecksum", "class_probabilities", "Internal synthetic"))
    assert case["client"].get(case["url"] + "/approved", headers=case["headers"]["other_patient"]).status_code == 404
    assert case["client"].get(case["url"] + "/approved", headers=case["headers"]["admin"]).status_code == 403
    with case["app"].app_context():
        approval = db.session.scalar(select(Approval))
        assert approval.snapshot["patientView"] == approved
        assert service.checksum(approval.snapshot) == approval.checksum
        assert approval.snapshot["source"]["prediction"]["id"] == case["run_id"]
        assert approval.snapshot["review"]["revision"] == payload["reviewRevision"]
        assert len(db.session.scalars(select(Approval)).all()) == 1
        assert db.session.get(Consultation, case["id"]).state == "APPROVED"
        assert db.session.get(DoctorReview, payload["reviewId"]).status == "APPROVED"
        for cls, attribute, value in ((Approval, "snapshot", {}), (ReviewDecision, "content", "changed"),
                                     (Prescription, "care_notes", "changed"), (DoctorReview, "source_snapshot", {})):
            row = db.session.scalar(select(cls)); setattr(row, attribute, value)
            with pytest.raises(ValueError):
                db.session.commit()
            db.session.rollback()


@pytest.mark.parametrize("change", ["input", "prediction", "enrichment"])
def test_changed_sources_cannot_be_approved(case, synthetic_policy, change):
    draft = save(case)
    with case["app"].app_context():
        if change == "input":
            revision = ClinicalInput(consultation_id=case["id"], revision=2, schema_version="synthetic",
                payload={}, provenance={}, actor_id=case["ids"]["patient"], submitted_at=utcnow())
            db.session.add(revision); db.session.flush()
            item = db.session.get(Consultation, case["id"]); item.current_input_revision = 2
        elif change == "prediction":
            prior = db.session.get(PredictionRun, case["run_id"])
            newer = PredictionRun(input_id=prior.input_id, model_version_id=prior.model_version_id,
                status="SUCCEEDED", started_at=utcnow(), completed_at=utcnow()+timedelta(seconds=1),
                request_id="synthetic-replacement", idempotency_key="synthetic-replacement")
            db.session.add(newer); db.session.flush()
            for output in db.session.scalars(select(PredictionOutput).where(PredictionOutput.prediction_run_id == prior.id)).all():
                db.session.add(PredictionOutput(prediction_run_id=newer.id, target_code=output.target_code, raw_result=deepcopy(output.raw_result)))
            original = db.session.scalar(select(EnrichmentResult).where(EnrichmentResult.prediction_run_id == prior.id))
            db.session.add(EnrichmentResult(prediction_run_id=newer.id, engine_name=original.engine_name,
                engine_version=original.engine_version, status="SUCCEEDED", result=deepcopy(original.result)))
        else:
            # Simulate corruption outside ORM protections; approval must still fail.
            db.session.execute(update(EnrichmentResult).values(result={}).execution_options(synchronize_session=False))
        db.session.commit()
    response = approve(case, approval_payload(draft))
    assert response.status_code == 409
    if change == "prediction":
        assert response.json["error"]["code"] == "STALE_SOURCE"
    with case["app"].app_context():
        assert db.session.scalar(select(Approval)) is None


def test_reassignment_invalidates_review_even_when_original_doctor_returns(case, synthetic_policy):
    draft = save(case)
    version = draft.json["data"]["consultation"]["rowVersion"]
    c, url = case["client"], case["url"]
    assignment_url = f"/api/v1/admin/consultations/{case['id']}/assignment"
    moved = c.post(assignment_url, headers=case["headers"]["admin"], json={"expectedRowVersion": version,
        "doctorId": case["ids"]["other_doctor"], "reason": "Synthetic reassignment"})
    assert moved.status_code == 200
    assert approve(case, approval_payload(draft)).status_code == 404
    assert approve(case, {**approval_payload(draft), "expectedRowVersion": moved.json["data"]["consultation"]["rowVersion"]}, actor="other_doctor").status_code == 409
    returned = c.post(assignment_url, headers=case["headers"]["admin"], json={
        "expectedRowVersion": moved.json["data"]["consultation"]["rowVersion"],
        "doctorId": case["ids"]["doctor"], "reason": "Synthetic return"})
    assert approve(case, {**approval_payload(draft), "expectedRowVersion": returned.json["data"]["consultation"]["rowVersion"]}).status_code == 409


def test_approval_audit_failure_rolls_back_every_write(case, synthetic_policy):
    draft = save(case)
    def fail(mapper, connection, record):
        if record.event == "CONSULTATION_APPROVED":
            raise RuntimeError("private synthetic clinical text")
    event.listen(AuditLog, "before_insert", fail)
    try:
        response = approve(case, approval_payload(draft))
        assert response.status_code == 500 and "private" not in response.text
    finally:
        event.remove(AuditLog, "before_insert", fail)
    with case["app"].app_context():
        assert db.session.scalar(select(Approval)) is None
        assert db.session.get(Consultation, case["id"]).state == "PENDING_DOCTOR_REVIEW"
        assert db.session.get(DoctorReview, draft.json["data"]["review"]["id"]).status == "COMPLETED"
    assert approve(case, approval_payload(draft)).status_code == 201


def test_preapproval_correction_creates_new_input_and_supersedes_review(case):
    draft = save(case)
    request = case["client"].post(case["url"] + "/request-information", headers=case["headers"]["doctor"],
        json={"expectedRowVersion": draft.json["data"]["consultation"]["rowVersion"],
              "reason": "Synthetic clarification requested", "requestedFields": ["Nadi Reading"]})
    assert request.status_code == 201
    assert case["client"].get(case["url"] + "/information-request", headers=case["headers"]["patient"]).status_code == 200
    changed = case["client"].put(case["url"] + "/inputs", headers=case["headers"]["patient"], json={
        "expectedRowVersion": request.json["data"]["consultation"]["rowVersion"], "schemaVersion": "synthetic",
        "clinicalInput": {"synthetic": "corrected"}, "provenance": {"synthetic": True}})
    assert changed.status_code == 201 and changed.json["data"]["inputRevision"]["revision"] == 2
    assert approve(case, approval_payload(draft)).status_code == 409
    with case["app"].app_context():
        assert db.session.get(ClinicalInput, case["input_id"]).payload == {"synthetic": "original input"}
        assert db.session.get(DoctorReview, draft.json["data"]["review"]["id"]).status == "SUPERSEDED"
        audit_row = db.session.scalar(select(AuditLog).where(AuditLog.event == "INFORMATION_REQUESTED"))
        assert "reason" not in audit_row.safe_metadata


def test_approved_case_cannot_be_corrected_or_reassigned(case, synthetic_policy):
    draft = save(case); assert approve(case, approval_payload(draft)).status_code == 201
    version = case["client"].get(case["url"], headers=case["headers"]["patient"]).json["data"]["consultation"]["rowVersion"]
    assert save(case, expectedRowVersion=version, expectedReviewRevision=1).status_code == 409
    assert case["client"].put(case["url"] + "/inputs", headers=case["headers"]["patient"],
        json={"expectedRowVersion": version}).status_code == 409
    assert case["client"].post(case["url"] + "/request-information", headers=case["headers"]["doctor"],
        json={"expectedRowVersion": version, "reason": "Synthetic amendment"}).status_code == 409
    assert case["client"].post(f"/api/v1/admin/consultations/{case['id']}/assignment", headers=case["headers"]["admin"],
        json={"expectedRowVersion": version, "doctorId": case["ids"]["other_doctor"], "reason": "Synthetic amendment"}).status_code == 409


def test_deactivated_doctor_cannot_use_existing_access_token(case):
    with case["app"].app_context():
        db.session.get(User, case["ids"]["doctor"]).active = False
        db.session.commit()
    assert save(case).status_code == 401


def test_review_body_limit_and_oversized_cursor_are_safe(case):
    response = save(case, careNotes="x" * (128 * 1024))
    assert response.status_code == 413 and response.headers["X-Request-ID"] == response.json["requestId"]
    response = case["client"].get("/api/v1/doctor/review-queue?limit=" + "1" * 5000, headers=case["headers"]["doctor"])
    assert response.status_code == 422


def test_approval_requires_every_persisted_target_even_if_review_is_marked_complete(case, synthetic_policy):
    draft = save(case, decisions=[])
    with case["app"].app_context():
        # Simulate erroneous status from a separate writer; structural checks still apply.
        row = db.session.get(DoctorReview, draft.json["data"]["review"]["id"])
        row.status = "COMPLETED"
        db.session.commit()
    assert approve(case, approval_payload(draft)).status_code == 409


def test_queue_pagination_is_scoped(case):
    second = seed_case(case["app"])
    with case["app"].app_context():
        item = db.session.get(Consultation, second["id"])
        item.assigned_doctor_id = case["ids"]["doctor"]
        db.session.commit()
    first = case["client"].get("/api/v1/doctor/review-queue?limit=1", headers=case["headers"]["doctor"]).json["data"]
    next_page = case["client"].get("/api/v1/doctor/review-queue?limit=1&cursor=" + first["nextCursor"], headers=case["headers"]["doctor"]).json["data"]
    assert {first["items"][0]["id"], next_page["items"][0]["id"]} == {case["id"], second["id"]}
    assert next_page["nextCursor"] is None
