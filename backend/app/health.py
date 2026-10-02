"""Non-sensitive process health endpoints."""

from flask import Blueprint, jsonify

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get("/live")
def liveness():
    """Report that the web process can serve requests."""
    return jsonify(status="ok"), 200
