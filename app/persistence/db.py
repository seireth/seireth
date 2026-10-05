"""Database engine, declarative base, and request-scoped sessions."""

from collections.abc import Generator
from uuid import uuid4

from sqlalchemy import Engine, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..core.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )


def create_runtime_engine(url: str) -> Engine:
    """Use the same bounded connections for runtime and disposable test databases."""
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )


engine = create_runtime_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and close it after the request completes."""

    with SessionLocal() as db:
        yield db
