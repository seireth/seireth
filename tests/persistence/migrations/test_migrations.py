"""Versioned schema, migration behavior, and database constraints."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, Table, inspect, text
from sqlalchemy.exc import IntegrityError

from app.assessments.sandbox import new_journal
from app.persistence import models


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


def test_versioned_schema_and_model_agree(database, alembic_config):
    command.upgrade(alembic_config, "head")
    _assert_schema_matches_models(database)


def test_migration_connection_has_separate_timeouts(database, alembic_config):
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
        command.upgrade(alembic_config, "head")
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


def test_baseline_round_trip(database, alembic_config):
    command.downgrade(alembic_config, "base")
    assert set(inspect(database.engine).get_table_names()) == {"alembic_version"}
    command.upgrade(alembic_config, "head")
    _assert_schema_matches_models(database)
    with database.engine.connect() as connection:
        assert (
            MigrationContext.configure(connection).get_current_revision()
            == ScriptDirectory.from_config(alembic_config).get_current_head()
        )


def test_revision_generation_uses_template(
    database, tmp_path, alembic_config, monkeypatch
):
    import shutil

    config = alembic_config
    baseline = ScriptDirectory.from_config(config).get_current_head()
    baseline_tables = set(inspect(database.engine).get_table_names())
    location = tmp_path / "migrations"
    shutil.copytree(ScriptDirectory.from_config(config).dir, location)
    config.set_main_option("script_location", str(location))

    metadata = MetaData()
    for table in database.Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    added_table = Table(
        "migration_generation_check", metadata, Column("id", Integer, primary_key=True)
    )
    monkeypatch.setattr(database.Base, "metadata", metadata)

    revision = command.revision(config, message="generation check", autogenerate=True)
    assert revision.down_revision == baseline
    command.upgrade(config, revision.revision)
    assert inspect(database.engine).has_table(added_table.name)
    command.downgrade(config, baseline)
    assert set(inspect(database.engine).get_table_names()) == baseline_tables


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


@pytest.mark.parametrize("number", [1, 2])
def test_valid_attempt_numbers_are_persisted(database, assessment_graph, number):
    graph = assessment_graph()
    with database.SessionLocal() as db:
        attempt = models.Attempt(
            assessment_id=graph.assessment.id,
            number=number,
            backend="inmemory",
            resources={},
            operation_journal=new_journal(),
        )
        db.add(attempt)
        db.commit()
        identity = attempt.id
    with database.SessionLocal() as db:
        persisted = db.get(models.Attempt, identity)
        assert persisted is not None
        assert persisted.number == number


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
