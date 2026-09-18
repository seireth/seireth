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

from app.migration import check_schema, migrate, migration_config


def test_versioned_schema_and_model_agree(database):
    migrate()
    migrate()
    check_schema()
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


def test_initial_revision_upgrade_and_missing_revision(database):
    # All tables live in this disposable database. This test runs after other
    # database tests; downgrade clears their synthetic records.
    command.downgrade(migration_config(), "base")
    with pytest.raises(RuntimeError, match="schema is not current"):
        check_schema()
    command.upgrade(migration_config(), "0001")
    assert "attempts" not in inspect(database.engine).get_table_names()
    migrate()
    check_schema()
    assert "attempts" in inspect(database.engine).get_table_names()
