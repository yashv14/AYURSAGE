"""Phase 4 identity and consultation HTTP API."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, make_response, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .auth import (access_token, check_password_hash, create_refresh, hash_password, normalize_email,
                   require_auth, require_refresh_proof, revoke_descendants, set_session_cookies, token_hash)
from .database import db, utcnow
from .errors import ApiError
from .models import AuditLog, ClinicalInput, Consultation, DoctorProfile, Patient, RefreshSession, Role, User

api = Blueprint("api", __name__)


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ApiError("INVALID_JSON", "A JSON object is required", 400)
    return value


def envelope(data, status=200):
    return jsonify(data=data, requestId=g.request_id), status


def user_view(user):
    return {"id": user.id, "email": user.normalized_email, "role": user.role.code,
            "active": user.active, "rowVersion": user.row_version}


def patient_view(patient):
    return {"id": patient.id, "profile": patient.profile, "rowVersion": patient.row_version}


def consultation_view(item, include_input=False):
    value = {"id": item.id, "state": item.state, "rowVersion": item.row_version,
             "currentInputRevision": item.current_input_revision,
             "assignedDoctorId": item.assigned_doctor_id}
    if include_input and item.current_input_revision:
        revision = next((x for x in item.inputs if x.revision == item.current_input_revision), None)
        if revision:
            value["currentInput"] = {"revision": revision.revision, "schemaVersion": revision.schema_version,
                                     "clinicalInput": revision.payload, "provenance": revision.provenance}
    return value


def audit(event, resource_type, resource_id, revision=None, metadata=None, actor=None):
    db.session.add(AuditLog(actor_id=(actor or getattr(g, "current_user", None)).id if (actor or getattr(g, "current_user", None)) else None,
                            event=event, resource_type=resource_type, resource_id=resource_id,
                            resource_revision=revision, request_id=g.request_id, safe_metadata=metadata or {}))


def expected_version(payload, item):
    expected = payload.get("expectedRowVersion")
    if type(expected) is not int or expected < 1:
        raise ApiError("INVALID_FIELD", "expectedRowVersion must be a positive integer", 422)
    if expected != item.row_version:
        raise ApiError("STALE_VERSION", "Resource has changed", 409)


def patient_scope(consultation_id, doctor=False):
    item = db.session.get(Consultation, consultation_id)
    user = g.current_user
    allowed = False
    if item:
        if user.role.code == "PATIENT":
            allowed = item.patient.user_id == user.id
        elif doctor and user.role.code == "DOCTOR":
            allowed = item.assigned_doctor_id == user.id
    if not allowed:
        raise ApiError("NOT_FOUND", "Consultation was not found", 404)
    return item


@api.post("/auth/register")
def register():
    payload = body()
    if set(payload) - {"email", "password", "acceptedTermsVersion", "role"}:
        raise ApiError("UNKNOWN_FIELD", "Unknown field supplied", 422)
    if "role" in payload:
        raise ApiError("ROLE_ESCALATION_DENIED", "Public registration cannot select a role", 403)
    terms = payload.get("acceptedTermsVersion")
    if not isinstance(terms, str) or not terms.strip() or len(terms) > 64:
        raise ApiError("INVALID_FIELD", "acceptedTermsVersion is required", 422)
    role = db.session.scalar(select(Role).where(Role.code == "PATIENT"))
    if role is None:
        raise ApiError("SERVICE_NOT_CONFIGURED", "Registration is unavailable", 503)
    user = User(normalized_email=normalize_email(payload.get("email")), password_hash=hash_password(payload.get("password")), role=role)
    db.session.add(user)
    db.session.flush()
    patient = Patient(user_id=user.id, profile={})
    db.session.add(patient)
    audit("PATIENT_REGISTERED", "user", user.id, actor=user, metadata={"termsVersion": terms.strip()})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("EMAIL_UNAVAILABLE", "Email address is unavailable", 409) from None
    return envelope({"user": user_view(user)}, 201)


@api.post("/auth/login")
def login():
    payload = body()
    email = normalize_email(payload.get("email"))
    user = db.session.scalar(select(User).where(User.normalized_email == email))
    if user is None or not check_password_hash(user.password_hash, payload.get("password", "")) or not user.active:
        raise ApiError("INVALID_CREDENTIALS", "Email or password is invalid", 401)
    raw, _ = create_refresh(user)
    audit("SESSION_CREATED", "user", user.id, actor=user)
    db.session.commit()
    token, expires = access_token(user)
    response = make_response(envelope({"accessToken": token, "expiresAt": expires.isoformat(), "user": user_view(user)})[0], 200)
    set_session_cookies(response, raw)
    return response


@api.post("/auth/refresh")
def refresh():
    require_refresh_proof()
    raw = request.cookies.get("refresh_token")
    session = db.session.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash(raw or "")))
    if session is None:
        raise ApiError("INVALID_REFRESH_SESSION", "Refresh session is invalid", 401)
    if session.revoked_at is not None:
        revoke_descendants(session)
        audit("REFRESH_REUSE_DETECTED", "refresh_session", session.id, actor=session.user)
        db.session.commit()
        raise ApiError("REFRESH_REUSE", "Refresh session is invalid", 401)
    if session.expires_at <= utcnow() or not session.user.active:
        session.revoked_at = utcnow()
        db.session.commit()
        raise ApiError("INVALID_REFRESH_SESSION", "Refresh session is invalid", 401)
    new_raw, _ = create_refresh(session.user, session)
    audit("SESSION_ROTATED", "refresh_session", session.id, actor=session.user)
    db.session.commit()
    token, expires = access_token(session.user)
    response = make_response(envelope({"accessToken": token, "expiresAt": expires.isoformat()})[0], 200)
    set_session_cookies(response, new_raw)
    return response


@api.post("/auth/logout")
def logout():
    require_refresh_proof()
    raw = request.cookies.get("refresh_token")
    session = db.session.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash(raw or "")))
    if session:
        revoke_descendants(session)
        audit("SESSION_REVOKED", "refresh_session", session.id, actor=session.user)
        db.session.commit()
    response = make_response("", 204)
    set_session_cookies(response)
    return response


@api.get("/auth/me")
@require_auth()
def me():
    return envelope({"user": user_view(g.current_user)})


@api.get("/patients/me")
@require_auth("PATIENT")
def get_patient():
    patient = db.session.scalar(select(Patient).where(Patient.user_id == g.current_user.id))
    return envelope({"patient": patient_view(patient)})


@api.patch("/patients/me")
@require_auth("PATIENT")
def update_patient():
    payload = body()
    patient = db.session.scalar(select(Patient).where(Patient.user_id == g.current_user.id))
    expected_version(payload, patient)
    changes = payload.get("changes")
    allowed = {"displayName", "phone"}
    if not isinstance(changes, dict) or set(changes) - allowed:
        raise ApiError("INVALID_PROFILE_CHANGE", "Only approved non-clinical profile fields may be changed", 422)
    for value in changes.values():
        if value is not None and (not isinstance(value, str) or len(value) > 128):
            raise ApiError("INVALID_PROFILE_CHANGE", "Profile value is invalid", 422)
    patient.profile = {**patient.profile, **changes}
    audit("PATIENT_PROFILE_UPDATED", "patient", patient.id, patient.row_version + 1)
    db.session.commit()
    return envelope({"patient": patient_view(patient)})


@api.post("/consultations")
@require_auth("PATIENT")
def create_consultation():
    payload = body()
    if set(payload) - {"context"}:
        raise ApiError("UNKNOWN_FIELD", "Unknown field supplied", 422)
    if payload.get("context") not in (None, {}):
        raise ApiError("POLICY_UNRESOLVED", "Consultation context schema is not approved", 422)
    patient = db.session.scalar(select(Patient).where(Patient.user_id == g.current_user.id))
    item = Consultation(patient_id=patient.id, state="DRAFT")
    db.session.add(item); db.session.flush()
    audit("CONSULTATION_CREATED", "consultation", item.id, item.row_version)
    db.session.commit()
    return envelope({"consultation": consultation_view(item)}, 201)


@api.get("/consultations")
@require_auth("PATIENT", "DOCTOR")
def list_consultations():
    query = select(Consultation)
    if g.current_user.role.code == "PATIENT":
        patient = db.session.scalar(select(Patient).where(Patient.user_id == g.current_user.id))
        query = query.where(Consultation.patient_id == patient.id)
    else:
        query = query.where(Consultation.assigned_doctor_id == g.current_user.id)
    items = db.session.scalars(query.order_by(Consultation.created_at.desc()).limit(51)).all()
    return envelope({"items": [consultation_view(x) for x in items[:50]], "nextCursor": None})


@api.get("/consultations/<consultation_id>")
@require_auth("PATIENT", "DOCTOR")
def get_consultation(consultation_id):
    item = patient_scope(consultation_id, doctor=True)
    return envelope({"consultation": consultation_view(item, include_input=True)})


@api.put("/consultations/<consultation_id>/inputs")
@require_auth("PATIENT")
def put_input(consultation_id):
    payload = body(); item = patient_scope(consultation_id)
    expected_version(payload, item)
    if item.state not in {"DRAFT", "NEEDS_INFORMATION"}:
        raise ApiError("INVALID_STATE", "Consultation does not accept input", 409)
    if not isinstance(payload.get("schemaVersion"), str) or not payload["schemaVersion"].strip():
        raise ApiError("INVALID_FIELD", "schemaVersion is required", 422)
    if not isinstance(payload.get("clinicalInput"), dict) or not isinstance(payload.get("provenance"), dict):
        raise ApiError("INVALID_FIELD", "Clinical input and provenance must be opaque objects", 422)
    revision_number = max((x.revision for x in item.inputs), default=0) + 1
    revision = ClinicalInput(consultation_id=item.id, revision=revision_number,
                             schema_version=payload["schemaVersion"], payload=payload["clinicalInput"],
                             provenance=payload["provenance"], actor_id=g.current_user.id)
    db.session.add(revision)
    db.session.flush()
    item.current_input_revision = revision_number
    audit("CONSULTATION_INPUT_REVISED", "consultation", item.id, revision_number,
          {"schemaVersion": payload["schemaVersion"]})
    try:
        db.session.commit()
    except StaleDataError:
        db.session.rollback(); raise ApiError("STALE_VERSION", "Resource has changed", 409) from None
    return envelope({"inputRevision": {"id": revision.id, "revision": revision.revision},
                     "consultation": consultation_view(item)}, 201)


@api.post("/admin/doctors")
@require_auth("ADMIN")
def onboard_doctor():
    payload = body()
    if set(payload) - {"email", "password", "verificationProvenance"}:
        raise ApiError("UNKNOWN_FIELD", "Unknown field supplied", 422)
    provenance = payload.get("verificationProvenance")
    if not isinstance(provenance, dict) or not provenance:
        raise ApiError("INVALID_FIELD", "Verification provenance is required", 422)
    role = db.session.scalar(select(Role).where(Role.code == "DOCTOR"))
    user = User(normalized_email=normalize_email(payload.get("email")), password_hash=hash_password(payload.get("password")), role=role)
    db.session.add(user); db.session.flush()
    db.session.add(DoctorProfile(user_id=user.id, verified_at=utcnow(), verified_by_id=g.current_user.id,
                                 verification_provenance=provenance))
    audit("DOCTOR_ONBOARDED", "user", user.id, metadata={"verifiedBy": g.current_user.id})
    db.session.commit()
    return envelope({"user": user_view(user)}, 201)


@api.post("/admin/consultations/<consultation_id>/assignment")
@require_auth("ADMIN")
def assign_doctor(consultation_id):
    payload = body(); item = db.session.get(Consultation, consultation_id)
    if item is None: raise ApiError("NOT_FOUND", "Consultation was not found", 404)
    expected_version(payload, item)
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip(): raise ApiError("INVALID_FIELD", "Reason is required", 422)
    doctor = db.session.get(User, payload.get("doctorId"))
    profile = db.session.scalar(select(DoctorProfile).where(DoctorProfile.user_id == getattr(doctor, "id", None)))
    if doctor is None or not doctor.active or doctor.role.code != "DOCTOR" or profile is None or profile.verified_at is None:
        raise ApiError("INVALID_DOCTOR", "Doctor is not active and verified", 422)
    item.assigned_doctor_id = doctor.id
    audit("DOCTOR_ASSIGNED", "consultation", item.id, item.row_version + 1, {"reason": reason.strip(), "doctorId": doctor.id})
    db.session.commit()
    return envelope({"consultation": consultation_view(item)})
