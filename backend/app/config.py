"""Validated environment configuration without connection-string logging."""
import os
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url


def database_options(value, *, testing=False, production=False):
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
    if production and not url.query.get("ssl_ca"):
        raise ValueError("Production database requires a trusted ssl_ca bundle")
    if production and url.query.get("ssl_verify_identity") != "true":
        raise ValueError("Production database requires ssl_verify_identity=true")
    if production and url.query.get("ssl_verify_cert") != "true":
        raise ValueError("Production database requires ssl_verify_cert=true")
    connect_args = {"connect_timeout": 5, "read_timeout": 5, "write_timeout": 5}
    if production:
        # SQLAlchemy nests ssl_ca in `ssl` but leaves the verify flags as top-level
        # driver arguments. PyMySQL then replaces `ssl`, discarding that CA unless
        # these three values are passed together directly to the driver.
        connect_args.update(ssl_ca=url.query["ssl_ca"], ssl_verify_cert=True,
                            ssl_verify_identity=True)
    return {"pool_pre_ping": True, "pool_recycle": 1800, "hide_parameters": True,
            "connect_args": connect_args}


def environment():
    origins = {item.strip() for item in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if item.strip()}
    secret = os.environ.get("JWT_SECRET")
    return {"PRODUCTION": os.environ.get("AYURSAGE_ENV", "development") == "production",
            "REPORT_STORAGE_BACKEND": os.environ.get("REPORT_STORAGE_BACKEND", "local"),
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


def validate_production(config):
    if not config.get("PRODUCTION"):
        return
    if config.get("REPORT_STORAGE_BACKEND") != "azure":
        raise ValueError("Production requires private Azure report storage")
    if not config.get("COOKIE_SECURE"):
        raise ValueError("Production requires secure cookies")
    if not config.get("JWT_SECRET") or len(config["JWT_SECRET"]) < 32:
        raise ValueError("Production requires JWT_SECRET of at least 32 characters")
    for origin in config.get("ALLOWED_ORIGINS", ()):
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Production origins must be HTTPS origins")
    database_options(config.get("DATABASE_URL"), production=True)
