"""Versioned schema, migration behavior, and database constraints."""

import json

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app import models
from app.migration import migrate, migration_config
from app.sandbox import new_journal


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


def test_status_constraint(database):
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError) as error:
            connection.execute(
                text(
                    "INSERT INTO assessments (id, project_id, target_id, scope_id, plugins, status, created_at) VALUES ('bad', 'bad', 'bad', 'bad', '[\"security-headers\"]'::json, 'unknown', now())"
                )
            )
    assert error.value.orig.diag.constraint_name == "assessment_status_valid"


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
            "(id, project_id, target_id, scope_id, status, "
            "cleanup_pending, result, created_at) "
            "VALUES ('old-assessment', 'old-project', 'old-target', 'old-scope', "
            "'completed', false, "
            '\'{"plugin":"security-headers","finding_count":1,"preserved":"original"}\'::json, now())'
        )
        for identity, result in [
            ("null-result", None),
            ("nonlegacy-result", {"error": "original failure"}),
        ]:
            connection.execute(
                text(
                    "INSERT INTO assessments (id, project_id, target_id, scope_id, status, cleanup_pending, result, created_at) "
                    "VALUES (:id, 'old-project', 'old-target', 'old-scope', 'failed', false, CAST(:result AS json), now())"
                ),
                {
                    "id": identity,
                    "result": json.dumps(result) if result is not None else None,
                },
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
        unchanged = dict(
            connection.execute(
                text("SELECT id, result FROM assessments WHERE id <> 'old-assessment'")
            ).all()
        )
        assert unchanged == {
            "null-result": None,
            "nonlegacy-result": {"error": "original failure"},
        }
        assert dict(
            connection.execute(text("SELECT id, plugins FROM assessments")).all()
        ) == {
            identity: ["security-headers"]
            for identity in ["old-assessment", "null-result", "nonlegacy-result"]
        }
    assert plugins == ["security-headers"]
    assert "plugin" not in result
    assert result["plugins"] == [{"id": "security-headers", "finding_count": 1}]
    assert result["preserved"] == "original"
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


def test_single_plugin_downgrade_round_trips_existing_data(database, assessment_graph):
    graph = assessment_graph(status="completed")
    original = {
        "plugins": [{"id": "security-headers", "finding_count": 1}],
        "finding_count": 1,
        "cleanup_verified": True,
        "preserved": {"value": "original"},
    }
    with database.SessionLocal() as db:
        db.get(models.Assessment, graph.assessment.id).result = original
        finding = models.Finding(
            assessment_id=graph.assessment.id,
            plugin="security-headers",
            title="test",
            severity="low",
            description="description",
            remediation="new remediation",
        )
        db.add(finding)
        db.commit()
        finding_id = finding.id
    command.downgrade(migration_config(), "0001_initial_schema")
    with database.engine.connect() as connection:
        downgraded = connection.scalar(
            text("SELECT result FROM assessments WHERE id=:id"),
            {"id": graph.assessment.id},
        )
        assert downgraded == {
            "plugin": "security-headers",
            "finding_count": 1,
            "cleanup_verified": True,
            "preserved": {"value": "original"},
        }
        assert "remediation" not in {
            column["name"] for column in inspect(connection).get_columns("findings")
        }
    migrate()
    with database.SessionLocal() as db:
        assert db.get(models.Assessment, graph.assessment.id).result == original
        assert db.get(models.Assessment, graph.assessment.id).plugins == [
            "security-headers"
        ]
        assert db.get(models.Finding, finding_id).remediation is None
        assert db.get(models.Finding, finding_id).description == "description"


def test_multiple_plugin_downgrade_rejection_is_atomic(database, assessment_graph):
    graph = assessment_graph(plugins=["security-headers", "second"])
    with database.engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
        before = dict(
            connection.execute(select(models.Assessment.__table__)).mappings().one()
        )
    with pytest.raises(
        RuntimeError, match="cannot downgrade assessments with multiple plugins"
    ):
        command.downgrade(migration_config(), "0001_initial_schema")
    _assert_schema_matches_models(database)
    with database.engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == revision
        assert (
            dict(
                connection.execute(select(models.Assessment.__table__)).mappings().one()
            )
            == before
        )
        assert connection.scalar(
            select(models.Assessment.plugins).where(
                models.Assessment.id == graph.assessment.id
            )
        ) == ["security-headers", "second"]


@pytest.mark.parametrize("number", [0, 3])
def test_attempt_number_bounds_are_enforced(database, assessment_graph, number):
    graph = assessment_graph()
    with database.SessionLocal() as db:
        db.add(
            models.Attempt(
                assessment_id=graph.assessment.id,
                number=number,
                backend="inmemory",
                resources={},
                operation_journal=new_journal(),
            )
        )
        with pytest.raises(IntegrityError) as error:
            db.commit()
    assert error.value.orig.diag.constraint_name == "attempt_number_bounded"


def test_attempt_number_must_be_unique_per_assessment(database, assessment_graph):
    graph = assessment_graph()
    with database.SessionLocal() as db:
        for _ in range(2):
            db.add(
                models.Attempt(
                    assessment_id=graph.assessment.id,
                    number=1,
                    backend="inmemory",
                    resources={},
                    operation_journal=new_journal(),
                )
            )
        with pytest.raises(IntegrityError) as error:
            db.commit()
    assert error.value.orig.diag.constraint_name == "attempt_number_unique"
