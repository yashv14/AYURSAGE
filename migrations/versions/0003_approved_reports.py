"""Add approval-bound report provenance and recoverable generation leases."""
import os
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import make_url

revision = "0003_approved_reports"
down_revision = "0002_doctor_review"
branch_labels = None
depends_on = None


def upgrade():
    for name, type_ in (("snapshot_checksum", sa.String(64)), ("template_version", sa.String(64)),
                        ("generation_token", sa.String(36)), ("lease_expires_at", mysql.DATETIME(fsp=6))):
        op.add_column("reports", sa.Column(name, type_, nullable=True))
    op.create_check_constraint("snapshot_checksum_length", "reports",
                               "snapshot_checksum IS NULL OR length(snapshot_checksum) = 64")


def downgrade():
    url = make_url(os.environ["DATABASE_URL"])
    if os.environ.get("AYURSAGE_ALLOW_TEST_DOWNGRADE") != "1" or not url.database.startswith("ayursage_test_"):
        raise RuntimeError("Downgrade is restricted to disposable ayursage_test_ databases")
    op.drop_constraint(op.f("ck_reports_snapshot_checksum_length"), "reports", type_="check")
    for name in ("lease_expires_at", "generation_token", "template_version", "snapshot_checksum"):
        op.drop_column("reports", name)
