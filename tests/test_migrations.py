"""Versioned schema, migration behavior, and database constraints."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
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


@pytest.mark.parametrize("finding_id", [None, "missing-finding"])
def test_evidence_requires_an_existing_finding(database, finding_id):
    with database.SessionLocal() as db:
        db.add(models.Evidence(finding_id=finding_id, kind="http-response", data={}))
        with pytest.raises(IntegrityError) as error:
            db.commit()
    if finding_id is None:
        assert error.value.orig.diag.column_name == "finding_id"
    else:
        assert error.value.orig.diag.constraint_name == "evidence_finding_id_fkey"


@pytest.mark.parametrize("remediation", [{}, {"remediation": None}])
def test_finding_requires_remediation(database, assessment_graph, remediation):
    graph = assessment_graph()
    with database.SessionLocal() as db:
        db.add(
            models.Finding(
                assessment_id=graph.assessment.id,
                plugin="security-headers",
                title="test",
                severity="low",
                description="test",
                **remediation,
            )
        )
        with pytest.raises(IntegrityError) as error:
            db.commit()
    assert error.value.orig.diag.column_name == "remediation"


def test_deleting_finding_removes_its_evidence(database, assessment_graph):
    graph = assessment_graph(status="completed")
    with database.SessionLocal() as db:
        evidence = models.Evidence(kind="http-response", data={})
        finding = models.Finding(
            assessment_id=graph.assessment.id,
            plugin="security-headers",
            title="test",
            severity="low",
            description="test",
            remediation="Configure the inspected response header.",
            evidence=[evidence],
        )
        db.add(finding)
        db.commit()
        identity = evidence.id
        db.delete(finding)
        db.commit()
        assert db.get(models.Evidence, identity) is None
