"""Consultation-bound persistence. Public enabling remains evidence gated."""
from copy import deepcopy
import json

from flask import current_app, g, request
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from .database import db, utcnow
from .errors import ApiError
from .inference import TARGETS, MODEL_SHA256, PIPELINE_VERSION, SOURCE_SHA256, ADAPTER_VERSION
from .models import (AuditLog, ClinicalInput, ModelVersion, PredictionRun, PredictionOutput,
                     EnrichmentResult)


def run_view(run):
    return {"id": run.id, "status": run.status, "inputRevision": run.input.revision,
            "startedAt": run.started_at.isoformat() if run.started_at else None,
            "completedAt": run.completed_at.isoformat() if run.completed_at else None,
            "failureCode": run.failure_code}


def split_result(result):
    """Preserve actual categories/confidence separately from supplied enrichment."""
    if type(result) is not dict or set(result) != {*TARGETS, "Doctor Prescription & Care Notes"}:
        raise ValueError("Incomplete prediction result")
    if result["Doctor Prescription & Care Notes"] != "PENDING_DOCTOR_REVIEW":
        raise ValueError("Invalid review placeholder")
    raw, enrichment = {}, {}
    for target in TARGETS:
        value = result[target]
        if type(value) is not dict or not isinstance(value.get("category"), str) or not value["category"]:
            raise ValueError("Invalid target result")
        if not isinstance(value.get("reasoning"), str) or not value["reasoning"]:
            raise ValueError("Missing required reasoning")
        raw[target] = {"category": value["category"]}
        if "confidence" in value:
            raw[target]["confidence"] = deepcopy(value["confidence"])
        enrichment[target] = {key: deepcopy(item) for key, item in value.items()
                              if key not in {"category", "confidence"}}
    # Reject non-finite/non-JSON output before any output writes.
    json.dumps([raw, enrichment], allow_nan=False)
    return raw, enrichment


def submit(item, payload, expected_version, audit):
    if set(payload) != {"expectedRowVersion", "inputRevision"}:
        raise ApiError("INVALID_FIELD", "Exact submission fields are required", 422)
    revision_number = payload["inputRevision"]
    expected = payload["expectedRowVersion"]
    key = request.headers.get("Idempotency-Key")
    if type(expected) is not int or expected < 1 or type(revision_number) is not int or revision_number < 1 or not key or not key.strip() or len(key) > 128:
        raise ApiError("INVALID_FIELD", "A positive revision and idempotency key are required", 422)
    if item.current_input_revision != revision_number:
        raise ApiError("STALE_REVISION", "Input revision has changed", 409)
    revision = db.session.scalar(select(ClinicalInput).where(
        ClinicalInput.consultation_id == item.id, ClinicalInput.revision == revision_number))
    if revision is None:
        raise ApiError("INVALID_REVISION", "Input revision is unavailable", 409)
    previous = db.session.scalar(select(PredictionRun).where(
        PredictionRun.input_id == revision.id, PredictionRun.idempotency_key == key))
    if previous:
        evidence = db.session.scalars(select(AuditLog).where(AuditLog.resource_id == item.id,
            AuditLog.resource_revision == revision_number, AuditLog.actor_id == g.current_user.id)).all()
        if not any(row.safe_metadata.get("runId") == previous.id and
                   row.safe_metadata.get("expectedRowVersion") == expected for row in evidence):
            raise ApiError("IDEMPOTENCY_CONFLICT", "Idempotency key was used with a different request", 409)
        # Initial submission's database key is revision scoped; duplicates do not retry.
        return previous
    expected_version(payload, item)
    if item.state not in {"DRAFT", "NEEDS_INFORMATION"}:
        raise ApiError("INVALID_STATE", "Consultation cannot be submitted", 409)
    service = current_app.extensions["inference"]
    if not service.available:
        raise ApiError("ML_UNAVAILABLE", "Inference is blocked pending verified evidence", 503)
    try:
        service.validate(revision.payload, revision.schema_version, revision.provenance)
    except ValueError:
        raise ApiError("INVALID_CLINICAL_INPUT", "Clinical input does not match the verified contract", 422) from None
    model = db.session.scalar(select(ModelVersion).where(ModelVersion.checksum == MODEL_SHA256))
    if model is None or not model.enabled or model.version != PIPELINE_VERSION or not model.runtime_reference or \
        model.evidence.get("adapterVersion") != ADAPTER_VERSION or model.evidence.get("sourceChecksum") != SOURCE_SHA256:
        raise ApiError("ML_UNAVAILABLE", "Verified model provenance is unavailable", 503)
    run = PredictionRun(input_id=revision.id, model_version_id=model.id, request_id=g.request_id,
                        idempotency_key=key, status="RUNNING", started_at=utcnow())
    revision.submitted_at = utcnow()
    item.state = "SUBMITTED"
    db.session.add(run)
    try:
        # Acquire aggregate optimistic write before prediction. MySQL retains this lock
        # through commit; conflicting input/assignment changes cannot become current.
        db.session.flush()
        try:
            raw, enrichment = split_result(service.predict(deepcopy(revision.payload)))
        except Exception:
            run.status = "FAILED"
            run.failure_code = "INFERENCE_FAILED"
        else:
            for target in TARGETS:
                db.session.add(PredictionOutput(prediction_run_id=run.id, target_code=target,
                                               raw_result=raw[target]))
            db.session.add(EnrichmentResult(prediction_run_id=run.id, engine_name="v17-deterministic",
                engine_version=SOURCE_SHA256, status="SUCCEEDED", result=enrichment))
            run.status = "SUCCEEDED"
            item.state = "PENDING_DOCTOR_REVIEW"
        run.completed_at = utcnow()
        audit("INFERENCE_" + run.status, "consultation", item.id, revision_number,
              {"runId": run.id, "adapterVersion": ADAPTER_VERSION, "sourceChecksum": SOURCE_SHA256,
               "expectedRowVersion": expected})
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        raise ApiError("STALE_VERSION", "Resource has changed", 409) from None
    return run
