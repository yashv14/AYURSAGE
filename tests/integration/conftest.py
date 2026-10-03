"""Create/drop only a schema newly owned by this test invocation."""
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app import create_app
from backend.app.database import db


@pytest.fixture(scope="module")
def mysql_app():
    server = os.environ.get("MYSQL_TEST_SERVER_URL")
    if not server:
        if os.environ.get("REQUIRE_MYSQL_TESTS") == "1":
            pytest.fail("MYSQL_TEST_SERVER_URL required by this run")
        pytest.skip("MYSQL_TEST_SERVER_URL not provided; MySQL evidence not established")
    url = make_url(server)
    if url.drivername != "mysql+pymysql" or url.database:
        pytest.fail("MYSQL_TEST_SERVER_URL must be mysql+pymysql with no database")
    name = "ayursage_test_" + uuid4().hex
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    created = False
    old_url = os.environ.get("DATABASE_URL")
    old_allow = os.environ.get("AYURSAGE_ALLOW_TEST_DOWNGRADE")
    app = None
    try:
        with engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"))
        created = True
        database_url = url.set(database=name).render_as_string(hide_password=False)
        os.environ["DATABASE_URL"] = database_url
        os.environ["AYURSAGE_ALLOW_TEST_DOWNGRADE"] = "1"
        command.upgrade(Config("alembic.ini"), "head")
        app = create_app({"TESTING": True, "DATABASE_URL": database_url, "ML_ENABLED": "false", "JWT_SECRET": "synthetic-test-secret-at-least-32-characters", "COOKIE_SECURE": False})
        yield app
    finally:
        if app:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        # DROP is legal only when our CREATE succeeded. Never reuse an existing schema.
        if created:
            with engine.connect() as connection:
                connection.execute(text(f"DROP DATABASE `{name}`"))
        engine.dispose()
        for key, value in (("DATABASE_URL", old_url), ("AYURSAGE_ALLOW_TEST_DOWNGRADE", old_allow)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
