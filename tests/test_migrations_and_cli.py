"""Migration and CLI behavior, including commands without an operator .env."""

import os
import subprocess
import sys

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.migration import migrate, migration_config


def test_versioned_schema_and_model_agree(database):
    migrate()
    migrate()
    with database.engine.connect() as connection:
        assert (
            compare_metadata(
                MigrationContext.configure(connection), database.Base.metadata
            )
            == []
        )


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


def test_status_constraint(database):
    # A CHECK violation is independent of whether a referenced project exists.
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO assessments (id, project_id, target_id, scope_id, profile, status, created_at) VALUES ('bad', 'bad', 'bad', 'bad', 'passive', 'unknown', now())"
                )
            )


def test_initial_revision_upgrade(database):
    # All tables live in this disposable database. This test runs after other
    # database tests; downgrade clears their synthetic records.
    command.downgrade(migration_config(), "base")
    command.upgrade(migration_config(), "0001")
    assert "attempts" not in inspect(database.engine).get_table_names()
    migrate()
    assert "attempts" in inspect(database.engine).get_table_names()


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

    monkeypatch.setattr(sys, "argv", ["app", "docker-up", "--timeout-seconds", "7.2"])
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

    monkeypatch.setattr(sys, "argv", ["app", "docker-up", "--timeout-seconds", timeout])
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


def test_journal_upgrade_preserves_populated_legacy_attempts(database):
    from app import models

    with database.SessionLocal() as db:
        project = models.Project(name="migration")
        db.add(project)
        db.flush()
        target = models.Target(
            project_id=project.id, name="demo", image="demo:local", url="http://demo/"
        )
        db.add(target)
        db.flush()
        scope = models.AuthorizationScope(
            project_id=project.id,
            target_id=target.id,
            allowed_url=target.url,
            expires_at=models.now(),
        )
        db.add(scope)
        db.flush()
        item = models.Assessment(
            project_id=project.id,
            target_id=target.id,
            scope_id=scope.id,
            profile="passive",
            status="failed",
            result={"error": "preserve me"},
        )
        db.add(item)
        db.flush()
        attempt = models.Attempt(
            assessment_id=item.id, number=1, backend="docker", resources={}
        )
        db.add(attempt)
        db.commit()
        item_id, attempt_id = item.id, attempt.id
    command.downgrade(migration_config(), "0002")
    assert "operation_journal" not in {
        column["name"] for column in inspect(database.engine).get_columns("attempts")
    }
    migrate()
    with database.SessionLocal() as db:
        assert db.get(models.Attempt, attempt_id).operation_journal is None
        assert db.get(models.Assessment, item_id).result == {"error": "preserve me"}
    test_versioned_schema_and_model_agree(database)
