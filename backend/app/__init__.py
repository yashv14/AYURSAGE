"""Flask application factory for the AYUR-SAGE API shell."""

from flask import Flask

from .health import health_blueprint
from .api import api
from .review import review_api
from .reports import reports_api
from .storage import configure_report_storage
from .commands import register_commands
from .config import database_options, environment
from .database import db, configure_engine
from .errors import register_errors
from .inference import DisabledInference
from pathlib import Path


def create_app(config=None) -> Flask:
    """Create the Flask application without loading clinical or ML code."""
    app = Flask(__name__)
    app.config.update(environment())
    if config:
        app.config.update(config)
    if str(app.config["ML_ENABLED"]).lower() != "false":
        raise ValueError("ML integration is unavailable; ML_ENABLED must be false")
    app.extensions["inference"] = DisabledInference(
        Path(__file__).resolve().parents[2] / "ml/artifacts/ayursage_model.pkl")
    if not app.config.get("JWT_SECRET") or len(app.config["JWT_SECRET"]) < 32:
        raise ValueError("JWT_SECRET must contain at least 32 characters")
    if not app.config.get("ALLOWED_ORIGINS"):
        raise ValueError("ALLOWED_ORIGINS must not be empty")
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["DATABASE_URL"]
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = database_options(
        app.config["DATABASE_URL"], testing=app.config.get("TESTING", False))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    from . import models  # noqa: F401 - register metadata without querying the DB
    with app.app_context():
        configure_engine(db.engine)
    register_errors(app)
    configure_report_storage(app)
    app.register_blueprint(health_blueprint, url_prefix="/api/v1/health")
    app.register_blueprint(api, url_prefix="/api/v1")
    app.register_blueprint(review_api, url_prefix="/api/v1")
    app.register_blueprint(reports_api, url_prefix="/api/v1")
    register_commands(app)
    return app
