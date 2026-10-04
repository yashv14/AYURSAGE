"""Phase 2 storage boundaries. Clinical keys/labels remain opaque and unseeded."""
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import declared_attr
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from .database import db, UTCDateTime, utcnow


def fk(table, **kwargs):
    return db.Column(db.String(36), db.ForeignKey(f"{table}.id", ondelete="RESTRICT"), **kwargs)


def states(column, values):
    choices = ",".join(repr(value) for value in values.split())
    return CheckConstraint(f"{column} IN ({choices})", name=f"{column}_allowed")


class Record:
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at = db.Column(UTCDateTime(), nullable=False, default=utcnow)


class Versioned:
    row_version = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow)

    @declared_attr
    def __mapper_args__(cls):
        return {"version_id_col": cls.row_version}


class Role(Record, db.Model):
    __tablename__ = "roles"
    code = db.Column(db.String(32), nullable=False, unique=True)
    __table_args__ = (states("code", "PATIENT DOCTOR ADMIN"),)


class User(Record, Versioned, db.Model):
    __tablename__ = "users"
    normalized_email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(512), nullable=False)
    role_id = fk("roles", nullable=False, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    role = db.relationship(Role)
    __table_args__ = (CheckConstraint("row_version > 0", name="positive_version"),)


class DoctorProfile(Record, Versioned, db.Model):
    __tablename__ = "doctor_profiles"
    user_id = fk("users", nullable=False, unique=True)
    verified_at = db.Column(UTCDateTime())
    verified_by_id = fk("users")
    verification_provenance = db.Column(db.JSON)
    user = db.relationship(User, foreign_keys=[user_id])
    verified_by = db.relationship(User, foreign_keys=[verified_by_id])
    __table_args__ = (CheckConstraint("row_version > 0", name="positive_version"),
                     CheckConstraint("(verified_at IS NULL AND verified_by_id IS NULL) OR "
                                      "(verified_at IS NOT NULL AND verified_by_id IS NOT NULL)",
                                      name="verification_pair"),)


class Patient(Record, Versioned, db.Model):
    __tablename__ = "patients"
    user_id = fk("users", nullable=False, unique=True)
    profile = db.Column(db.JSON, nullable=False)
    user = db.relationship(User)
    __table_args__ = (CheckConstraint("row_version > 0", name="positive_version"),)


class Consultation(Record, Versioned, db.Model):
    __tablename__ = "consultations"
    patient_id = fk("patients", nullable=False, index=True)
    assigned_doctor_id = fk("users", index=True)
    state = db.Column(db.String(32), nullable=False, default="DRAFT", index=True)
    current_input_revision = db.Column(db.Integer)
    patient = db.relationship(Patient)
    assigned_doctor = db.relationship(User)
    inputs = db.relationship("ClinicalInput", back_populates="consultation", passive_deletes="all",
                             foreign_keys="ClinicalInput.consultation_id")
    __table_args__ = (states("state", "DRAFT SUBMITTED PENDING_DOCTOR_REVIEW NEEDS_INFORMATION APPROVED REJECTED CANCELLED"),
                      ForeignKeyConstraint(["id", "current_input_revision"],
                                           ["clinical_inputs.consultation_id", "clinical_inputs.revision"],
                                           name="fk_consultation_current_input", use_alter=True, ondelete="RESTRICT"),
                      CheckConstraint("row_version > 0", name="positive_version"),
                      CheckConstraint("current_input_revision IS NULL OR current_input_revision > 0", name="positive_revision"))


class ClinicalInput(Record, db.Model):
    __tablename__ = "clinical_inputs"
    consultation_id = fk("consultations", nullable=False, index=True)
    revision = db.Column(db.Integer, nullable=False)
    schema_version = db.Column(db.String(64), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    provenance = db.Column(db.JSON, nullable=False)
    actor_id = fk("users", nullable=False)
    submitted_at = db.Column(UTCDateTime())
    verified_by_id = fk("users")
    verified_at = db.Column(UTCDateTime())
    consultation = db.relationship(Consultation, back_populates="inputs", foreign_keys=[consultation_id])
    actor = db.relationship(User, foreign_keys=[actor_id])
    verified_by = db.relationship(User, foreign_keys=[verified_by_id])
    __table_args__ = (UniqueConstraint("consultation_id", "revision"),
                      UniqueConstraint("id", "consultation_id"),
                      CheckConstraint("revision > 0", name="positive_revision"))


class ModelVersion(Record, db.Model):
    __tablename__ = "model_versions"
    version = db.Column(db.String(64), nullable=False, unique=True)
    checksum = db.Column(db.String(64), nullable=False, unique=True)
    object_key = db.Column(db.String(512), nullable=False, unique=True)
    evidence = db.Column(db.JSON, nullable=False)
    runtime_reference = db.Column(db.String(256), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (CheckConstraint("length(checksum) = 64", name="checksum_length"),)


class PredictionRun(Record, db.Model):
    __tablename__ = "prediction_runs"
    input_id = fk("clinical_inputs", nullable=False, index=True)
    model_version_id = fk("model_versions", nullable=False)
    status = db.Column(db.String(16), nullable=False, default="PENDING", index=True)
    request_id = db.Column(db.String(36), nullable=False)
    idempotency_key = db.Column(db.String(128), nullable=False)
    started_at = db.Column(UTCDateTime())
    completed_at = db.Column(UTCDateTime())
    failure_code = db.Column(db.String(64))
    input = db.relationship(ClinicalInput)
    model_version = db.relationship(ModelVersion)
    outputs = db.relationship("PredictionOutput", back_populates="run", passive_deletes="all")
    __table_args__ = (UniqueConstraint("input_id", "idempotency_key"),
                      UniqueConstraint("id", "input_id"),
                      states("status", "PENDING RUNNING SUCCEEDED FAILED"))


class PredictionOutput(Record, db.Model):
    __tablename__ = "prediction_outputs"
    prediction_run_id = fk("prediction_runs", nullable=False, index=True)
    target_code = db.Column(db.String(128), nullable=False)
    raw_result = db.Column(db.JSON, nullable=False)
    run = db.relationship(PredictionRun, back_populates="outputs")
    __table_args__ = (UniqueConstraint("prediction_run_id", "target_code"),)


class EnrichmentResult(Record, db.Model):
    __tablename__ = "enrichment_results"
    prediction_run_id = fk("prediction_runs", nullable=False, index=True)
    engine_name = db.Column(db.String(64), nullable=False)
    engine_version = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(16), nullable=False)
    result = db.Column(db.JSON)
    failure_code = db.Column(db.String(64))
    run = db.relationship(PredictionRun)
    __table_args__ = (UniqueConstraint("prediction_run_id", "engine_name", "engine_version"),
                      states("status", "PENDING RUNNING SUCCEEDED FAILED"))


class DoctorReview(Record, Versioned, db.Model):
    __tablename__ = "doctor_reviews"
    consultation_id = fk("consultations", nullable=False, index=True)
    input_id = db.Column(db.String(36), nullable=False)
    prediction_run_id = db.Column(db.String(36), nullable=False)
    reviewer_id = fk("users", nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="IN_PROGRESS")
    expected_consultation_version = db.Column(db.Integer, nullable=False)
    completed_at = db.Column(UTCDateTime())
    consultation = db.relationship(Consultation)
    input = db.relationship(ClinicalInput, foreign_keys=[input_id], overlaps="consultation")
    run = db.relationship(PredictionRun, foreign_keys=[prediction_run_id], overlaps="input")
    reviewer = db.relationship(User)
    __table_args__ = (
        CheckConstraint("row_version > 0", name="positive_version"),
        ForeignKeyConstraint(["input_id", "consultation_id"], ["clinical_inputs.id", "clinical_inputs.consultation_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["prediction_run_id", "input_id"], ["prediction_runs.id", "prediction_runs.input_id"], ondelete="RESTRICT"),
        states("status", "IN_PROGRESS COMPLETED APPROVED SUPERSEDED"),
        UniqueConstraint("id", "consultation_id"),
        CheckConstraint("expected_consultation_version > 0", name="positive_expected_version"))


class ReviewDecision(Record, db.Model):
    __tablename__ = "review_decisions"
    doctor_review_id = fk("doctor_reviews", nullable=False, index=True)
    target_code = db.Column(db.String(128), nullable=False)
    action = db.Column(db.String(16), nullable=False)
    content = db.Column(db.JSON(none_as_null=True))
    reason = db.Column(db.Text)
    review = db.relationship(DoctorReview)
    __table_args__ = (UniqueConstraint("doctor_review_id", "target_code"),
                      states("action", "ACCEPT EDIT OVERRIDE"),
                      CheckConstraint("action = 'ACCEPT' OR (reason IS NOT NULL AND length(trim(reason)) > 0 AND content IS NOT NULL AND lower(JSON_TYPE(content)) <> 'null')", name="change_requires_reason"))


class Prescription(Record, db.Model):
    __tablename__ = "prescriptions"
    doctor_review_id = fk("doctor_reviews", nullable=False, unique=True)
    care_notes = db.Column(db.Text, nullable=False)
    care_notes_completed = db.Column(db.Boolean, nullable=False, default=False)
    medication = db.Column(db.JSON)
    review = db.relationship(DoctorReview)
    __table_args__ = (CheckConstraint("care_notes_completed = 0 OR length(trim(care_notes)) > 0", name="completed_notes"),)


class Approval(Record, db.Model):
    __tablename__ = "approvals"
    doctor_review_id = db.Column(db.String(36), nullable=False, unique=True)
    consultation_id = fk("consultations", nullable=False)
    version = db.Column(db.Integer, nullable=False)
    approver_id = fk("users", nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)
    checksum = db.Column(db.String(64), nullable=False)
    approved_at = db.Column(UTCDateTime(), nullable=False)
    review = db.relationship(DoctorReview, foreign_keys=[doctor_review_id], overlaps="consultation")
    consultation = db.relationship(Consultation, foreign_keys=[consultation_id])
    approver = db.relationship(User)
    __table_args__ = (UniqueConstraint("consultation_id", "version"),
                      ForeignKeyConstraint(["doctor_review_id", "consultation_id"],
                                           ["doctor_reviews.id", "doctor_reviews.consultation_id"], ondelete="RESTRICT"),
                      CheckConstraint("version > 0", name="positive_version"),
                      CheckConstraint("length(checksum) = 64", name="checksum_length"))


class FileMetadata(Record, db.Model):
    __tablename__ = "file_metadata"
    consultation_id = fk("consultations", nullable=False, index=True)
    owner_id = fk("users", nullable=False)
    object_key = db.Column(db.String(512), nullable=False, unique=True)
    media_type = db.Column(db.String(128), nullable=False)
    byte_size = db.Column(db.BigInteger, nullable=False)
    checksum = db.Column(db.String(64), nullable=False)
    scope = db.Column(db.String(32), nullable=False)
    lifecycle_status = db.Column(db.String(32), nullable=False)
    scan_status = db.Column(db.String(32), nullable=False)
    consultation = db.relationship(Consultation)
    owner = db.relationship(User)
    __table_args__ = (CheckConstraint("byte_size >= 0", name="nonnegative_size"),
                      CheckConstraint("length(checksum) = 64", name="checksum_length"))


class Report(Record, Versioned, db.Model):
    __tablename__ = "reports"
    approval_id = fk("approvals", nullable=False, index=True)
    version = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="PENDING", index=True)
    object_key = db.Column(db.String(512), nullable=False, unique=True)
    file_id = fk("file_metadata", unique=True)
    failure_code = db.Column(db.String(64))
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    approval = db.relationship(Approval)
    file = db.relationship(FileMetadata)
    __table_args__ = (UniqueConstraint("approval_id", "version"),
                      CheckConstraint("row_version > 0", name="positive_version"),
                      states("status", "PENDING GENERATING READY FAILED"),
                      CheckConstraint("retry_count >= 0", name="nonnegative_retries"),
                      CheckConstraint("status <> 'READY' OR file_id IS NOT NULL", name="ready_requires_file"))


class RefreshSession(Record, db.Model):
    __tablename__ = "refresh_sessions"
    user_id = fk("users", nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(UTCDateTime(), nullable=False, index=True)
    revoked_at = db.Column(UTCDateTime())
    replacement_id = fk("refresh_sessions", unique=True)
    user = db.relationship(User)
    replacement = db.relationship("RefreshSession", remote_side="RefreshSession.id")


class AuditLog(Record, db.Model):
    __tablename__ = "audit_logs"
    actor_id = fk("users", index=True)
    event = db.Column(db.String(64), nullable=False, index=True)
    resource_type = db.Column(db.String(64), nullable=False)
    resource_id = db.Column(db.String(36), nullable=False, index=True)
    resource_revision = db.Column(db.Integer)
    request_id = db.Column(db.String(36), nullable=False, index=True)
    safe_metadata = db.Column(db.JSON, nullable=False)
    actor = db.relationship(User)


# No cascade deletion: retention policy is unresolved. Approval and input immutability,
# role/assignment authority, target completeness and atomic processing are service
# transaction requirements in later phases, not satisfied by table definitions alone.


@event.listens_for(Session, "before_flush")
def preserve_immutable_history(session, flush_context, instances):
    for record in session.deleted:
        if isinstance(record, (ClinicalInput, PredictionRun, PredictionOutput, EnrichmentResult,
                               DoctorReview, ReviewDecision, Prescription, Approval, Report, AuditLog)):
            raise ValueError("Clinical history deletion is unavailable pending retention policy")
    for record in session.dirty:
        if not session.is_modified(record, include_collections=False):
            continue
        if isinstance(record, (Approval, AuditLog, Role)):
            raise ValueError("Immutable record cannot be changed")
        if isinstance(record, ClinicalInput):
            submitted = session.connection().execute(
                select(ClinicalInput.__table__.c.submitted_at).where(ClinicalInput.__table__.c.id == record.id)
            ).scalar()
            if submitted is not None:
                raise ValueError("Submitted input requires a new revision")
        if isinstance(record, PredictionOutput):
            raise ValueError("Persisted raw output cannot be changed")
        if isinstance(record, ModelVersion) and session.connection().execute(
            select(PredictionRun.id).where(PredictionRun.model_version_id == record.id).limit(1)
        ).first() is not None:
            raise ValueError("Used model provenance cannot be changed")
        if isinstance(record, EnrichmentResult):
            raise ValueError("Persisted enrichment cannot be changed")
