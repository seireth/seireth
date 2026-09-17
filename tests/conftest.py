"""Isolate tests from operator settings and persistent development databases."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_database_directory = TemporaryDirectory(prefix="seireth-tests-")
os.environ.update(
    SEIRETH_API_HOST="127.0.0.1",
    SEIRETH_API_PORT="8000",
    SEIRETH_ENVIRONMENT="test",
    SEIRETH_SANDBOX_BACKEND="inmemory",
    SEIRETH_DOCKER_TARGET_IMAGE="seireth/demo-target:local",
    SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES='["seireth/demo-target:local"]',
    SEIRETH_DATABASE_URL=f"sqlite:///{Path(_database_directory.name).as_posix()}/test.db",
)


@pytest.fixture(scope="session", autouse=True)
def close_test_database():
    yield
    from app.db import engine
    from app.worker import dispatcher

    dispatcher._executor.shutdown(wait=True)
    engine.dispose()
    _database_directory.cleanup()
