"""CLI behavior, including commands without an operator .env."""

import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest


@pytest.fixture
def socket_group(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "987\n")


def test_cli_help_does_not_load_operator_settings(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SEIRETH_")
    }
    result = subprocess.run(
        [sys.executable, "-m", "app", "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "arguments,host,port",
    [
        ([], "127.0.0.2", 9001),
        (["--host", "0.0.0.0", "--port", "9000"], "0.0.0.0", 9000),
        (["--port", "0"], "127.0.0.2", 0),
    ],
)
@pytest.mark.parametrize("status", [0, 17])
def test_serve_forwards_binding_and_exit_status(
    monkeypatch, arguments, host, port, status
):
    from app.cli.commands import main
    from app.core.config import settings

    monkeypatch.setattr(settings, "api_host", "127.0.0.2")
    monkeypatch.setattr(settings, "api_port", 9001)
    monkeypatch.setattr(sys, "argv", ["app", "serve", *arguments])
    call = Mock(return_value=status)
    monkeypatch.setattr(subprocess, "call", call)

    assert main() == status
    call.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--host",
            host,
            "--port",
            str(port),
        ]
    )


@pytest.mark.parametrize("status", [0, 17])
def test_migrate_upgrades_to_head_and_preserves_exit_status(monkeypatch, status):
    from app.cli.commands import main

    monkeypatch.setattr(sys, "argv", ["app", "migrate"])
    call = Mock(return_value=status)
    monkeypatch.setattr(subprocess, "call", call)

    assert main() == status
    call.assert_called_once_with([sys.executable, "-m", "alembic", "upgrade", "head"])


@pytest.mark.parametrize(
    "arguments,base_url,timeout,backend",
    [
        ([], "http://127.0.0.2:9001", 120, None),
        (
            [
                "--base-url",
                "https://example.test",
                "--timeout-seconds",
                "7.2",
                "--expected-backend",
                "docker",
            ],
            "https://example.test",
            7.2,
            "docker",
        ),
    ],
)
def test_verify_forwards_options_and_prints_json(
    monkeypatch, capsys, arguments, base_url, timeout, backend
):
    from app.cli import commands
    from app.core.config import settings

    monkeypatch.setattr(settings, "api_host", "127.0.0.2")
    monkeypatch.setattr(settings, "api_port", 9001)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app",
            "verify",
            "--image",
            "arbitrary:local",
            "--target-url",
            "http://arbitrary:8080/",
            "--plugins",
            "security-headers",
            *arguments,
        ],
    )
    result = {"assessment": {"id": "assessment-1"}, "results": {"status": "completed"}}
    check = Mock(return_value=result)
    monkeypatch.setattr(commands, "verify", check)

    assert commands.main() == 0
    check.assert_called_once_with(
        base_url,
        timeout_seconds=timeout,
        expected_backend=backend,
        image="arbitrary:local",
        target_url="http://arbitrary:8080/",
        plugins=["security-headers"],
    )
    output = capsys.readouterr()
    assert json.loads(output.out) == result
    assert output.err == ""


def test_verify_failure_reports_error_and_returns_failure(monkeypatch, capsys):
    from app.cli import commands

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app",
            "verify",
            "--image",
            "arbitrary:local",
            "--target-url",
            "http://arbitrary:8080/",
            "--plugins",
            "security-headers",
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

    monkeypatch.setattr(sys, "argv", ["app", "docker-up"])
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
        sys, "argv", ["app", "docker-up", "--api-ready-timeout-seconds", "7.2"]
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
        sys, "argv", ["app", "docker-up", "--api-ready-timeout-seconds", timeout]
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

    monkeypatch.setattr(sys, "argv", ["app", "docker-up"])
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

    monkeypatch.setattr(sys, "argv", ["app", "docker-up"])
    monkeypatch.setattr(subprocess, "call", compose)
    assert main() == 17
    assert [command[2] for command in calls] == verbs
    if stage == "start PostgreSQL":
        assert calls[-1][-1] == "postgres"
    assert stage in capsys.readouterr().err
