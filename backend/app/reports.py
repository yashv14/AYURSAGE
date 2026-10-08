"""Approval-bound reports; short DB claims surround transaction-free object IO."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from flask import Blueprint, current_app, g, request, send_file
from sqlalchemy import select

from .api import audit, body, envelope, patient_scope
from .auth import require_auth
from .database import db, utcnow
from .errors import ApiError
from .models import Approval, Report, FileMetadata, User, Patient, Consultation
from .review import approved_view, doctor_case, exact_fields, locked
from .report_pdf import render_pdf, TEMPLATE_VERSION, RenderError
from .storage import StorageError

reports_api = Blueprint("reports", __name__)
LEASE_SECONDS = 300


@reports_api.before_request
def limit_report_body():
    request.max_content_length = 4096


@reports_api.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def report_case(consultation_id):
    if g.current_user.role.code == "DOCTOR":
        item = doctor_case(consultation_id)
    else:
        item = patient_scope(consultation_id)
        # Re-read actor and ownership after the consultation lock, matching doctor scope.
        item = db.session.scalar(locked(select(Consultation).where(Consultation.id == item.id)))
        actor = db.session.scalar(locked(select(User).where(User.id == g.current_user.id)))
        patient = db.session.scalar(locked(select(Patient).where(Patient.id == item.patient_id)))
        if actor is None or not actor.active or actor.role.code != "PATIENT":
            raise ApiError("ACCOUNT_INACTIVE", "Account is unavailable", 401)
        if patient is None or patient.user_id != actor.id:
            raise ApiError("NOT_FOUND", "Consultation was not found", 404)
    if item.state != "APPROVED":
        raise ApiError("NOT_FOUND", "Approved report is unavailable", 404)
    return item


def eligible_approval(item, approval_id):
    approval = db.session.scalar(locked(select(Approval).where(Approval.id == approval_id,
                                                             Approval.consultation_id == item.id)))
    if approval is None:
        raise ApiError("NOT_FOUND", "Approved report is unavailable", 404)
    try:
        view = approved_view(approval)
    except (KeyError, ValueError, TypeError):
        raise ApiError("APPROVAL_INTEGRITY_FAILURE", "Approved snapshot evidence is unavailable", 503) from None
    snapshot = approval.snapshot
    if (not isinstance(view["approvedContent"], dict)
            or snapshot.get("consultationId") != item.id or snapshot.get("patientId") != item.patient_id
            or snapshot.get("approverId") != approval.approver_id
            or snapshot.get("approvedAt") != view["approvedAt"]
            or view["approvedContent"].get("consultationId") != item.id):
        raise ApiError("APPROVAL_INTEGRITY_FAILURE", "Approved snapshot evidence is unavailable", 503)
    return approval, view


def validate_binding(report, approval):
    if report.snapshot_checksum != approval.checksum or report.template_version != TEMPLATE_VERSION or report.version != TEMPLATE_VERSION:
        raise ApiError("REPORT_INTEGRITY_FAILURE", "Report provenance is unavailable", 503)


def report_view(report):
    return {"id": report.id, "approvalId": report.approval_id, "reportVersion": report.version,
            "templateVersion": report.template_version, "snapshotChecksum": report.snapshot_checksum,
            "status": report.status, "failureCode": report.failure_code,
            "retryCount": report.retry_count,
            "fileChecksum": report.file.checksum if report.file else None}


def scoped_report(report_id):
    report = db.session.get(Report, report_id)
    if report is None:
        raise ApiError("NOT_FOUND", "Report was not found", 404)
    item = report_case(report.approval.consultation_id)
    report = db.session.scalar(locked(select(Report).where(Report.id == report_id)))
    approval, _ = eligible_approval(item, report.approval_id)
    validate_binding(report, approval)
    return report, item


def verified_object(report):
    file = report.file
    if (report.status != "READY" or file is None or file.object_key != report.object_key
            or file.media_type != "application/pdf" or file.scope != "REPORT"
            or file.lifecycle_status != "READY" or file.consultation_id != report.approval.consultation_id
            or file.owner_id != report.approval.consultation.patient.user_id):
        raise ApiError("REPORT_UNAVAILABLE", "Report file is unavailable", 503)
    key, expected, size = report.object_key, file.checksum, file.byte_size
    db.session.commit()  # No storage IO under a database lock/transaction.
    try:
        data = current_app.extensions["report_storage"].read(key)
    except StorageError:
        raise ApiError("REPORT_STORAGE_UNAVAILABLE", "Report file is unavailable", 503) from None
    if len(data) != size or sha256(data).hexdigest() != expected or not data.startswith(b"%PDF-"):
        raise ApiError("REPORT_INTEGRITY_FAILURE", "Report file integrity failed", 503)
    return data


@reports_api.post("/consultations/<consultation_id>/reports")
@require_auth("PATIENT", "DOCTOR")
def generate_report(consultation_id):
    payload = body()
    exact_fields(payload, {"approvalId", "reportVersion"})
    if not isinstance(payload["approvalId"], str) or not 1 <= len(payload["approvalId"]) <= 36:
        raise ApiError("INVALID_FIELD", "approvalId is invalid", 422)
    if payload["reportVersion"] != TEMPLATE_VERSION:
        raise ApiError("INVALID_FIELD", "Unsupported report version", 422)
    # Database uniqueness of approval/version is the contract's equivalent to a key.
    item = report_case(consultation_id)
    approval, view = eligible_approval(item, payload["approvalId"])
    report = db.session.scalar(locked(select(Report).where(Report.approval_id == approval.id,
                                                         Report.version == TEMPLATE_VERSION)))
    first = report is None
    if first:
        report = Report(approval_id=approval.id, version=TEMPLATE_VERSION,
                        object_key="reports/" + uuid4().hex + ".pdf",
                        snapshot_checksum=approval.checksum, template_version=TEMPLATE_VERSION)
        db.session.add(report)
        db.session.flush()
    validate_binding(report, approval)
    if report.status == "READY":
        verified_object(report)
        # Recheck authorization after IO before returning a ready representation.
        report, _ = scoped_report(report.id)
        return envelope({"report": report_view(report)})
    if report.status == "GENERATING" and report.lease_expires_at and report.lease_expires_at > utcnow():
        raise ApiError("REPORT_GENERATING", "Report generation is in progress", 409)
    token = str(uuid4())
    if not first:
        report.retry_count += 1
    report.status, report.failure_code = "GENERATING", None
    report.generation_token = token
    report.lease_expires_at = utcnow() + timedelta(seconds=LEASE_SECONDS)
    report_id, key, snapshot_hash = report.id, report.object_key, report.snapshot_checksum
    owner_id = item.patient.user_id
    view = deepcopy(view)
    audit("REPORT_GENERATING", "report", report_id, metadata={"approvalId": approval.id})
    db.session.commit()
    try:
        # Test marker can only be selected by isolated server-side test configuration.
        data = render_pdf(view, report_id, current_app.config["REPORT_FONT_PATH"],
                          synthetic=bool(current_app.testing))
        storage = current_app.extensions["report_storage"]
        storage.put(key, data)
        if storage.read(key) != data:
            raise StorageError("Upload integrity failure")
    except (StorageError, RenderError, OSError):
        fail_attempt(report_id, token)
        raise ApiError("REPORT_GENERATION_FAILED", "Report generation is unavailable", 503) from None
    # Reacquire authority/approval locks and fence late or reclaimed workers.
    item = report_case(consultation_id)
    approval, _ = eligible_approval(item, payload["approvalId"])
    report = db.session.scalar(locked(select(Report).where(Report.id == report_id)))
    if report.generation_token != token or report.status != "GENERATING" or approval.checksum != snapshot_hash:
        raise ApiError("REPORT_GENERATING", "Report generation requires reconciliation", 409)
    file = FileMetadata(consultation_id=item.id, owner_id=owner_id, object_key=key,
        media_type="application/pdf", byte_size=len(data), checksum=sha256(data).hexdigest(),
        scope="REPORT", lifecycle_status="READY", scan_status="NOT_APPLICABLE")
    db.session.add(file)
    db.session.flush()
    report.file_id, report.status = file.id, "READY"
    report.generation_token, report.lease_expires_at = None, None
    audit("REPORT_READY", "report", report.id, metadata={"approvalId": approval.id, "fileChecksum": file.checksum})
    # On DB failure upload remains private at this recorded key. Lease retry verifies
    # identical bytes and reconciles metadata. Never delete after an ambiguous commit.
    db.session.commit()
    return envelope({"report": report_view(report)}, 201 if first else 200)


def fail_attempt(report_id, token):
    db.session.rollback()
    initial = db.session.get(Report, report_id)
    if initial is None:
        return
    # Keep consultation-first lock order even for failure/audit transactions.
    db.session.scalar(locked(select(Consultation).where(Consultation.id == initial.approval.consultation_id)))
    report = db.session.scalar(locked(select(Report).where(Report.id == report_id)))
    if report is not None and report.generation_token == token and report.status == "GENERATING":
        report.status, report.failure_code = "FAILED", "REPORT_GENERATION_FAILED"
        report.generation_token, report.lease_expires_at = None, None
        audit("REPORT_FAILED", "report", report.id)
        db.session.commit()


@reports_api.get("/reports/<report_id>")
@require_auth("PATIENT", "DOCTOR")
def get_report(report_id):
    report, _ = scoped_report(report_id)
    if report.status == "READY":
        verified_object(report)
        report, _ = scoped_report(report_id)
    return envelope({"report": report_view(report)})


@reports_api.get("/reports/<report_id>/download")
@require_auth("PATIENT", "DOCTOR")
def download_report(report_id):
    report, _ = scoped_report(report_id)
    data = verified_object(report)
    report, _ = scoped_report(report_id)
    audit("REPORT_DOWNLOADED", "report", report.id)
    db.session.commit()
    return send_file(BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=f"ayursage-report-{report.id}.pdf", conditional=False,
                     etag=False, max_age=0)
