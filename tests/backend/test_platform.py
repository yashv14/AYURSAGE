from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, IntegrityError

from backend.app import create_app
from backend.app.database import UTCDateTime, db


@pytest.mark.parametrize("url", [None, "invalid", "postgresql://user@localhost/app", "mysql+pymysql://"])
def test_invalid_configuration_does_not_leak_url(url):
    with pytest.raises(ValueError) as error:
        create_app({"DATABASE_URL": url})
    assert "user@" not in str(error.value)


def test_ml_cannot_be_enabled():
    with pytest.raises(ValueError, match="ML integration is unavailable"):
        create_app({"DATABASE_URL": "sqlite://", "TESTING": True, "ML_ENABLED": True})


def test_errors_and_ids_are_safe(app):
    @app.get("/broken")
    def broken():
        raise OperationalError("SELECT secret", {}, Exception("private-password"))

    client = app.test_client()
    response = client.get("/broken", headers={"X-Request-ID": "untrusted"})
    assert response.status_code == 503
    assert response.json["requestId"] != "untrusted"
    assert response.json["requestId"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text and "private-password" not in response.text
    missing = client.get("/missing")
    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "NOT_FOUND"
    assert missing.json["requestId"] != response.json["requestId"]


def test_database_error_without_driver_arguments_is_safe(app):
    @app.get("/database-error")
    def database_error():
        raise OperationalError("private SQL", {}, Exception())
    assert app.test_client().get("/database-error").status_code == 503


@pytest.mark.parametrize("exception", [IntegrityError("private SQL", {}, Exception("secret")),
                                       OperationalError("private SQL", {}, type("CheckViolation", (Exception,), {})(3819, "secret"))])
def test_database_conflicts_are_safe(app, exception):
    @app.get("/conflict")
    def conflict():
        raise exception
    response = app.test_client().get("/conflict")
    assert response.status_code == 409
    assert response.json["error"]["code"] == "CONFLICT"
    assert "secret" not in response.text and "SQL" not in response.text


def test_utc_type_rejects_naive_and_normalizes_offset():
    datatype = UTCDateTime()
    with pytest.raises(ValueError):
        datatype.process_bind_param(datetime(2026, 1, 1), None)
    value = datetime(2026, 1, 1, 6, tzinfo=timezone(timedelta(hours=6)))
    stored = datatype.process_bind_param(value, None)
    assert stored == datetime(2026, 1, 1)
    assert datatype.process_result_value(stored, None).tzinfo == timezone.utc


def test_readiness_requires_expected_schema(app):
    with app.app_context():
        db.session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        db.session.execute(text("INSERT INTO alembic_version VALUES ('wrong')"))
        db.session.commit()
    assert app.test_client().get("/api/v1/health/ready").status_code == 503
    with app.app_context():
        db.session.execute(text("UPDATE alembic_version SET version_num='0001_platform'"))
        db.session.commit()
    response = app.test_client().get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json["data"]["ml"] == "unavailable"
