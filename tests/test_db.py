"""Runtime connection settings and disposable database failure cleanup."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import db, migration, worker
from app.config import settings

pytestmark = pytest.mark.database


def test_runtime_connections_are_bounded(database):
    with database.engine.connect() as connection:
        assert connection.scalar(text("SHOW statement_timeout")) == "5s"
        assert (
            connection.connection.driver_connection.info.get_parameters()[
                "connect_timeout"
            ]
            == "5"
        )
    assert database.engine.pool.checkedout() == 0


@pytest.mark.parametrize("stage", ["engine", "migration", "stop", "dispose"])
def test_database_fixture_restores_bindings_and_drops_after_failure(
    database_context, monkeypatch, stage
):
    original = db.engine, db.SessionLocal, settings.database_url
    create = db.create_runtime_engine
    created = []

    def fail():
        raise RuntimeError(f"synthetic {stage} failure")

    def capture(url):
        created.append(make_url(url).database)
        if stage == "engine":
            fail()
        engine = create(url)
        if stage == "dispose":
            dispose = engine.dispose

            def dispose_and_fail():
                dispose()
                fail()

            monkeypatch.setattr(engine, "dispose", dispose_and_fail)
        return engine

    monkeypatch.setattr(db, "create_runtime_engine", capture)
    if stage == "migration":
        monkeypatch.setattr(migration, "migrate", fail)
    if stage == "stop":
        stop = worker.dispatcher.stop

        def stop_and_fail():
            stop()
            fail()

        monkeypatch.setattr(worker.dispatcher, "stop", stop_and_fail)
    with pytest.raises(RuntimeError, match=f"synthetic {stage} failure"):
        with database_context():
            assert db.engine is not original[0]
    assert (db.engine, db.SessionLocal, settings.database_url) == original
    assert len(created) == 1
    admin = create_engine(os.environ["SEIRETH_TEST_ADMIN_URL"])
    try:
        with admin.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                    {"name": created[0]},
                )
                == 0
            )
    finally:
        admin.dispose()
