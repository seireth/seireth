"""Migration and CLI behavior, including commands without an operator .env."""

import os
import subprocess
import sys

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.migration import migrate, migration_config


def _assert_schema_matches_models(database):
    with database.engine.connect() as connection:
        assert (
            compare_metadata(
                MigrationContext.configure(connection), database.Base.metadata
            )
            == []
        )
        inspector = inspect(connection)
        for table, name in [
            ("assessments", "assessment_status_valid"),
            ("attempts", "attempt_number_bounded"),
        ]:
            assert name in {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table)
            }


def test_versioned_schema_and_model_agree(database):
    migrate()
    migrate()
    _assert_schema_matches_models(database)


def test_migration_connection_has_separate_timeouts(database):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    observed = []

    def record(connection, _record):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('lock_timeout'), current_setting('statement_timeout')"
            )
            observed.append(cursor.fetchone())
        assert connection.info.get_parameters()["connect_timeout"] == "5"

    event.listen(Engine, "connect", record)
    try:
        migrate()
    finally:
        event.remove(Engine, "connect", record)
    assert observed == [("30s", "5min")]


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
                    "INSERT INTO assessments (id, project_id, target_id, scope_id, profile, plugins, status, created_at) VALUES ('bad', 'bad', 'bad', 'bad', 'passive', '[\"security-headers\"]'::json, 'unknown', now())"
                )
            )


def test_baseline_round_trip(database):
    command.downgrade(migration_config(), "base")
    assert set(inspect(database.engine).get_table_names()) == {"alembic_version"}
    migrate()
    _assert_schema_matches_models(database)
    with database.engine.connect() as connection:
        assert (
            MigrationContext.configure(connection).get_current_revision()
            == ScriptDirectory.from_config(migration_config()).get_current_head()
        )


def test_plugin_migration_backfills_existing_assessments(database):
    config = migration_config()
    command.downgrade(config, "base")
    command.upgrade(config, "0001_initial_schema")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id, name, owner_actor, created_at) "
                "VALUES ('old-project', 'old', 'local-development', now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO targets (id, project_id, name, image, url) "
                "VALUES ('old-target', 'old-project', 'old', 'demo:local', 'http://demo/')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO authorization_scopes "
                "(id, project_id, target_id, allowed_url, expires_at) "
                "VALUES ('old-scope', 'old-project', 'old-target', 'http://demo/', now() + interval '1 hour')"
            )
        )
        connection.exec_driver_sql(
            "INSERT INTO assessments "
            "(id, project_id, target_id, scope_id, profile, status, "
            "cleanup_pending, result, created_at) "
            "VALUES ('old-assessment', 'old-project', 'old-target', 'old-scope', "
            "'passive', 'completed', false, "
            '\'{"plugin":"security-headers","finding_count":1}\'::json, now())'
        )
        connection.execute(
            text(
                "INSERT INTO findings "
                "(id, assessment_id, plugin, title, severity, description) "
                "VALUES ('old-finding', 'old-assessment', 'security-headers', "
                "'old', 'medium', 'old finding')"
            )
        )
    migrate()
    with database.engine.connect() as connection:
        plugins, result = connection.execute(
            text("SELECT plugins, result FROM assessments WHERE id='old-assessment'")
        ).one()
        remediation = connection.scalar(
            text("SELECT remediation FROM findings WHERE id='old-finding'")
        )
    assert plugins == ["security-headers"]
    assert "plugin" not in result
    assert result["plugins"] == [{"id": "security-headers", "finding_count": 1}]
    assert remediation is None


def test_revision_generation_uses_template(database, tmp_path):
    import shutil
    from pathlib import Path

    config = migration_config()
    location = tmp_path / "migrations"
    shutil.copytree(config.get_main_option("script_location"), location)
    config.set_main_option("script_location", str(location))
    revision = command.revision(config, message="generation check", autogenerate=True)
    compile(Path(revision.path).read_text(), revision.path, "exec")


def test_missing_journal_is_rejected_by_database(database):
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError) as error:
            connection.execute(
                text(
                    "INSERT INTO attempts (id, assessment_id, number, backend, resources, started_at, cleanup_verified) VALUES ('bad', 'bad', 1, 'docker', '{}', now(), false)"
                )
            )
    assert error.value.orig.diag.column_name == "operation_journal"


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
