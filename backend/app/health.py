"""Non-sensitive process health endpoints."""

from flask import Blueprint, jsonify, g, current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import db

SCHEMA_REVISION = "0002_doctor_review"

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get("/live")
def liveness():
    """Report that the web process can serve requests."""
    return jsonify(status="ok"), 200


@health_blueprint.get("/ready")
def readiness():
    """Platform readiness is distinct from the permanently unavailable ML gate."""
    ready = False
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            ready = revision == [SCHEMA_REVISION]
    except SQLAlchemyError:
        pass
    return jsonify(data={"status": "ready" if ready else "unavailable",
                         "database": "ready" if ready else "unavailable",
                         "ml": "unavailable",
                         "clinicalApproval": "unavailable",
                         "approvalBlockers": ["CLINICAL_REVIEW_POLICY_UNAPPROVED"],
                         "mlBlockers": current_app.extensions["inference"].blockers},
                   requestId=g.request_id), 200 if ready else 503
