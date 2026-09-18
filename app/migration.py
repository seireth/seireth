"""Explicit versioned migrations; startup only checks the schema revision."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory


def migration_config() -> Config:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).with_name("migrations"))
    )
    return config


def migrate() -> None:
    command.upgrade(migration_config(), "head")


def check_schema() -> None:
    from .db import engine

    with engine.connect() as connection:
        actual = MigrationContext.configure(connection).get_current_heads()
    expected = ScriptDirectory.from_config(migration_config()).get_heads()
    if set(actual) != set(expected):
        raise RuntimeError("Database schema is not current; run python -m app migrate")
