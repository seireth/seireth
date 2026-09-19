"""Explicit disposable PostgreSQL databases; unit tests need no server."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

# Do not load operator settings into tests. This URL is never connected to unless
# a database fixture replaces it with a freshly created database.
os.environ.update(
    SEIRETH_API_HOST="127.0.0.1",
    SEIRETH_API_PORT="8000",
    SEIRETH_SANDBOX_BACKEND="inmemory",
    SEIRETH_DOCKER_TARGET_IMAGE="seireth/demo-target:local",
    SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES='["seireth/demo-target:local"]',
    SEIRETH_DATABASE_URL="postgresql+psycopg://unused:unused@127.0.0.1/unused",
)


@pytest.fixture(scope="session")
def database():
    admin_url = os.environ.get("SEIRETH_TEST_ADMIN_URL")
    if not admin_url:
        pytest.fail(
            "Set SEIRETH_TEST_ADMIN_URL to a disposable PostgreSQL admin connection"
        )
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = "seireth_test_" + uuid4().hex
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    from app import db, worker
    from app.config import settings
    from app.migration import migrate

    old_engine, old_factory, old_url = db.engine, db.SessionLocal, settings.database_url
    settings.database_url = url
    db.engine = create_engine(url, pool_pre_ping=True)
    db.SessionLocal = sessionmaker(db.engine, expire_on_commit=False)
    worker.engine, worker.SessionLocal = db.engine, db.SessionLocal
    try:
        migrate()
        yield db
    finally:
        worker.dispatcher.stop()
        db.engine.dispose()
        db.engine, db.SessionLocal = old_engine, old_factory
        worker.engine, worker.SessionLocal = old_engine, old_factory
        settings.database_url = old_url
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
