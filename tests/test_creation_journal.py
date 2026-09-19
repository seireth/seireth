from copy import deepcopy
from threading import Event
from time import monotonic

import pytest
from fake_docker import FakeDocker

from app.execution import ExecutionContext
from app.orchestrator import execute
from app.sandbox import DockerSandbox, new_journal


def make_sandbox(journal=None, persist=None):
    return DockerSandbox(
        "demo:local",
        runner_image="python:3.14-slim",
        target_host="demo-target",
        operation_journal=journal,
        persist_journal=persist,
    )


def context():
    return ExecutionContext(Event(), Event(), monotonic() + 5)


def test_late_creation_is_not_certified_absent(monkeypatch):
    daemon = FakeDocker()
    daemon.install(monkeypatch)
    persisted = []
    sandbox = make_sandbox(
        new_journal(), lambda journal, advancing: persisted.append(deepcopy(journal))
    )

    def timeout(sandbox, kind):
        assert persisted[-1]["resources"][kind]["state"] == "uncertain"
        raise TimeoutError("daemon still creating")

    daemon.create_hook = timeout
    outcome = execute(sandbox, "http://demo-target:8080", context())
    assert outcome.status == "failed"
    assert outcome.error == "assessment deadline exceeded"
    assert not outcome.cleanup_verified
    assert "network: creation outcome unknown" in outcome.cleanup_reason
    for _ in range(3):
        assert not sandbox.cleanup().verified
    assert (
        len([call for call in daemon.calls if call[:2] == ["network", "create"]]) == 1
    )
    daemon.add(sandbox, "network")
    assert sandbox.cleanup().verified
    assert not daemon.live
    assert persisted[-1]["resources"]["network"]["state"] == "removed"


@pytest.mark.parametrize(
    "boundary", ["before_intent", "after_intent", "after_creation"]
)
def test_crash_boundaries_remain_conservative(monkeypatch, boundary):
    daemon = FakeDocker()
    daemon.install(monkeypatch)
    stored = new_journal()

    def persist(journal, advancing):
        nonlocal stored
        state = journal["resources"]["network"]["state"]
        if boundary == "before_intent" and state == "uncertain":
            raise OSError("journal commit failed")
        if boundary == "after_creation" and state == "created":
            raise OSError("journal commit failed after Docker replied")
        stored = deepcopy(journal)

    sandbox = make_sandbox(stored, persist)
    if boundary == "after_intent":
        daemon.create_hook = lambda *args: (_ for _ in ()).throw(
            TimeoutError("crash before request reached daemon")
        )
    with pytest.raises((OSError, TimeoutError)):
        sandbox.execute("http://demo-target:8080")
    recovered = DockerSandbox(
        "demo:local",
        runner_image="python:3.14-slim",
        resources=sandbox.resources,
        assessment_id=sandbox.assessment_id,
        attempt_id=sandbox.attempt_id,
        operation_journal=stored,
    )
    assert recovered.cleanup().verified is (boundary != "after_intent")
    if boundary == "before_intent":
        assert not any("create" in call for call in daemon.calls)
    assert not daemon.live


def test_legacy_absence_remains_unknown(monkeypatch):
    daemon = FakeDocker()
    daemon.install(monkeypatch)
    sandbox = make_sandbox()
    assert not sandbox.cleanup().verified
    for kind in sandbox.resources:
        daemon.add(sandbox, kind)
    assert sandbox.cleanup().verified
    assert not daemon.live


def test_persist_observed_id_before_removing_late_resource(monkeypatch):
    daemon = FakeDocker()
    daemon.install(monkeypatch)
    sandbox = make_sandbox(new_journal(legacy=True))
    daemon.add(sandbox, "network")

    def cannot_persist(journal, advancing):
        if journal["resources"]["network"]["state"] == "created":
            raise OSError("database unavailable")

    sandbox.persist_journal = cannot_persist
    assert not sandbox.cleanup().verified
    assert sandbox.resources["network"] in daemon.live
    assert not any("rm" in call for call in daemon.calls)


def test_known_identity_cannot_be_replaced(monkeypatch):
    daemon = FakeDocker()
    daemon.install(monkeypatch)
    sandbox = make_sandbox(new_journal())
    sandbox.journal["resources"]["network"] = {"state": "created", "id": "a" * 64}
    daemon.add(sandbox, "network")
    cleanup = sandbox.cleanup()
    assert not cleanup.verified
    assert "identity mismatch" in cleanup.reason
    assert daemon.live
