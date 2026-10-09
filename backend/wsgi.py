"""Gunicorn entry point. Schema changes are an explicit release operation."""
from backend.app import create_app

app = create_app()
