"""Alembic environment shared by the CLI, Compose, and tests."""

from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401
from app.config import settings
from app.db import Base

engine = create_engine(settings.database_url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
