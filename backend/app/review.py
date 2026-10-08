"""Versioned doctor review of the persisted Phase 5 contract.

No inference is invoked here. Clinical policy approval remains an explicit gate.
All mutations lock the consultation first and re-read authority and source rows.
"""
from copy import deepcopy
from hashlib import sha256
import json

from flask import Blueprint, g, request
from sqlalchemy import select

from .auth import require_auth
from .database import db, utcnow
from .errors import ApiError
from .inference import TARGETS, INPUTS, MODEL_SHA256, PIPELINE_VERSION, SOURCE_SHA256, ADAPTER_VERSION
from .models import (User, DoctorProfile, Patient, Consultation, ClinicalInput, PredictionRun,
                     PredictionOutput, EnrichmentResult, ModelVersion, DoctorReview,
                     ReviewDecision, Prescription, Approval, InformationRequest)
from .api import body, envelope, expected_version, consultation_view, audit

review_api = Blueprint("review", __name__)
SNAPSHOT_VERSION = "doctor-approval-v1"
PLACEHOLDER = "PENDING_DOCTOR_REVIEW"


@review_api.before_request
def limit_review_body():
    request.max_content_length = 128 * 1024


@review_api.after_request
def private_review_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def checksum(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def locked(query):
    return query.with_for_update().execution_options(populate_existing=True)


def doctor_case(consultation_id):
    item = db.session.scalar(locked(select(Consultation).where(Consultation.id == consultation_id)))
    # Authentication's earlier read may be stale after waiting for the case lock.
    user = db.session.scalar(locked(select(User).where(User.id == g.current_user.id)))
    if user is None or not user.active:
        raise ApiError("ACCOUNT_INACTIVE", "Account is unavailable", 401)
    if user.role.code != "DOCTOR":
        raise ApiError("FORBIDDEN", "Operation is not permitted", 403)
    if item is None or item.assigned_doctor_id != user.id:
        raise ApiError("NOT_FOUND", "Consultation was not found", 404)
    profile = db.session.scalar(locked(select(DoctorProfile).where(DoctorProfile.user_id == user.id)))
    if profile is None or profile.verified_at is None or profile.verified_by_id is None:
        raise ApiError("DOCTOR_UNVERIFIED", "Verified doctor authority is required", 403)
    return item


def pending(item):
    if item.state != "PENDING_DOCTOR_REVIEW":
        raise ApiError("INVALID_STATE", "Consultation is not pending doctor review", 409)


def positive(value, name, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ApiError("INVALID_FIELD", f"{name} must be a valid integer", 422)
    return value


def bounded_text(value, name, limit, *, blank=False):
    if not isinstance(value, str) or len(value) > limit or (not blank and not value.strip()):
        raise ApiError("INVALID_FIELD", f"{name} is invalid", 422)
    if value.strip() == PLACEHOLDER:
        raise ApiError("INVALID_FIELD", "A review placeholder is not doctor-authored content", 422)
    return value


def exact_fields(payload, required, optional=()):
    if set(payload) - (set(required) | set(optional)) or set(required) - set(payload):
        raise ApiError("INVALID_FIELD", "Request fields do not match the review contract", 422)


def source_context(item):
    """Read a complete, current Phase 5 result; no fallback categories or engines."""
    revision = db.session.scalar(locked(select(ClinicalInput).where(
        ClinicalInput.consultation_id == item.id, ClinicalInput.revision == item.current_input_revision)))
    if revision is None or revision.submitted_at is None:
        raise ApiError("SOURCE_UNAVAILABLE", "A submitted input revision is required", 409)
    # Lock the input's run range, including gaps on MySQL. Future run writers must
    # also acquire the consultation lock; no run replacement may race approval.
    runs = db.session.scalars(locked(select(PredictionRun).where(PredictionRun.input_id == revision.id)
        .order_by(PredictionRun.completed_at.desc(), PredictionRun.created_at.desc(), PredictionRun.id.desc()))).all()
    run = next((row for row in runs if row.status == "SUCCEEDED"), None)
    if run is None or run.started_at is None or run.completed_at is None or run.failure_code is not None:
        raise ApiError("SOURCE_UNAVAILABLE", "A complete successful prediction is required", 409)
    outputs = db.session.scalars(locked(select(PredictionOutput).where(PredictionOutput.prediction_run_id == run.id))).all()
    engines = db.session.scalars(locked(select(EnrichmentResult).where(EnrichmentResult.prediction_run_id == run.id))).all()
    model = db.session.scalar(locked(select(ModelVersion).where(ModelVersion.id == run.model_version_id)))
    raw = {row.target_code: deepcopy(row.raw_result) for row in outputs}
    required_keys = {
        TARGETS[0]: {"reasoning"},
        TARGETS[1]: {"focus", "actions", "dietary_changes", "wellness_tips", "avoid", "reasoning"},
        TARGETS[2]: {"focus", "duration", "poses", "pranayama", "meditation", "benefits", "precautions", "reasoning"},
        TARGETS[3]: {"reasoning"},
    }
    valid = (set(raw) == set(TARGETS) and len(outputs) == len(TARGETS) and len(engines) == 1
             and engines[0].engine_name == "v17-deterministic" and engines[0].engine_version == SOURCE_SHA256
             and engines[0].status == "SUCCEEDED" and engines[0].failure_code is None
             and isinstance(engines[0].result, dict) and set(engines[0].result) == set(TARGETS)
             and model is not None and model.checksum == MODEL_SHA256 and model.version == PIPELINE_VERSION
             and isinstance(model.evidence, dict) and model.evidence.get("sourceChecksum") == SOURCE_SHA256
             and model.evidence.get("adapterVersion") == ADAPTER_VERSION and bool(model.runtime_reference))
    if valid:
        for target in TARGETS:
            value, enrichment = raw[target], engines[0].result[target]
            valid = (isinstance(value, dict) and isinstance(value.get("category"), str) and bool(value["category"].strip())
                     and set(value) <= {"category", "confidence"} and isinstance(enrichment, dict)
                     and set(enrichment) == required_keys[target] and isinstance(enrichment.get("reasoning"), str)
                     and bool(enrichment["reasoning"].strip()))
            if not valid:
                break
    if not valid:
        raise ApiError("INCOMPLETE_INFERENCE", "Verified prediction and enrichment records are incomplete", 409)
    snapshot = {
        "input": {"id": revision.id, "revision": revision.revision, "schemaVersion": revision.schema_version,
                  "clinicalInput": deepcopy(revision.payload), "provenance": deepcopy(revision.provenance),
                  "actorId": revision.actor_id, "submittedAt": revision.submitted_at.isoformat(),
                  "verifiedById": revision.verified_by_id,
                  "verifiedAt": revision.verified_at.isoformat() if revision.verified_at else None},
        "prediction": {"id": run.id, "status": run.status, "startedAt": run.started_at.isoformat(),
                       "completedAt": run.completed_at.isoformat(), "originalOutputs": raw},
        "enrichment": {"id": engines[0].id, "engine": engines[0].engine_name,
                       "version": engines[0].engine_version, "status": engines[0].status,
                       "result": deepcopy(engines[0].result)},
        "modelProvenance": {"id": model.id, "checksum": model.checksum, "pipelineVersion": model.version,
                            "adapterVersion": ADAPTER_VERSION, "sourceChecksum": SOURCE_SHA256,
                            "evidenceChecksum": checksum(model.evidence),
                            "runtimeReferenceChecksum": checksum(model.runtime_reference)},
    }
    try:
        checksum(snapshot)
    except (TypeError, ValueError):
        raise ApiError("INCOMPLETE_INFERENCE", "Stored inference is not a valid snapshot", 409) from None
    return snapshot


def reviews_for(item):
    rows = db.session.scalars(locked(select(DoctorReview).where(DoctorReview.consultation_id == item.id)
        .order_by(DoctorReview.revision.desc()))).all()
    if any(row.revision is None for row in rows):
        raise ApiError("LEGACY_REVIEW_UNVERIFIED", "Historical review evidence requires reconciliation", 409)
    return rows


def decisions_from(payload):
    values = payload.get("decisions")
    if not isinstance(values, list) or len(values) > len(TARGETS):
        raise ApiError("INVALID_DECISIONS", "Decisions must be a bounded target array", 422)
    decisions = {}
    for value in values:
        if not isinstance(value, dict):
            raise ApiError("INVALID_DECISIONS", "Each decision must be an object", 422)
        exact_fields(value, {"targetCode", "action"}, {"content", "reason"})
        target, action = value["targetCode"], value["action"]
        if not isinstance(target, str) or target not in TARGETS or target in decisions or action not in ("ACCEPT", "EDIT", "OVERRIDE"):
            raise ApiError("INVALID_DECISIONS", "Decision target or action is invalid", 422)
        if action == "ACCEPT":
            if "content" in value or "reason" in value:
                raise ApiError("INVALID_DECISIONS", "ACCEPT cannot contain replacement content or a reason", 422)
            content = reason = None
        else:
            content = bounded_text(value.get("content"), "content", 16000)
            reason = bounded_text(value.get("reason"), "reason", 2000)
        decisions[target] = {"action": action, "content": content, "reason": reason}
    return decisions


def review_view(row):
    decisions = db.session.scalars(locked(select(ReviewDecision).where(ReviewDecision.doctor_review_id == row.id))).all()
    notes = db.session.scalar(locked(select(Prescription).where(Prescription.doctor_review_id == row.id)))
    return {"id": row.id, "revision": row.revision, "rowVersion": row.row_version, "status": row.status,
            "inputId": row.input_id, "predictionRunId": row.prediction_run_id, "doctorId": row.reviewer_id,
            "createdAt": row.created_at.isoformat(), "sourceChecksum": row.source_checksum,
            "completedAt": row.completed_at.isoformat() if row.completed_at else None,
            "decisions": [{"targetCode": value.target_code, "action": value.action,
                           "original": deepcopy(value.original_result), "content": deepcopy(value.content),
                           "reason": value.reason} for value in sorted(decisions, key=lambda x: x.target_code)],
            "careNotes": notes.care_notes if notes else None,
            "careNotesCompleted": notes.care_notes_completed if notes else False,
            "prescription": deepcopy(notes.medication) if notes else None}


def require_approval_policy(source):
    """No clinic-approved required-engine/context policy has been supplied.

    This is deliberately not configurable by an API caller or ML_ENABLED. Synthetic
    transaction tests mock this policy boundary and explicitly do not prove readiness.
    """
    raise ApiError("CLINICAL_REVIEW_POLICY_UNAPPROVED", "Clinical review policy evidence is unavailable", 503)


@review_api.get("/doctor/review-queue")
@require_auth("DOCTOR")
def queue():
    # Account/profile authority is also checked for an empty queue.
    user = db.session.scalar(locked(select(User).where(User.id == g.current_user.id)))
    profile = db.session.scalar(locked(select(DoctorProfile).where(DoctorProfile.user_id == user.id)))
    if not user.active or user.role.code != "DOCTOR" or profile is None or profile.verified_at is None:
        raise ApiError("FORBIDDEN", "Verified doctor authority is required", 403)
    if set(request.args) - {"cursor", "limit"}:
        raise ApiError("INVALID_FIELD", "Unknown queue filter", 422)
    limit = request.args.get("limit", "25")
    if len(limit) > 3 or not limit.isdecimal() or not 1 <= int(limit) <= 100:
        raise ApiError("INVALID_FIELD", "limit must be between 1 and 100", 422)
    cursor = request.args.get("cursor")
    if cursor is not None and (not cursor or len(cursor) > 36):
        raise ApiError("INVALID_FIELD", "Queue cursor is invalid", 422)
    query = select(Consultation).where(Consultation.assigned_doctor_id == user.id, Consultation.state == PLACEHOLDER)
    if cursor:
        query = query.where(Consultation.id > cursor)
    rows = db.session.scalars(query.order_by(Consultation.id).limit(int(limit) + 1)).all()
    return envelope({"items": [consultation_view(row) for row in rows[:int(limit)]],
                     "nextCursor": rows[int(limit) - 1].id if len(rows) > int(limit) else None})


@review_api.get("/consultations/<consultation_id>/review-context")
@require_auth("DOCTOR")
def context(consultation_id):
    item = doctor_case(consultation_id)
    pending(item)
    source = source_context(item)
    rows = reviews_for(item)
    return envelope({"consultation": consultation_view(item), "source": source,
                     "latestReview": review_view(rows[0]) if rows else None,
                     "approvalBlockers": ["CLINICAL_REVIEW_POLICY_UNAPPROVED"]})


@review_api.get("/consultations/<consultation_id>/review")
@require_auth("DOCTOR")
def get_review(consultation_id):
    item = doctor_case(consultation_id)
    if set(request.args) - {"revision"}:
        raise ApiError("INVALID_FIELD", "Unknown review filter", 422)
    rows = reviews_for(item)
    number = request.args.get("revision")
    if number is not None and (len(number) > 10 or not number.isdecimal() or int(number) < 1):
        raise ApiError("INVALID_FIELD", "Review revision is invalid", 422)
    row = next((row for row in rows if number is None or row.revision == int(number)), None)
    if row is None:
        raise ApiError("NOT_FOUND", "Review was not found", 404)
    return envelope({"review": review_view(row), "consultation": consultation_view(item)})


@review_api.post("/consultations/<consultation_id>/review")
@require_auth("DOCTOR")
def save_review(consultation_id):
    payload = body()
    exact_fields(payload, {"expectedRowVersion", "expectedReviewRevision", "inputRevision", "predictionRunId",
                           "decisions", "careNotes", "careNotesCompleted"}, {"prescription"})
    item = doctor_case(consultation_id)
    expected_version(payload, item)
    pending(item)
    source = source_context(item)
    positive(payload["inputRevision"], "inputRevision")
    if payload["inputRevision"] != item.current_input_revision or payload["predictionRunId"] != source["prediction"]["id"]:
        raise ApiError("STALE_SOURCE", "Review source has changed", 409)
    rows = reviews_for(item)
    last_revision = rows[0].revision if rows else 0
    if positive(payload["expectedReviewRevision"], "expectedReviewRevision", zero=True) != last_revision:
        raise ApiError("STALE_REVIEW", "Review revision has changed", 409)
    decisions = decisions_from(payload)
    care_notes = bounded_text(payload["careNotes"], "careNotes", 16000, blank=True)
    completed = payload["careNotesCompleted"]
    if type(completed) is not bool or (completed and not care_notes.strip()):
        raise ApiError("INVALID_FIELD", "Completed care notes must contain doctor-authored text", 422)
    prescription = payload.get("prescription")
    if prescription is not None:
        bounded_text(prescription, "prescription", 16000)
    if rows and rows[0].status in {"IN_PROGRESS", "COMPLETED"}:
        rows[0].status = "SUPERSEDED"
    elif rows and rows[0].status == "APPROVED":
        raise ApiError("INVALID_STATE", "Approved reviews require an amendment policy", 409)
    complete = set(decisions) == set(TARGETS) and completed
    # Every save creates a fresh immutable content revision, including notes.
    item.row_version += 1
    saved_at = utcnow()
    review = DoctorReview(consultation_id=item.id, input_id=source["input"]["id"],
        prediction_run_id=source["prediction"]["id"], reviewer_id=g.current_user.id,
        revision=last_revision + 1, expected_consultation_version=item.row_version,
        source_snapshot=source, source_checksum=checksum(source),
        status="COMPLETED" if complete else "IN_PROGRESS", created_at=saved_at,
        completed_at=saved_at if complete else None)
    db.session.add(review)
    db.session.flush()
    for target, decision in decisions.items():
        db.session.add(ReviewDecision(doctor_review_id=review.id, target_code=target, **decision,
            original_result={"raw": source["prediction"]["originalOutputs"][target],
                             "enrichment": source["enrichment"]["result"][target]}))
    db.session.add(Prescription(doctor_review_id=review.id, care_notes=care_notes,
                               care_notes_completed=completed, medication=prescription))
    audit("DOCTOR_REVIEW_SAVED", "consultation", item.id, review.revision,
          {"reviewId": review.id, "inputRevision": item.current_input_revision, "predictionRunId": review.prediction_run_id})
    db.session.commit()
    return envelope({"review": review_view(review), "consultation": consultation_view(item)}, 201)


def approved_view(approval):
    if not isinstance(approval.snapshot, dict) or approval.snapshot.get("schemaVersion") != SNAPSHOT_VERSION:
        raise ApiError("LEGACY_APPROVAL_UNVERIFIED", "Approved snapshot evidence is unavailable", 503)
    if checksum(approval.snapshot) != approval.checksum:
        raise ApiError("APPROVAL_INTEGRITY_FAILURE", "Approved snapshot evidence is unavailable", 503)
    return {"id": approval.id, "version": approval.version, "approvedAt": approval.approved_at.isoformat(),
            "approvedContent": deepcopy(approval.snapshot["patientView"])}


@review_api.post("/consultations/<consultation_id>/approve")
@require_auth("DOCTOR")
def approve(consultation_id):
    payload = body()
    exact_fields(payload, {"expectedRowVersion", "reviewId", "reviewRevision"})
    positive(payload["expectedRowVersion"], "expectedRowVersion")
    positive(payload["reviewRevision"], "reviewRevision")
    if not isinstance(payload["reviewId"], str) or not payload["reviewId"] or len(payload["reviewId"]) > 36:
        raise ApiError("INVALID_FIELD", "reviewId is invalid", 422)
    key = request.headers.get("Idempotency-Key")
    if not key or not key.strip() or len(key) > 128:
        raise ApiError("INVALID_FIELD", "An idempotency key is required", 422)
    item = doctor_case(consultation_id)
    request_hash = checksum(payload)
    existing = db.session.scalar(locked(select(Approval).where(Approval.consultation_id == item.id,
        Approval.approver_id == g.current_user.id, Approval.idempotency_key == key)))
    if existing:
        if existing.request_checksum != request_hash:
            raise ApiError("IDEMPOTENCY_CONFLICT", "Idempotency key was used with another request", 409)
        return envelope({"approval": approved_view(existing)})
    expected_version(payload, item)
    pending(item)
    if db.session.scalar(locked(select(Approval).where(Approval.consultation_id == item.id))):
        raise ApiError("ALREADY_APPROVED", "Consultation already has an approval", 409)
    rows = reviews_for(item)
    review = rows[0] if rows else None
    if review is None or review.id != payload["reviewId"] or review.revision != payload["reviewRevision"]:
        raise ApiError("STALE_REVIEW", "The current review revision is required", 409)
    if review.reviewer_id != g.current_user.id or review.expected_consultation_version != item.row_version:
        raise ApiError("STALE_REVIEW", "Assignment or consultation changed after review", 409)
    if review.status != "COMPLETED":
        raise ApiError("INCOMPLETE_REVIEW", "Complete target decisions and care notes are required", 409)
    source = source_context(item)
    if (review.input_id != source["input"]["id"] or review.prediction_run_id != source["prediction"]["id"]
            or review.source_checksum != checksum(source) or review.source_snapshot != source):
        raise ApiError("STALE_SOURCE", "Input or prediction changed after review", 409)
    view = review_view(review)
    # Revalidate persisted decisions, not just the derived COMPLETED status.
    values = [{"targetCode": value["targetCode"], "action": value["action"],
               **({"content": value["content"], "reason": value["reason"]}
                  if value["action"] != "ACCEPT" or value["content"] is not None or value["reason"] is not None else {})}
              for value in view["decisions"]]
    decisions = decisions_from({"decisions": values})
    if set(decisions) != set(TARGETS) or not view["careNotesCompleted"] or not view["careNotes"]:
        raise ApiError("INCOMPLETE_REVIEW", "Complete target decisions and care notes are required", 409)
    bounded_text(view["careNotes"], "careNotes", 16000)
    if view["prescription"] is not None:
        bounded_text(view["prescription"], "prescription", 16000)
    for value in view["decisions"]:
        target = value["targetCode"]
        if value["original"] != {"raw": source["prediction"]["originalOutputs"][target],
                                  "enrichment": source["enrichment"]["result"][target]}:
            raise ApiError("STALE_SOURCE", "Decision source changed after review", 409)
    policy_evidence = require_approval_policy(source)
    now = utcnow()
    final_targets = {}
    for target, decision in decisions.items():
        final_targets[target] = ({"category": source["prediction"]["originalOutputs"][target]["category"],
                                  **deepcopy(source["enrichment"]["result"][target])}
                                 if decision["action"] == "ACCEPT" else {"text": decision["content"]})
    patient_view = {"consultationId": item.id, "inputRevision": item.current_input_revision,
                    "reviewRevision": review.revision, "doctorId": g.current_user.id,
                    "recommendations": final_targets, "careNotes": view["careNotes"],
                    "prescription": view["prescription"]}
    snapshot = {"schemaVersion": SNAPSHOT_VERSION, "consultationId": item.id, "patientId": item.patient_id,
                "approvedAt": now.isoformat(), "approverId": g.current_user.id,
                "source": source, "review": view, "policyEvidence": policy_evidence, "patientView": patient_view}
    approval = Approval(doctor_review_id=review.id, consultation_id=item.id, version=1,
        approver_id=g.current_user.id, snapshot=snapshot, checksum=checksum(snapshot), approved_at=now,
        idempotency_key=key, request_checksum=request_hash)
    db.session.add(approval)
    review.status = "APPROVED"
    item.state = "APPROVED"
    db.session.flush()
    audit("CONSULTATION_APPROVED", "consultation", item.id, item.current_input_revision,
          {"approvalId": approval.id, "reviewId": review.id, "reviewRevision": review.revision,
           "predictionRunId": review.prediction_run_id, "snapshotChecksum": approval.checksum})
    db.session.commit()
    return envelope({"approval": approved_view(approval)}, 201)


@review_api.get("/consultations/<consultation_id>/approved")
@require_auth("PATIENT", "DOCTOR")
def get_approved(consultation_id):
    if g.current_user.role.code == "DOCTOR":
        item = doctor_case(consultation_id)
    else:
        item = db.session.scalar(select(Consultation).join(Patient, Patient.id == Consultation.patient_id).where(
            Consultation.id == consultation_id, Patient.user_id == g.current_user.id))
        if item is None:
            raise ApiError("NOT_FOUND", "Consultation was not found", 404)
    if item.state != "APPROVED":
        raise ApiError("NOT_FOUND", "Approved content is unavailable", 404)
    approval = db.session.scalar(select(Approval).where(Approval.consultation_id == item.id)
                                 .order_by(Approval.version.desc()))
    if approval is None:
        raise ApiError("NOT_FOUND", "Approved content is unavailable", 404)
    return envelope({"approval": approved_view(approval)})


@review_api.post("/consultations/<consultation_id>/request-information")
@require_auth("DOCTOR")
def request_information(consultation_id):
    payload = body()
    exact_fields(payload, {"expectedRowVersion", "reason"}, {"requestedFields"})
    item = doctor_case(consultation_id)
    expected_version(payload, item)
    pending(item)
    source = source_context(item)
    reason = bounded_text(payload["reason"], "reason", 2000)
    fields = payload.get("requestedFields", [])
    if not isinstance(fields, list) or len(fields) > len(INPUTS) or any(not isinstance(field, str) or field not in INPUTS for field in fields) or len(set(fields)) != len(fields):
        raise ApiError("INVALID_FIELD", "Requested fields must be evidenced input identifiers", 422)
    record = InformationRequest(consultation_id=item.id, input_id=source["input"]["id"],
                               doctor_id=g.current_user.id, reason=reason, requested_fields=fields)
    db.session.add(record)
    for row in reviews_for(item):
        if row.status in {"IN_PROGRESS", "COMPLETED"}:
            row.status = "SUPERSEDED"
    item.state = "NEEDS_INFORMATION"
    db.session.flush()
    audit("INFORMATION_REQUESTED", "consultation", item.id, item.current_input_revision,
          {"informationRequestId": record.id})
    db.session.commit()
    return envelope({"consultation": consultation_view(item), "informationRequestId": record.id}, 201)


@review_api.get("/consultations/<consultation_id>/information-request")
@require_auth("PATIENT", "DOCTOR")
def get_information_request(consultation_id):
    from .api import patient_scope
    item = doctor_case(consultation_id) if g.current_user.role.code == "DOCTOR" else patient_scope(consultation_id)
    if item.state != "NEEDS_INFORMATION":
        raise ApiError("NOT_FOUND", "Information request is unavailable", 404)
    row = db.session.scalar(select(InformationRequest).where(InformationRequest.consultation_id == item.id)
                            .order_by(InformationRequest.created_at.desc(), InformationRequest.id.desc()))
    if row is None:
        raise ApiError("NOT_FOUND", "Information request is unavailable", 404)
    return envelope({"informationRequest": {"id": row.id, "reason": row.reason,
                     "requestedFields": row.requested_fields, "createdAt": row.created_at.isoformat()}})
