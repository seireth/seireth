"""Explicit disposable PostgreSQL databases; unit tests need no server."""

import os
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from time import monotonic, sleep
from types import SimpleNamespace
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


def pytest_collection_modifyitems(items):
    for item in items:
        if "database" in item.fixturenames:
            item.add_marker(pytest.mark.database)


@contextmanager
def disposable_database():
    admin_url = os.environ.get("SEIRETH_TEST_ADMIN_URL")
    if not admin_url:
        pytest.fail(
            "Set SEIRETH_TEST_ADMIN_URL to a disposable PostgreSQL admin connection"
        )
    with ExitStack() as cleanup:
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        cleanup.callback(admin.dispose)
        name = "seireth_test_" + uuid4().hex
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))

        def drop():
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))

        cleanup.callback(drop)
        url = (
            make_url(admin_url).set(database=name).render_as_string(hide_password=False)
        )
        from app import db, worker
        from app.config import settings
        from app.migration import migrate

        old_engine, old_factory, old_url = (
            db.engine,
            db.SessionLocal,
            settings.database_url,
        )

        def restore():
            db.engine, db.SessionLocal = old_engine, old_factory
            settings.database_url = old_url

        cleanup.callback(restore)
        settings.database_url = url
        db.engine = db.create_runtime_engine(url)
        cleanup.callback(db.engine.dispose)
        db.SessionLocal = sessionmaker(db.engine, expire_on_commit=False)
        cleanup.callback(worker.dispatcher.stop)
        migrate()
        yield db


@pytest.fixture
def database_context():
    return disposable_database


@pytest.fixture
def database(database_context):
    with database_context() as db:
        yield db


@pytest.fixture
def assessment_graph(database):
    from app import models
    from app.config import settings

    def make(*, owner="local-development", plugins=None, status="queued"):
        with database.SessionLocal() as db:
            project = models.Project(name="test project", owner_actor=owner)
            db.add(project)
            db.flush()
            target = models.Target(
                project_id=project.id,
                name="demo",
                image=settings.docker_target_image,
                url="http://demo-target:8080/",
            )
            db.add(target)
            db.flush()
            scope = models.AuthorizationScope(
                project_id=project.id,
                target_id=target.id,
                allowed_url=target.url,
                expires_at=models.now() + timedelta(minutes=5),
            )
            db.add(scope)
            db.flush()
            assessment = models.Assessment(
                project_id=project.id,
                target_id=target.id,
                scope_id=scope.id,
                plugins=["security-headers"] if plugins is None else plugins,
                status=status,
            )
            db.add(assessment)
            db.commit()
            return SimpleNamespace(
                project=project, target=target, scope=scope, assessment=assessment
            )

    return make


@pytest.fixture
def fake_docker(monkeypatch):
    from fake_docker import FakeDocker

    daemon = FakeDocker()
    daemon.install(monkeypatch)
    yield daemon
    assert not daemon.unsupported_calls, daemon.unsupported_calls


@pytest.fixture
def execution_context():
    from threading import Event

    from app.execution import ExecutionContext

    return ExecutionContext(Event(), Event(), monotonic() + 5)


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
