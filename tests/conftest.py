"""Explicit disposable PostgreSQL databases; unit tests need no server."""

import json
import os
from contextlib import ExitStack, contextmanager
from functools import partial
from importlib import import_module
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic_settings import DotEnvSettingsSource
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

# Keep explicit test switches, but discard operator environment settings.
for key in tuple(os.environ):
    if (
        key.startswith("SEIRETH_")
        and not key.startswith("SEIRETH_TEST_")
        and key != "SEIRETH_DOCKER_TESTS"
    ):
        del os.environ[key]

# This URL is never connected to unless a database fixture replaces it.
os.environ.update(
    SEIRETH_API_HOST="127.0.0.1",
    SEIRETH_API_PORT="8000",
    SEIRETH_SANDBOX_BACKEND="inmemory",
    SEIRETH_DATABASE_URL="postgresql+psycopg://unused:unused@127.0.0.1/unused",
)

# Use Pydantic's defaults without loading the operator's .env. Export the full
# baseline so API subprocesses also override optional settings in that file.
with patch.object(DotEnvSettingsSource, "__call__", return_value={}):
    test_settings = import_module("app.core.config").settings
os.environ.update(
    {
        f"SEIRETH_{key.upper()}": json.dumps(value)
        if isinstance(value, (list, dict))
        else str(value)
        for key, value in test_settings.model_dump(mode="json").items()
    }
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
def disposable_database(alembic_config):
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
        from app.assessments import worker
        from app.core.config import settings
        from app.persistence import db

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
        command.upgrade(alembic_config, "head")
        yield db


@pytest.fixture
def alembic_config():
    return Config(toml_file=Path(__file__).resolve().parents[1] / "pyproject.toml")


@pytest.fixture
def database_context(alembic_config):
    return partial(disposable_database, alembic_config)


@pytest.fixture
def database(database_context):
    with database_context() as db:
        yield db


@pytest.fixture
def assessment_graph(database):
    from app.persistence import models

    def make(*, owner="local-development", plugins=None, status="queued"):
        with database.SessionLocal() as db:
            project = models.Project(name="test project", owner_actor=owner)
            db.add(project)
            db.flush()
            target = models.Target(
                project_id=project.id,
                name="demo",
                image="seireth/demo-app:local",
                url="http://demo-app:8080/",
            )
            db.add(target)
            db.flush()
            assessment = models.Assessment(
                project_id=project.id,
                target_id=target.id,
                url=target.url,
                plugins=["security-headers"] if plugins is None else plugins,
                status=status,
            )
            db.add(assessment)
            db.commit()
            return SimpleNamespace(
                project=project, target=target, assessment=assessment
            )

    return make


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
        "evidence": {"url": "http://demo-app:8080/", "observed": True},
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
