"""Docker command failure paths without a daemon."""

import json
import subprocess
import sys
from threading import Event
from time import monotonic

import pytest

from app.execution import Cancelled, ExecutionContext
from app.sandbox import _FETCH, DockerSandbox, new_journal


@pytest.fixture
def sandbox():
    return DockerSandbox(
        "demo:local",
        runner_image="python:3.14-slim",
        target_host="demo-target",
        operation_journal=new_journal(),
    )


def test_restricted_owned_commands(sandbox, monkeypatch):
    calls = []

    def run(args, timeout, **kwargs):
        calls.append(args)
        output = json.dumps({"X-Test": "ok"}) if "--attach" in args else "a" * 64
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(sandbox, "_run", run)
    assert sandbox.execute("http://demo-target:8080") == {"X-Test": "ok"}
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


def test_daemon_failure_never_means_cleanup_success(sandbox, monkeypatch):
    monkeypatch.setattr(
        sandbox,
        "_run",
        lambda args, *a, **k: subprocess.CompletedProcess(
            args, 1, "", "daemon unavailable"
        ),
    )
    assert not sandbox.cleanup().verified


@pytest.mark.parametrize(
    "failure", [None, "runner", "target", "network", "ownership", "remove-error"]
)
def test_cleanup_checks_each_resource(sandbox, monkeypatch, failure):
    present = set(sandbox.resources.values())
    identities = {
        name: f"{index:064x}"
        for index, name in enumerate(sandbox.resources.values(), 1)
    }
    removed = []

    def run(args, *a, **kwargs):
        output = ""
        if args[:2] == ["network", "ls"] or args[0] == "ps":
            output = "\n".join(present)
        elif "inspect" in args:
            labels = sandbox.labels if failure != "ownership" else {}
            output = json.dumps(
                [
                    {
                        "Id": identities[args[-1]],
                        "Labels": labels,
                        "Config": {"Labels": labels},
                    }
                ]
            )
        else:
            name = next(
                name for name, identity in identities.items() if identity == args[-1]
            )
            removed.append(name)
            if failure == "remove-error":
                return subprocess.CompletedProcess(args, 1, "", "failed")
            if name != sandbox.resources.get(failure):
                present.discard(name)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(sandbox, "_run", run)
    assert sandbox.cleanup().verified is (failure is None)
    if failure == "ownership":
        assert not removed
    else:
        assert set(removed) == set(sandbox.resources.values())


def test_cleanup_of_absent_resources_is_idempotent(sandbox, monkeypatch):
    monkeypatch.setattr(
        sandbox,
        "_run",
        lambda args, *a, **k: subprocess.CompletedProcess(args, 0, "", ""),
    )
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


def test_network_created_before_cli_timeout_is_reconciled(sandbox, monkeypatch):
    from app.orchestrator import execute

    live = set()

    def run(args, *a, **kwargs):
        output = ""
        if args[:2] == ["network", "create"]:
            live.add(sandbox.resources["network"])
            raise TimeoutError("client timed out after daemon created network")
        if args[:2] == ["network", "ls"]:
            output = "\n".join(live)
        elif args[:2] == ["network", "inspect"]:
            output = json.dumps([{"Id": "a" * 64, "Labels": sandbox.labels}])
        elif args[:2] == ["network", "rm"]:
            assert args[-1] == "a" * 64
            live.discard(sandbox.resources["network"])
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(sandbox, "_run", run)
    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    outcome = execute(sandbox, "http://demo-target:8080", context)
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert not live


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
