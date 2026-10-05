"""Docker execution, creation journals, and cleanup without a daemon."""

import json
import subprocess
import sys
from copy import deepcopy
from threading import Event

import pytest

from app.assessments.execution import Cancelled, ExecutionContext
from app.assessments.orchestrator import execute
from app.assessments.sandbox import _FETCH, DockerSandbox, InMemorySandbox, new_journal
from app.plugins.base import HttpObservation
from app.plugins.registry import registry


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


@pytest.mark.parametrize("custom_limits", [False, True])
def test_restricted_owned_commands(sandbox, fake_docker, custom_limits):
    if custom_limits:
        sandbox.memory, sandbox.cpus, sandbox.pids_limit = "128m", 0.25, 32
    fake_docker.headers = {
        "X-Test": ["ok"],
        "Set-Cookie": ["first=synthetic"],
        "set-cookie": ["second=synthetic"],
    }
    observation = sandbox.execute("http://demo-target:8080/app?test=1")
    assert isinstance(observation, HttpObservation)
    assert str(observation.url) == "http://demo-target:8080/app?test=1"
    assert observation.headers == {
        "x-test": ["ok"],
        "set-cookie": ["first=synthetic", "second=synthetic"],
    }
    calls = fake_docker.calls
    runner = next(call for call in calls if "python" in call)
    assert runner[-2] == "http://target:8080/app?test=1"
    assert "--internal" in calls[0]
    expected_labels = {
        "seireth.assessment": sandbox.assessment_id,
        "seireth.attempt": sandbox.attempt_id,
    }
    for args in (calls[0], *(call for call in calls if call[0] == "create")):
        assert (
            dict(
                args[index + 1].split("=", 1)
                for index, arg in enumerate(args)
                if arg == "--label"
            )
            == expected_labels
        )
    for args in (call for call in calls if call[0] == "create"):
        for flag in [
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65532:65532",
            f"--memory={'128m' if custom_limits else '256m'}",
            f"--cpus={0.25 if custom_limits else 0.5}",
            f"--pids-limit={32 if custom_limits else 64}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
        ]:
            assert flag in args
        assert "--network=host" not in args
        assert "--rm" not in args
        assert args[args.index("--network") + 1] == sandbox.resources["network"]


def test_wrong_host_is_rejected_before_docker_calls(sandbox, fake_docker):
    with pytest.raises(ValueError, match="outside the registered target"):
        sandbox.execute("http://other-target:8080/")
    assert fake_docker.calls == []


@pytest.mark.parametrize(
    "status,output,error",
    [
        pytest.param(1, "", RuntimeError, id="nonzero-exit"),
        pytest.param(0, "not JSON", RuntimeError, id="malformed-json"),
        pytest.param(0, "[]", RuntimeError, id="non-object-headers"),
    ],
)
def test_invalid_runner_response_still_allows_cleanup(
    sandbox, fake_docker, status, output, error
):
    fake_docker.runner_status, fake_docker.runner_output = status, output
    with pytest.raises(error):
        sandbox.execute("http://demo-target:8080/")
    assert sandbox.cleanup().verified
    assert not fake_docker.live


@pytest.mark.parametrize(
    "output",
    [
        "synthetic-cookie-secret invalid JSON",
        '{"Set-Cookie": "synthetic-cookie-secret"}',
        '{"Set-Cookie": ["synthetic-cookie-secret", 1]}',
        '{"Set-Cookie": ["synthetic-cookie-secret"], "X-Test": []}',
        '{"Set-Cookie": ["synthetic-cookie-secret"], "X-Test": null}',
        '[["Set-Cookie", "synthetic-cookie-secret"]]',
    ],
)
def test_invalid_runner_output_is_not_logged_and_always_cleans_up(
    sandbox, fake_docker, output, execution_context, caplog
):
    fake_docker.runner_output = output
    outcome = execute(
        sandbox,
        "http://demo-target:8080/",
        execution_context,
        registry.select(["cookie-security"]),
    )
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert not outcome.plugin_results
    assert not fake_docker.live
    assert "synthetic-cookie-secret" not in caplog.text


