"""Docker execution, creation journals, and cleanup without a daemon."""

import json
import subprocess
import sys
from copy import deepcopy
from threading import Event
from time import monotonic

import pytest

from app.execution import Cancelled, ExecutionContext
from app.orchestrator import execute
from app.plugins import registry
from app.sandbox import _FETCH, DockerSandbox, new_journal


@pytest.fixture
def make_sandbox():
    def make(journal, persist=None):
        return DockerSandbox(
            "demo:local",
            runner_image="python:3.14-slim",
            target_host="demo-target",
            operation_journal=journal,
            persist_journal=persist,
        )

    return make


@pytest.fixture
def sandbox(make_sandbox):
    return make_sandbox(new_journal())


def test_restricted_owned_commands(sandbox, fake_docker):
    fake_docker.headers = {"X-Test": "ok"}
    assert sandbox.execute("http://demo-target:8080") == {"X-Test": "ok"}
    calls = fake_docker.calls
    assert "--internal" in calls[0]
    for args in (call for call in calls if call[0] == "create"):
        for flag in [
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65532:65532",
            "--label",
        ]:
            assert flag in args
        assert "--network=host" not in args
        assert "--rm" not in args


def test_daemon_failure_never_means_cleanup_success(sandbox, fake_docker):
    fake_docker.available = False
    assert not sandbox.cleanup().verified


@pytest.mark.parametrize(
    "failure", [None, "runner", "target", "network", "ownership", "remove-error"]
)
def test_cleanup_checks_each_resource(sandbox, failure, fake_docker):
    identities = {fake_docker.add(sandbox, kind) for kind in sandbox.resources}
    if failure == "ownership":
        for record in fake_docker.live.values():
            record["Labels"] = record["Config"]["Labels"] = {}
    fake_docker.kept = {sandbox.resources.get(failure)}
    fake_docker.remove_error = failure == "remove-error"
    assert sandbox.cleanup().verified is (failure is None)
    removed = {call[-1] for call in fake_docker.calls if "rm" in call}
    assert removed == (set() if failure == "ownership" else identities)


def test_cleanup_of_absent_resources_is_idempotent(sandbox, fake_docker):
    assert sandbox.cleanup().verified
    assert sandbox.cleanup().verified


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_real_subprocess_is_killed_on_interruption(sandbox, monkeypatch, reason):
    original = subprocess.Popen
    processes = []

    def launch(*args, **kwargs):
        process = original(
            [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        processes.append(process)
        if reason == "cancel":
            sandbox.context.cancel.set()
        return process

    sandbox.context = ExecutionContext(Event(), Event(), monotonic() + 0.2)
    monkeypatch.setattr("app.sandbox.subprocess.Popen", launch)
    with pytest.raises(Cancelled if reason == "cancel" else TimeoutError):
        sandbox._run(["version"], 5)
    assert processes[0].poll() is not None


def test_network_created_before_cli_timeout_is_reconciled(sandbox, fake_docker):
    def timeout_after_creation(sandbox, kind):
        fake_docker.add(sandbox, kind)
        raise TimeoutError("client timed out after daemon created network")

    fake_docker.create_hook = timeout_after_creation
    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    outcome = execute(
        sandbox,
        "http://demo-target:8080",
        context,
        registry.select(["security-headers"]),
    )
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert not fake_docker.live


def test_runner_does_not_follow_redirects():
    # Exercise the actual embedded runner against a local owned HTTP server.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/outside-scope")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _FETCH,
                f"http://127.0.0.1:{server.server_port}/allowed",
                "2",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["Location"] == "/outside-scope"
        assert paths == ["/allowed"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def context():
    return ExecutionContext(Event(), Event(), monotonic() + 5)


def test_late_creation_is_not_certified_absent(fake_docker, make_sandbox):
    persisted = []
    sandbox = make_sandbox(
        new_journal(), lambda journal, advancing: persisted.append(deepcopy(journal))
    )

    def timeout(sandbox, kind):
        assert persisted[-1]["resources"][kind]["state"] == "uncertain"
        raise TimeoutError("daemon still creating")

    fake_docker.create_hook = timeout
    outcome = execute(
        sandbox,
        "http://demo-target:8080",
        context(),
        registry.select(["security-headers"]),
    )
    assert outcome.status == "failed"
    assert outcome.error == "assessment deadline exceeded"
    assert not outcome.cleanup_verified
    assert "network: creation outcome unknown" in outcome.cleanup_reason
    for _ in range(3):
        assert not sandbox.cleanup().verified
    assert (
        len([call for call in fake_docker.calls if call[:2] == ["network", "create"]])
        == 1
    )
    fake_docker.add(sandbox, "network")
    assert sandbox.cleanup().verified
    assert not fake_docker.live
    assert persisted[-1]["resources"]["network"]["state"] == "removed"


@pytest.mark.parametrize(
    "boundary", ["before_intent", "after_intent", "after_creation"]
)
def test_cleanup_requires_proven_resource_state_after_crash(
    boundary, fake_docker, make_sandbox
):
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
        fake_docker.create_hook = lambda *args: (_ for _ in ()).throw(
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
        assert not any("create" in call for call in fake_docker.calls)
    assert not fake_docker.live


@pytest.mark.parametrize(
    "journal", [None, {}, {"version": 1, "owner": "invalid", "resources": {}}]
)
def test_invalid_journal_is_rejected(journal, make_sandbox):
    with pytest.raises(ValueError, match="invalid operation journal"):
        make_sandbox(journal)


def test_persist_observed_id_before_removing_late_resource(fake_docker, make_sandbox):
    journal = new_journal()
    journal["resources"]["network"]["state"] = "uncertain"
    sandbox = make_sandbox(journal)
    fake_docker.add(sandbox, "network")

    def cannot_persist(journal, advancing):
        if journal["resources"]["network"]["state"] == "created":
            raise OSError("database unavailable")

    sandbox.persist_journal = cannot_persist
    assert not sandbox.cleanup().verified
    assert sandbox.resources["network"] in fake_docker.live
    assert not any("rm" in call for call in fake_docker.calls)


def test_known_identity_cannot_be_replaced(fake_docker, make_sandbox):
    sandbox = make_sandbox(new_journal())
    sandbox.journal["resources"]["network"] = {"state": "created", "id": "a" * 64}
    fake_docker.add(sandbox, "network")
    cleanup = sandbox.cleanup()
    assert not cleanup.verified
    assert "identity mismatch" in cleanup.reason
    assert fake_docker.live
