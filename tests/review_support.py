"""Synthetic persisted records only: never calls or enables V17 inference."""
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select

from backend.app.auth import access_token
from backend.app.database import db, utcnow
from backend.app.inference import TARGETS, MODEL_SHA256, SOURCE_SHA256, PIPELINE_VERSION, ADAPTER_VERSION
from backend.app.models import (Role, User, DoctorProfile, Patient, Consultation, ClinicalInput,
                               ModelVersion, PredictionRun, PredictionOutput, EnrichmentResult)


def seed_case(app):
    with app.app_context():
        roles = {role.code: role for role in db.session.scalars(select(Role)).all()}
        for code in ("PATIENT", "DOCTOR", "ADMIN"):
            if code not in roles:
                roles[code] = Role(code=code)
                db.session.add(roles[code])
        users = {}
        for name, role in (("patient", "PATIENT"), ("other_patient", "PATIENT"),
                           ("doctor", "DOCTOR"), ("other_doctor", "DOCTOR"), ("admin", "ADMIN")):
            users[name] = User(normalized_email=f"{name}-{uuid4().hex}@example.invalid",
                               password_hash="synthetic-not-a-login-hash", role=roles[role])
            db.session.add(users[name])
        db.session.flush()
        patients = {}
        for name in ("patient", "other_patient"):
            patients[name] = Patient(user_id=users[name].id, profile={"synthetic": True})
            db.session.add(patients[name])
        for name in ("doctor", "other_doctor"):
            db.session.add(DoctorProfile(user_id=users[name].id, verified_at=utcnow(),
                verified_by_id=users["admin"].id, verification_provenance={"synthetic": True}))
        model = db.session.scalar(select(ModelVersion).where(ModelVersion.checksum == MODEL_SHA256))
        if model is None:
            model = ModelVersion(version=PIPELINE_VERSION, checksum=MODEL_SHA256,
                object_key="synthetic-persisted-records-only", runtime_reference="synthetic-not-training-evidence",
                evidence={"sourceChecksum": SOURCE_SHA256, "adapterVersion": ADAPTER_VERSION}, enabled=False)
            db.session.add(model)
        db.session.flush()
        item = Consultation(patient_id=patients["patient"].id, assigned_doctor_id=users["doctor"].id,
                            state="PENDING_DOCTOR_REVIEW")
        db.session.add(item); db.session.flush()
        revision = ClinicalInput(consultation_id=item.id, revision=1, schema_version="synthetic-persisted-only",
            payload={"synthetic": "original input"}, provenance={"source": "synthetic-fixture"},
            actor_id=users["patient"].id, submitted_at=utcnow())
        db.session.add(revision); db.session.flush()
        item.current_input_revision = 1
        run = PredictionRun(input_id=revision.id, model_version_id=model.id, status="SUCCEEDED",
            request_id=str(uuid4()), idempotency_key=uuid4().hex, started_at=utcnow(), completed_at=utcnow())
        db.session.add(run); db.session.flush()
        enrichment = {target: {"reasoning": "synthetic original explanation"} for target in TARGETS}
        enrichment[TARGETS[1]].update(focus="synthetic focus", actions=["synthetic action"],
                                     dietary_changes=[], wellness_tips=[], avoid=[])
        enrichment[TARGETS[2]].update(focus="synthetic focus", duration="synthetic duration", poses=[],
                                     pranayama=[], meditation="synthetic meditation", benefits=[], precautions=[])
        for target in TARGETS:
            db.session.add(PredictionOutput(prediction_run_id=run.id, target_code=target,
                raw_result={"category": "synthetic persisted category", "confidence": None}))
        db.session.add(EnrichmentResult(prediction_run_id=run.id, engine_name="v17-deterministic",
                                       engine_version=SOURCE_SHA256, status="SUCCEEDED", result=enrichment))
        db.session.commit()
        return {"app": app, "client": app.test_client(), "id": item.id,
                "url": f"/api/v1/consultations/{item.id}", "input_id": revision.id, "run_id": run.id,
                "ids": {name: user.id for name, user in users.items()},
                "headers": {name: {"Authorization": "Bearer " + access_token(user)[0]} for name, user in users.items()},
                "row_version": item.row_version}


def draft_payload(case, **changes):
    value = {"expectedRowVersion": case["row_version"], "expectedReviewRevision": 0,
             "inputRevision": 1, "predictionRunId": case["run_id"],
             "decisions": [{"targetCode": target, "action": "ACCEPT"} for target in TARGETS],
             "careNotes": "Synthetic doctor-authored notes.", "careNotesCompleted": True, "prescription": None}
    return {**value, **changes}


def save(case, **changes):
    return case["client"].post(case["url"] + "/review", headers=case["headers"]["doctor"],
                               json=draft_payload(case, **changes))


def approval_payload(response):
    value = response.json["data"]
    return {"expectedRowVersion": value["consultation"]["rowVersion"],
            "reviewId": value["review"]["id"], "reviewRevision": value["review"]["revision"]}


def approve(case, payload, key="synthetic-approval", actor="doctor"):
    return case["client"].post(case["url"] + "/approve", json=payload,
        headers={**case["headers"][actor], "Idempotency-Key": key})


def original_records(case):
    with case["app"].app_context():
        revision = db.session.get(ClinicalInput, case["input_id"])
        outputs = db.session.scalars(select(PredictionOutput).where(PredictionOutput.prediction_run_id == case["run_id"])).all()
        engine = db.session.scalar(select(EnrichmentResult).where(EnrichmentResult.prediction_run_id == case["run_id"]))
        return deepcopy([revision.payload, revision.provenance,
                         {row.target_code: row.raw_result for row in outputs}, engine.result])
