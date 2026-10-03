import pytest
from backend.app import create_app


@pytest.fixture
def app():
    return create_app({"TESTING": True, "DATABASE_URL": "sqlite://", "ML_ENABLED": "false", "JWT_SECRET": "synthetic-test-secret-at-least-32-characters", "COOKIE_SECURE": False})
