"""Explicit, idempotent startup migrations.

This intentionally small migration keeps schema setup out of module import time.
It can later be replaced by Alembic without changing application imports.
"""

from sqlalchemy import inspect, text

from . import models  # noqa: F401 - register mapped tables
from .db import Base, engine


def migrate() -> None:
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    if "projects" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("projects")}
        if "owner_actor" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN owner_actor VARCHAR(200) "
                        "NOT NULL DEFAULT 'local-development'"
                    )
                )
    if "targets" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("targets")}
        if "owned_demo" in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE targets DROP COLUMN owned_demo"))
