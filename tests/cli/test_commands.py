"""CLI command wiring and Docker startup behavior."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def socket_group(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "987\n")


@pytest.mark.parametrize("dotenv", ["", "SEIRETH_DATABASE_URL=invalid\n"])
def test_remote_verification_and_evidence_validation_need_no_local_settings(
    tmp_path, dotenv
):
    (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SEIRETH_")
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    program = """
import sys
from unittest.mock import patch

import httpx

from app.cli import commands

events = [
    ("project.created", "project-1"), ("target.registered", "target-1"),
    ("assessment.queued", "assessment-1"), ("assessment.running", "assessment-1"),
    ("assessment.route_finished", "assessment-1"),
    ("assessment.completed", "assessment-1"),
]
responses = {
    "/health": {"status": "ok"},
    "/api/v1/projects": {"id": "project-1"},
    "/api/v1/targets": {"id": "target-1", "url": "http://demo:8080/"},
    "/api/v1/assessments": {"id": "assessment-1"},
    "/api/v1/assessments/assessment-1/results": {
        "assessment_id": "assessment-1", "status": "completed", "findings": [],
        "result": {"cleanup_verified": True, "sandbox_backend": "docker"},
    },
    "/api/v1/assessments/assessment-1/evidence": {
        "assessment_id": "assessment-1", "status": "completed",
        "cleanup_pending": False, "evidence": [],
    },
    "/api/v1/projects/project-1/audit-events": [
        {"action": action, "resource_id": resource_id}
        for action, resource_id in events
    ],
}
def respond(request):
    assert request.url.host == "remote.example"
    status = 202 if request.url.path == "/api/v1/assessments" else 200
    return httpx.Response(status, json=responses[request.url.path])

client = httpx.Client
with patch.object(httpx, "Client", lambda **kwargs: client(
    transport=httpx.MockTransport(respond), **kwargs
)):
    status = commands.main()
assert "app.core.config" not in sys.modules
assert "app.persistence.db" not in sys.modules
raise SystemExit(status)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            program,
            "verify",
            "--base-url",
            "https://remote.example",
            "--image",
            "demo:local",
            "--target-url",
            "http://demo:8080/",
            "--plugins",
            "http-security-headers",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["evidence"]["assessment_id"] == "assessment-1"


def test_verify_failure_reports_error_and_returns_failure(monkeypatch, capsys):
    from app.cli import commands

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.cli.commands",
            "verify",
            "--image",
            "arbitrary:local",
            "--target-url",
            "http://arbitrary:8080/",
            "--plugins",
            "http-security-headers",
        ],
    )
    monkeypatch.setattr(
        commands,
        "verify",
        Mock(side_effect=RuntimeError("synthetic verification failure")),
    )

    assert commands.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "verification failed: synthetic verification failure\n"


@pytest.mark.parametrize("migration_status", [0, 1])
def test_docker_startup_gates_api_on_temporary_migration(
    monkeypatch, migration_status, socket_group
):
    from app.cli.commands import main

    calls = []

    def compose(command, **kwargs):
        calls.append(command)
        return migration_status if "run" in command else 0

    monkeypatch.setattr(sys, "argv", ["app.cli.commands", "docker-up"])
    monkeypatch.setattr(subprocess, "call", compose)
    assert main() == migration_status
    migration = next(call for call in calls if "run" in call)
    assert "--rm" in migration
    assert any(
        "stop" in call and "api" in call for call in calls[: calls.index(migration)]
    )
    api_started = any("up" in call and "api" in call for call in calls)
    assert api_started == (migration_status == 0)


