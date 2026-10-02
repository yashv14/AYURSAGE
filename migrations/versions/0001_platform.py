"""Initial Phase 3 schema; no clinical or model seed data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
import os
from sqlalchemy.engine import make_url

revision = "0001_platform"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('model_versions',
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('checksum', sa.String(length=64), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('runtime_reference', sa.String(length=256), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('length(checksum) = 64', name=op.f('ck_model_versions_checksum_length')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_versions')),
    sa.UniqueConstraint('checksum', name=op.f('uq_model_versions_checksum')),
    sa.UniqueConstraint('object_key', name=op.f('uq_model_versions_object_key')),
    sa.UniqueConstraint('version', name=op.f('uq_model_versions_version'))
    )
    op.create_table('roles',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("code IN ('PATIENT','DOCTOR','ADMIN')", name=op.f('ck_roles_code_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('code', name=op.f('uq_roles_code'))
    )
    op.create_table('users',
    sa.Column('normalized_email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=512), nullable=False),
    sa.Column('role_id', sa.String(length=36), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('row_version > 0', name=op.f('ck_users_positive_version')),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_users_role_id_roles'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('normalized_email', name=op.f('uq_users_normalized_email'))
    )
    op.create_index(op.f('ix_users_role_id'), 'users', ['role_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('event', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=False),
    sa.Column('resource_id', sa.String(length=36), nullable=False),
    sa.Column('resource_revision', sa.Integer(), nullable=True),
    sa.Column('request_id', sa.String(length=36), nullable=False),
    sa.Column('safe_metadata', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_logs_actor_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_actor_id'), 'audit_logs', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_event'), 'audit_logs', ['event'], unique=False)
    op.create_index(op.f('ix_audit_logs_request_id'), 'audit_logs', ['request_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_id'), 'audit_logs', ['resource_id'], unique=False)
    op.create_table('doctor_profiles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('verified_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('verified_by_id', sa.String(length=36), nullable=True),
    sa.Column('verification_provenance', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('(verified_at IS NULL AND verified_by_id IS NULL) OR (verified_at IS NOT NULL AND verified_by_id IS NOT NULL)', name=op.f('ck_doctor_profiles_verification_pair')),
    sa.CheckConstraint('row_version > 0', name=op.f('ck_doctor_profiles_positive_version')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_doctor_profiles_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['verified_by_id'], ['users.id'], name=op.f('fk_doctor_profiles_verified_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doctor_profiles')),
    sa.UniqueConstraint('user_id', name=op.f('uq_doctor_profiles_user_id'))
    )
    op.create_table('patients',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('profile', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_patients_user_id_users'), ondelete='RESTRICT'),
    sa.CheckConstraint('row_version > 0', name=op.f('ck_patients_positive_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_patients')),
    sa.UniqueConstraint('user_id', name=op.f('uq_patients_user_id'))
    )
    op.create_table('refresh_sessions',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('revoked_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('replacement_id', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(['replacement_id'], ['refresh_sessions.id'], name=op.f('fk_refresh_sessions_replacement_id_refresh_sessions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_sessions_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_sessions')),
    sa.UniqueConstraint('replacement_id', name=op.f('uq_refresh_sessions_replacement_id')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_sessions_token_hash'))
    )
    op.create_index(op.f('ix_refresh_sessions_expires_at'), 'refresh_sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_sessions_user_id'), 'refresh_sessions', ['user_id'], unique=False)
    op.create_table('consultations',
    sa.Column('patient_id', sa.String(length=36), nullable=False),
    sa.Column('assigned_doctor_id', sa.String(length=36), nullable=True),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('current_input_revision', sa.Integer(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("state IN ('DRAFT','SUBMITTED','PENDING_DOCTOR_REVIEW','NEEDS_INFORMATION','APPROVED','REJECTED','CANCELLED')", name=op.f('ck_consultations_state_allowed')),
    sa.CheckConstraint('current_input_revision IS NULL OR current_input_revision > 0', name=op.f('ck_consultations_positive_revision')),
    sa.CheckConstraint('row_version > 0', name=op.f('ck_consultations_positive_version')),
    sa.ForeignKeyConstraint(['assigned_doctor_id'], ['users.id'], name=op.f('fk_consultations_assigned_doctor_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_consultations_patient_id_patients'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consultations'))
    )
    op.create_index(op.f('ix_consultations_assigned_doctor_id'), 'consultations', ['assigned_doctor_id'], unique=False)
    op.create_index(op.f('ix_consultations_patient_id'), 'consultations', ['patient_id'], unique=False)
    op.create_index(op.f('ix_consultations_state'), 'consultations', ['state'], unique=False)
    op.create_table('clinical_inputs',
    sa.Column('consultation_id', sa.String(length=36), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('schema_version', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('provenance', sa.JSON(), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=False),
    sa.Column('submitted_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('verified_by_id', sa.String(length=36), nullable=True),
    sa.Column('verified_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('revision > 0', name=op.f('ck_clinical_inputs_positive_revision')),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_clinical_inputs_actor_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['consultation_id'], ['consultations.id'], name=op.f('fk_clinical_inputs_consultation_id_consultations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['verified_by_id'], ['users.id'], name=op.f('fk_clinical_inputs_verified_by_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clinical_inputs')),
    sa.UniqueConstraint('consultation_id', 'revision', name=op.f('uq_clinical_inputs_consultation_id')),
    sa.UniqueConstraint('id', 'consultation_id', name=op.f('uq_clinical_inputs_id'))
    )
    op.create_index(op.f('ix_clinical_inputs_consultation_id'), 'clinical_inputs', ['consultation_id'], unique=False)
    op.create_foreign_key('fk_consultation_current_input', 'consultations', 'clinical_inputs',
                          ['id', 'current_input_revision'], ['consultation_id', 'revision'], ondelete='RESTRICT')
    op.create_table('file_metadata',
    sa.Column('consultation_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('media_type', sa.String(length=128), nullable=False),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('checksum', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.String(length=32), nullable=False),
    sa.Column('lifecycle_status', sa.String(length=32), nullable=False),
    sa.Column('scan_status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('byte_size >= 0', name=op.f('ck_file_metadata_nonnegative_size')),
    sa.CheckConstraint('length(checksum) = 64', name=op.f('ck_file_metadata_checksum_length')),
    sa.ForeignKeyConstraint(['consultation_id'], ['consultations.id'], name=op.f('fk_file_metadata_consultation_id_consultations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_file_metadata_owner_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_file_metadata')),
    sa.UniqueConstraint('object_key', name=op.f('uq_file_metadata_object_key'))
    )
    op.create_index(op.f('ix_file_metadata_consultation_id'), 'file_metadata', ['consultation_id'], unique=False)
    op.create_table('prediction_runs',
    sa.Column('input_id', sa.String(length=36), nullable=False),
    sa.Column('model_version_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('request_id', sa.String(length=36), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('started_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('completed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name=op.f('ck_prediction_runs_status_allowed')),
    sa.ForeignKeyConstraint(['input_id'], ['clinical_inputs.id'], name=op.f('fk_prediction_runs_input_id_clinical_inputs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], name=op.f('fk_prediction_runs_model_version_id_model_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prediction_runs')),
    sa.UniqueConstraint('id', 'input_id', name=op.f('uq_prediction_runs_id')),
    sa.UniqueConstraint('input_id', 'idempotency_key', name=op.f('uq_prediction_runs_input_id'))
    )
    op.create_index(op.f('ix_prediction_runs_input_id'), 'prediction_runs', ['input_id'], unique=False)
    op.create_index(op.f('ix_prediction_runs_status'), 'prediction_runs', ['status'], unique=False)
    op.create_table('doctor_reviews',
    sa.Column('consultation_id', sa.String(length=36), nullable=False),
    sa.Column('input_id', sa.String(length=36), nullable=False),
    sa.Column('prediction_run_id', sa.String(length=36), nullable=False),
    sa.Column('reviewer_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('expected_consultation_version', sa.Integer(), nullable=False),
    sa.Column('completed_at', mysql.DATETIME(fsp=6), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("status IN ('IN_PROGRESS','COMPLETED','APPROVED','SUPERSEDED')", name=op.f('ck_doctor_reviews_status_allowed')),
    sa.CheckConstraint('expected_consultation_version > 0', name=op.f('ck_doctor_reviews_positive_expected_version')),
    sa.CheckConstraint('row_version > 0', name=op.f('ck_doctor_reviews_positive_version')),
    sa.ForeignKeyConstraint(['consultation_id'], ['consultations.id'], name=op.f('fk_doctor_reviews_consultation_id_consultations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['input_id', 'consultation_id'], ['clinical_inputs.id', 'clinical_inputs.consultation_id'], name=op.f('fk_doctor_reviews_input_id_clinical_inputs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['prediction_run_id', 'input_id'], ['prediction_runs.id', 'prediction_runs.input_id'], name=op.f('fk_doctor_reviews_prediction_run_id_prediction_runs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], name=op.f('fk_doctor_reviews_reviewer_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_doctor_reviews')),
    sa.UniqueConstraint('id', 'consultation_id', name=op.f('uq_doctor_reviews_id'))
    )
    op.create_index(op.f('ix_doctor_reviews_consultation_id'), 'doctor_reviews', ['consultation_id'], unique=False)
    op.create_index(op.f('ix_doctor_reviews_reviewer_id'), 'doctor_reviews', ['reviewer_id'], unique=False)
    op.create_table('enrichment_results',
    sa.Column('prediction_run_id', sa.String(length=36), nullable=False),
    sa.Column('engine_name', sa.String(length=64), nullable=False),
    sa.Column('engine_version', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','FAILED')", name=op.f('ck_enrichment_results_status_allowed')),
    sa.ForeignKeyConstraint(['prediction_run_id'], ['prediction_runs.id'], name=op.f('fk_enrichment_results_prediction_run_id_prediction_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_enrichment_results')),
    sa.UniqueConstraint('prediction_run_id', 'engine_name', 'engine_version', name=op.f('uq_enrichment_results_prediction_run_id'))
    )
    op.create_index(op.f('ix_enrichment_results_prediction_run_id'), 'enrichment_results', ['prediction_run_id'], unique=False)
    op.create_table('prediction_outputs',
    sa.Column('prediction_run_id', sa.String(length=36), nullable=False),
    sa.Column('target_code', sa.String(length=128), nullable=False),
    sa.Column('raw_result', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.ForeignKeyConstraint(['prediction_run_id'], ['prediction_runs.id'], name=op.f('fk_prediction_outputs_prediction_run_id_prediction_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prediction_outputs')),
    sa.UniqueConstraint('prediction_run_id', 'target_code', name=op.f('uq_prediction_outputs_prediction_run_id'))
    )
    op.create_index(op.f('ix_prediction_outputs_prediction_run_id'), 'prediction_outputs', ['prediction_run_id'], unique=False)
    op.create_table('approvals',
    sa.Column('doctor_review_id', sa.String(length=36), nullable=False),
    sa.Column('consultation_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('approver_id', sa.String(length=36), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('checksum', sa.String(length=64), nullable=False),
    sa.Column('approved_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('length(checksum) = 64', name=op.f('ck_approvals_checksum_length')),
    sa.CheckConstraint('version > 0', name=op.f('ck_approvals_positive_version')),
    sa.ForeignKeyConstraint(['approver_id'], ['users.id'], name=op.f('fk_approvals_approver_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['consultation_id'], ['consultations.id'], name=op.f('fk_approvals_consultation_id_consultations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['doctor_review_id', 'consultation_id'], ['doctor_reviews.id', 'doctor_reviews.consultation_id'], name=op.f('fk_approvals_doctor_review_id_doctor_reviews'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals')),
    sa.UniqueConstraint('consultation_id', 'version', name=op.f('uq_approvals_consultation_id')),
    sa.UniqueConstraint('doctor_review_id', name=op.f('uq_approvals_doctor_review_id'))
    )
    op.create_table('prescriptions',
    sa.Column('doctor_review_id', sa.String(length=36), nullable=False),
    sa.Column('care_notes', sa.Text(), nullable=False),
    sa.Column('care_notes_completed', sa.Boolean(), nullable=False),
    sa.Column('medication', sa.JSON(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint('care_notes_completed = 0 OR length(trim(care_notes)) > 0', name=op.f('ck_prescriptions_completed_notes')),
    sa.ForeignKeyConstraint(['doctor_review_id'], ['doctor_reviews.id'], name=op.f('fk_prescriptions_doctor_review_id_doctor_reviews'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prescriptions')),
    sa.UniqueConstraint('doctor_review_id', name=op.f('uq_prescriptions_doctor_review_id'))
    )
    op.create_table('review_decisions',
    sa.Column('doctor_review_id', sa.String(length=36), nullable=False),
    sa.Column('target_code', sa.String(length=128), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('content', sa.JSON(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("action = 'ACCEPT' OR (reason IS NOT NULL AND length(trim(reason)) > 0 AND content IS NOT NULL AND lower(JSON_TYPE(content)) <> 'null')", name=op.f('ck_review_decisions_change_requires_reason')),
    sa.CheckConstraint("action IN ('ACCEPT','EDIT','OVERRIDE')", name=op.f('ck_review_decisions_action_allowed')),
    sa.ForeignKeyConstraint(['doctor_review_id'], ['doctor_reviews.id'], name=op.f('fk_review_decisions_doctor_review_id_doctor_reviews'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_decisions')),
    sa.UniqueConstraint('doctor_review_id', 'target_code', name=op.f('uq_review_decisions_doctor_review_id'))
    )
    op.create_index(op.f('ix_review_decisions_doctor_review_id'), 'review_decisions', ['doctor_review_id'], unique=False)
    op.create_table('reports',
    sa.Column('approval_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('file_id', sa.String(length=36), nullable=True),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False),
    sa.CheckConstraint("status <> 'READY' OR file_id IS NOT NULL", name=op.f('ck_reports_ready_requires_file')),
    sa.CheckConstraint("status IN ('PENDING','GENERATING','READY','FAILED')", name=op.f('ck_reports_status_allowed')),
    sa.CheckConstraint('retry_count >= 0', name=op.f('ck_reports_nonnegative_retries')),
    sa.CheckConstraint('row_version > 0', name=op.f('ck_reports_positive_version')),
    sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], name=op.f('fk_reports_approval_id_approvals'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['file_id'], ['file_metadata.id'], name=op.f('fk_reports_file_id_file_metadata'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports')),
    sa.UniqueConstraint('approval_id', 'version', name=op.f('uq_reports_approval_id')),
    sa.UniqueConstraint('file_id', name=op.f('uq_reports_file_id')),
    sa.UniqueConstraint('object_key', name=op.f('uq_reports_object_key'))
    )
    op.create_index(op.f('ix_reports_approval_id'), 'reports', ['approval_id'], unique=False)
    op.create_index(op.f('ix_reports_status'), 'reports', ['status'], unique=False)

def downgrade():
    url = make_url(os.environ["DATABASE_URL"])
    if os.environ.get("AYURSAGE_ALLOW_TEST_DOWNGRADE") != "1" or not url.database.startswith("ayursage_test_"):
        raise RuntimeError("Downgrade is restricted to disposable ayursage_test_ databases")
    op.drop_constraint('fk_consultation_current_input', 'consultations', type_='foreignkey')
    op.drop_table('reports')
    op.drop_table('review_decisions')
    op.drop_table('prescriptions')
    op.drop_table('approvals')
    op.drop_table('prediction_outputs')
    op.drop_table('enrichment_results')
    op.drop_table('doctor_reviews')
    op.drop_table('prediction_runs')
    op.drop_table('file_metadata')
    op.drop_table('clinical_inputs')
    op.drop_table('consultations')
    op.drop_table('refresh_sessions')
    op.drop_table('patients')
    op.drop_table('doctor_profiles')
    op.drop_table('audit_logs')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('model_versions')
