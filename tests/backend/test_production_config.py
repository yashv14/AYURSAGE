"""Production startup refuses unsafe configuration without touching patient data."""
import pytest
import ssl
import os
import pymysql
from sqlalchemy import create_engine

from backend.app.config import validate_production, database_options


SAFE = dict(PRODUCTION=True, REPORT_STORAGE_BACKEND="azure", COOKIE_SECURE=True,
            JWT_SECRET="synthetic-secret-0123456789-abcdefghijkl",
            ALLOWED_ORIGINS={"https://example.invalid"},
            DATABASE_URL="mysql+pymysql://synthetic:synthetic@db.example.invalid/ayursage?ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_cert=true&ssl_verify_identity=true")


@pytest.mark.parametrize("change", [
    {"REPORT_STORAGE_BACKEND": "local"},
    {"COOKIE_SECURE": False},
    {"ALLOWED_ORIGINS": {"http://example.invalid"}},
    {"JWT_SECRET": "short"},
    {"DATABASE_URL": "mysql+pymysql://synthetic:synthetic@db.example.invalid/ayursage"},
    {"DATABASE_URL": "mysql+pymysql://synthetic:synthetic@db.example.invalid/ayursage?ssl_verify_cert=true&ssl_verify_identity=true"},
])
def test_production_rejects_unsafe_config(change):
    with pytest.raises(ValueError):
        validate_production(SAFE | change)


def test_production_accepts_synthetic_safe_config():
    validate_production(SAFE)


@pytest.mark.skipif(os.name == "nt", reason="Linux production CA bundle path")
def test_mysql_driver_enables_ca_and_hostname_verification():
    engine = create_engine(SAFE["DATABASE_URL"])
    options = engine.dialect.create_connect_args(engine.url)[1]
    options.update(database_options(SAFE["DATABASE_URL"], production=True)["connect_args"])
    connection = pymysql.connections.Connection(defer_connect=True, **options)
    assert connection.ctx.verify_mode == ssl.CERT_REQUIRED
    assert connection.ctx.check_hostname is True
