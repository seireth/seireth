"""Database engine, declarative base, and request-scoped sessions."""

from collections.abc import Generator
from uuid import uuid4

from sqlalchemy import String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and close it after the request completes."""

    with SessionLocal() as db:
        yield db
