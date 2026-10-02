"""Explicit migrations only; URL comes from environment, never from Git."""
import os

from alembic import context
from sqlalchemy import create_engine, pool, inspect, text

from backend.app.config import database_options
from backend.app.database import db, configure_engine
from backend.app import models  # noqa: F401

config = context.config
target_metadata = db.metadata
url = os.environ.get("DATABASE_URL")
options = database_options(url)
if "downgrade" in str(getattr(config.cmd_opts, "cmd", "")):
    from sqlalchemy.engine import make_url
    if os.environ.get("AYURSAGE_ALLOW_TEST_DOWNGRADE") != "1" or not make_url(url).database.startswith("ayursage_test_"):
        raise RuntimeError("Downgrade is restricted to disposable ayursage_test_ databases")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get("connection")
    engine = None
    if supplied is None:
        engine = create_engine(url, poolclass=pool.NullPool, **options)
        configure_engine(engine)
        supplied = engine.connect()
    try:
        # Initial migration must not be applied over existing unversioned data.
        tables = inspect(supplied).get_table_names()
        if tables and "alembic_version" not in tables:
            raise RuntimeError("Refusing to migrate a nonempty unversioned database")
        if "alembic_version" in tables and len(tables) > 1:
            versions = supplied.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if not versions:
                raise RuntimeError("Refusing to migrate a nonempty unversioned database")
        if engine is not None:
            supplied.commit()  # End inspection's autobegin before Alembic owns its transaction.
        context.configure(connection=supplied, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if engine is not None:
            supplied.close()
            engine.dispose()
