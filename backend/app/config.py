"""Validated environment configuration without connection-string logging."""
import os

from sqlalchemy.engine import make_url


def database_options(value, *, testing=False):
    if not value:
        raise ValueError("DATABASE_URL is required")
    try:
        url = make_url(value)
    except Exception:
        raise ValueError("DATABASE_URL is invalid") from None
    if testing and url.drivername == "sqlite":
        return {}
    if url.drivername != "mysql+pymysql" or not url.database or not url.host or not url.username:
        raise ValueError("DATABASE_URL must specify a mysql+pymysql database, host and user")
    return {"pool_pre_ping": True, "pool_recycle": 1800, "hide_parameters": True,
            "connect_args": {"connect_timeout": 5, "read_timeout": 5, "write_timeout": 5}}


def environment():
    origins = {item.strip() for item in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if item.strip()}
    secret = os.environ.get("JWT_SECRET")
    return {"REPORT_STORAGE_BACKEND": os.environ.get("REPORT_STORAGE_BACKEND", "local"),
            "REPORT_LOCAL_ROOT": os.environ.get("REPORT_LOCAL_ROOT", "/workspace/ayursage-private-reports"),
            "REPORT_FONT_PATH": os.environ.get("REPORT_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            "AZURE_REPORT_ACCOUNT_URL": os.environ.get("AZURE_REPORT_ACCOUNT_URL"),
            "AZURE_REPORT_CONTAINER": os.environ.get("AZURE_REPORT_CONTAINER"),
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "ML_ENABLED": os.environ.get("ML_ENABLED", "false"),
            "JWT_SECRET": secret, "JWT_ISSUER": "ayursage-api",
            "ACCESS_TOKEN_SECONDS": int(os.environ.get("ACCESS_TOKEN_SECONDS", "900")),
            "REFRESH_TOKEN_SECONDS": int(os.environ.get("REFRESH_TOKEN_SECONDS", "1209600")),
            "COOKIE_SECURE": os.environ.get("COOKIE_SECURE", "true").lower() == "true",
            "ALLOWED_ORIGINS": origins}
