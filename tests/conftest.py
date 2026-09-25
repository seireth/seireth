"""Explicit disposable PostgreSQL databases; unit tests need no server."""

import os
from time import monotonic, sleep
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


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Avoid shared Windows temp directories with incompatible ownership."""
    if os.name == "nt" and config.option.basetemp is None:
        root = config.rootpath / "build"
        root.mkdir(exist_ok=True)
        config.option.basetemp = str(root / f"pytest-{uuid4().hex}")


@pytest.fixture
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
    try:
        migrate()
        yield db
    finally:
        worker.dispatcher.stop()
        db.engine.dispose()
        db.engine, db.SessionLocal = old_engine, old_factory
        settings.database_url = old_url
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def fake_docker(monkeypatch):
    from fake_docker import FakeDocker

    daemon = FakeDocker()
    daemon.install(monkeypatch)
    return daemon


@pytest.fixture
def wait_until():
    def wait(sample, predicate=bool, *, description, timeout=5, interval=0.01):
        deadline = monotonic() + timeout
        while True:
            value = sample()
            if predicate(value):
                return value
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AssertionError(
                    f"Timed out waiting for {description}; last value: {value!r}"
                )
            sleep(min(interval, remaining))

    return wait


@pytest.fixture
def finding_payload():
    return {
        "title": "Example",
        "severity": "low",
        "description": "Example description",
        "remediation": "Example remediation",
        "evidence": {"url": "http://demo-target:8080/", "observed": True},
    }


@pytest.fixture
def make_plugin():
    from app.plugins.base import Plugin, PluginManifest

    def make(plugin_id, analyze_plugin):
        return Plugin(
            PluginManifest(
                id=plugin_id,
                name=plugin_id.title(),
                description=f"Test {plugin_id} plugin",
            ),
            analyze_plugin,
        )

    return make
