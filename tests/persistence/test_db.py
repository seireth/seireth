"""Bounded runtime database connections."""

import pytest
from sqlalchemy import text

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
