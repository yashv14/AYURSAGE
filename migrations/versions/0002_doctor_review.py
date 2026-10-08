"""Append-only doctor review revisions and approval idempotency.

Existing rows are preserved with null new evidence columns, never backfilled.
"""
import os
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import make_url

revision = "0002_doctor_review"
down_revision = "0001_platform"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("doctor_reviews", sa.Column("revision", sa.Integer(), nullable=True))
    op.add_column("doctor_reviews", sa.Column("source_snapshot", sa.JSON(), nullable=True))
    op.add_column("doctor_reviews", sa.Column("source_checksum", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_doctor_reviews_consultation_revision", "doctor_reviews", ["consultation_id", "revision"])
    op.create_check_constraint("positive_revision", "doctor_reviews", "revision IS NULL OR revision > 0")
    op.create_check_constraint("source_checksum_length", "doctor_reviews", "source_checksum IS NULL OR length(source_checksum) = 64")
    op.add_column("review_decisions", sa.Column("original_result", sa.JSON(), nullable=True))
    op.add_column("approvals", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("approvals", sa.Column("request_checksum", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_approvals_actor_key", "approvals", ["consultation_id", "approver_id", "idempotency_key"])
    op.create_check_constraint("request_checksum_length", "approvals", "request_checksum IS NULL OR length(request_checksum) = 64")
    op.create_table("information_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("consultation_id", sa.String(36), sa.ForeignKey("consultations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("input_id", sa.String(36), nullable=False),
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_fields", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["input_id", "consultation_id"], ["clinical_inputs.id", "clinical_inputs.consultation_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="reason_required"))
    op.create_index("ix_information_requests_consultation_id", "information_requests", ["consultation_id"])


def downgrade():
    url = make_url(os.environ["DATABASE_URL"])
    if os.environ.get("AYURSAGE_ALLOW_TEST_DOWNGRADE") != "1" or not url.database.startswith("ayursage_test_"):
        raise RuntimeError("Downgrade is restricted to disposable ayursage_test_ databases")
    op.drop_table("information_requests")
    op.drop_constraint(op.f("ck_approvals_request_checksum_length"), "approvals", type_="check")
    op.drop_constraint("uq_approvals_actor_key", "approvals", type_="unique")
    op.drop_column("approvals", "request_checksum")
    op.drop_column("approvals", "idempotency_key")
    op.drop_column("review_decisions", "original_result")
    op.drop_constraint(op.f("ck_doctor_reviews_source_checksum_length"), "doctor_reviews", type_="check")
    op.drop_constraint(op.f("ck_doctor_reviews_positive_revision"), "doctor_reviews", type_="check")
    op.drop_constraint("uq_doctor_reviews_consultation_revision", "doctor_reviews", type_="unique")
    for column in ("source_checksum", "source_snapshot", "revision"):
        op.drop_column("doctor_reviews", column)
