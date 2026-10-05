"""Fixtures for assessment execution and simulated Docker behavior."""

from time import monotonic

import pytest


@pytest.fixture
def fake_docker(monkeypatch):
    from tests.assessments.fake_docker import FakeDocker

    daemon = FakeDocker()
    daemon.install(monkeypatch)
    yield daemon
    assert not daemon.unsupported_calls, daemon.unsupported_calls


@pytest.fixture
def execution_context():
    from threading import Event

    from app.assessments.execution import ExecutionContext

    return ExecutionContext(Event(), Event(), monotonic() + 5)
