"""CLI behavior, including commands without an operator .env."""

import os
import subprocess
import sys

import pytest


def test_cli_help_and_tests_do_not_load_operator_settings(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SEIRETH_")
    }
    for arguments in (["--help"], ["test", "--help"]):
        result = subprocess.run(
            [sys.executable, "-m", "app", *arguments],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("migration_status", [0, 1])
def test_docker_startup_gates_api_on_temporary_migration(monkeypatch, migration_status):
    from app.__main__ import main

    calls = []

    def compose(command):
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
def test_docker_up_waits_and_propagates_readiness_failure(monkeypatch, capsys, status):
    from app.__main__ import main

    calls = []

    def compose(command):
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
    from app.__main__ import main

    monkeypatch.setattr(
        sys, "argv", ["app", "docker-up", "--api-ready-timeout-seconds", timeout]
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_docker_up_missing_cli_reports_stage(monkeypatch, capsys):
    from app.__main__ import main

    def unavailable(*args):
        raise FileNotFoundError("docker unavailable")

    monkeypatch.setattr(sys, "argv", ["app", "docker-up"])
    monkeypatch.setattr(subprocess, "call", unavailable)
    assert main() == 1
    assert "build" in capsys.readouterr().err
