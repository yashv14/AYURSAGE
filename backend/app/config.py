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
    return {"DATABASE_URL": os.environ.get("DATABASE_URL"),
            "ML_ENABLED": os.environ.get("ML_ENABLED", "false")}