def test_simulated_backend_preserves_values_and_returns_independent_observations():
    sandbox = InMemorySandbox(
        headers={"Set-Cookie": ["first=synthetic"], "set-cookie": ["second=synthetic"]}
    )
    observation = sandbox.execute("http://demo-target:8080/app?test=1")
    assert isinstance(observation, HttpObservation)
    assert str(observation.url) == "http://demo-target:8080/app?test=1"
    assert observation.headers == {
        "set-cookie": ["first=synthetic", "second=synthetic"]
    }
    observation.headers["set-cookie"].append("changed=synthetic")
    assert sandbox.execute("http://demo-target:8080/app?test=1").headers == {
        "set-cookie": ["first=synthetic", "second=synthetic"]
    }


@pytest.mark.parametrize(
    "headers", [[], {"Set-Cookie": "synthetic-cookie-secret"}, {"Set-Cookie": []}]
)
def test_simulated_backend_rejects_invalid_headers_without_logging_values(
    headers, execution_context, caplog
):
    outcome = execute(
        InMemorySandbox(headers=headers),
        "http://demo-target:8080/",
        execution_context,
        registry.select(["cookie-security"]),
    )
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert not outcome.plugin_results
    assert "synthetic-cookie-secret" not in caplog.text


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


@pytest.mark.parametrize("label", ["seireth.assessment", "seireth.attempt"])
def test_cleanup_requires_both_ownership_labels(sandbox, fake_docker, label):
    labels = {**sandbox.labels, label: "another-owner"}
    for kind in sandbox.resources:
        fake_docker.add(sandbox, kind, labels=labels)
    before = deepcopy(fake_docker.live)

    assert not sandbox.cleanup().verified
    assert fake_docker.live == before
    assert not any("rm" in call for call in fake_docker.calls)


def test_cleanup_of_absent_resources_is_idempotent(sandbox, fake_docker):
    assert sandbox.cleanup().verified
    assert sandbox.cleanup().verified


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_real_subprocess_is_killed_on_interruption(sandbox, monkeypatch, reason):
    original = subprocess.Popen
    processes = []
    elapsed = 0

    def launch(*args, **kwargs):
        nonlocal elapsed
        process = original(
            [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        processes.append(process)
        if reason == "cancel":
            sandbox.context.cancel.set()
        else:
            elapsed = 2
        return process

    monkeypatch.setattr("app.assessments.execution.monotonic", lambda: elapsed)
    sandbox.context = ExecutionContext(Event(), Event(), 1)
    monkeypatch.setattr("app.assessments.sandbox.subprocess.Popen", launch)
    try:
        with pytest.raises(
            Cancelled if reason == "cancel" else TimeoutError,
            match="assessment cancelled"
            if reason == "cancel"
            else "assessment deadline exceeded",
        ):
            sandbox._run(["version"], 5)
        assert len(processes) == 1
        assert processes[0].poll() is not None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


def test_network_created_before_cli_timeout_is_reconciled(
    sandbox, fake_docker, execution_context
):
    def timeout_after_creation(sandbox, kind):
        fake_docker.add(sandbox, kind)
        raise TimeoutError("client timed out after daemon created network")

    fake_docker.create_hook = timeout_after_creation
    outcome = execute(
        sandbox,
        "http://demo-target:8080",
        execution_context,
        registry.select(["security-headers"]),
    )
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert not fake_docker.live


@pytest.mark.parametrize("status", [200, 302, 400])
def test_runner_preserves_repeated_headers_without_following_redirects(status):
    # Exercise the actual embedded runner against a local owned HTTP server.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(status)
            self.send_header("Location", "/outside-scope")
            self.send_header(
                "Set-Cookie", "first=synthetic; Expires=Wed, 21 Oct 2037 07:28:00 GMT"
            )
            self.send_header("set-cookie", "second=synthetic; SameSite=None")
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
        assert json.loads(result.stdout)["location"] == ["/outside-scope"]
        assert json.loads(result.stdout)["set-cookie"] == [
            "first=synthetic; Expires=Wed, 21 Oct 2037 07:28:00 GMT",
            "second=synthetic; SameSite=None",
        ]
        assert paths == ["/allowed"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_late_creation_is_not_certified_absent(
    fake_docker, make_sandbox, execution_context
):
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
        execution_context,
        registry.select(["security-headers"]),
    )
    assert outcome.status == "failed"
    assert outcome.error == "assessment execution timed out"
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
