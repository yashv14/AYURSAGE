"""Flask application factory for the AYUR-SAGE API shell."""

from flask import Flask

from .health import health_blueprint


def create_app() -> Flask:
    """Create the Flask application without loading clinical or ML code."""
    app = Flask(__name__)
    app.register_blueprint(health_blueprint, url_prefix="/api/v1/health")
    return app
