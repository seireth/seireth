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