@pytest.mark.parametrize("status", [0, 1, 17])
def test_docker_up_waits_and_propagates_readiness_failure(
    monkeypatch, capsys, status, socket_group
):
    from app.cli.commands import main

    calls = []

    def compose(command, **kwargs):
        calls.append(command)
        return status if "--wait-timeout" in command else 0

    monkeypatch.setattr(
        sys,
        "argv",
        ["app.cli.commands", "docker-up", "--api-ready-timeout-seconds", "7.2"],
    )
    monkeypatch.setattr(subprocess, "call", compose)
    assert main() == status
    start = calls[-1]
    assert "--wait" in start
    assert start[start.index("--wait-timeout") + 1] == "8"
    error = capsys.readouterr().err
    if status:
        assert "API readiness" in error
        assert "docker compose ps -a" in error
        assert "docker compose logs api" in error
    assert not any("down" in call for call in calls)


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "not-a-number"])
def test_docker_up_rejects_invalid_timeout_before_start(monkeypatch, timeout):
    from app.cli.commands import main

    monkeypatch.setattr(
        sys,
        "argv",
        ["app.cli.commands", "docker-up", "--api-ready-timeout-seconds", timeout],
    )
    call = Mock(return_value=0)
    probe = Mock(return_value="987\n")
    monkeypatch.setattr(subprocess, "call", call)
    monkeypatch.setattr(subprocess, "check_output", probe)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    call.assert_not_called()
    probe.assert_not_called()


def test_docker_up_missing_cli_reports_stage(monkeypatch, capsys):
    from app.cli.commands import main

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("docker unavailable")

    monkeypatch.setattr(sys, "argv", ["app.cli.commands", "docker-up"])
    monkeypatch.setattr(subprocess, "call", unavailable)
    assert main() == 1
    assert "build" in capsys.readouterr().err


@pytest.mark.parametrize("gid", ["0", "987"])
def test_docker_up_uses_detected_socket_group_without_changing_host_env(
    monkeypatch, gid
):
    from app.cli.commands import _docker_up

    monkeypatch.setenv("SEIRETH_DOCKER_SOCKET_GID", "123")
    calls = []

    def compose(command, *, env):
        calls.append((command, env.copy()))
        return 0

    def probe(command, *, env, text):
        assert "--no-deps" in command and "--rm" in command
        assert command[-4:] == ["stat", "-c", "%g", "/var/run/docker.sock"]
        assert "/var/run/docker.sock:/var/run/docker.sock" in command
        return f"{gid}\n"

    monkeypatch.setattr(subprocess, "call", compose)
    monkeypatch.setattr(subprocess, "check_output", probe)
    assert _docker_up(120) == 0
    assert calls[-1][1]["SEIRETH_DOCKER_SOCKET_GID"] == gid
    assert os.environ["SEIRETH_DOCKER_SOCKET_GID"] == "123"


@pytest.mark.parametrize("result", ["", "root", "-1", "0\n987", "ï¼‘ï¼’ï¼“", None])
def test_docker_up_socket_probe_failure_stops_before_services(
    monkeypatch, capsys, result
):
    from app.cli.commands import _docker_up

    calls = []
    monkeypatch.setattr(
        subprocess, "call", lambda command, **kwargs: calls.append(command) or 0
    )

    def probe(*args, **kwargs):
        if result is None:
            raise subprocess.CalledProcessError(1, args[0])
        return result

    monkeypatch.setattr(subprocess, "check_output", probe)
    assert _docker_up(120) == 1
    assert len(calls) == 1
    assert "docker-up failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    "stage,verbs",
    [
        ("build", ["build"]),
        ("stop API", ["build", "stop"]),
        ("start PostgreSQL", ["build", "stop", "up"]),
    ],
)
def test_docker_up_stage_failure_prevents_following_commands(
    monkeypatch, capsys, socket_group, stage, verbs
):
    from app.cli.commands import main

    calls = []

    def compose(command, **kwargs):
        calls.append(command)
        return 17 if len(calls) == len(verbs) else 0

    monkeypatch.setattr(sys, "argv", ["app.cli.commands", "docker-up"])
    monkeypatch.setattr(subprocess, "call", compose)
    assert main() == 17
    assert [command[2] for command in calls] == verbs
    if stage == "start PostgreSQL":
        assert calls[-1][-1] == "postgres"
    assert stage in capsys.readouterr().err
