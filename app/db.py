"""Database engine, declarative base, and request-scoped sessions."""

from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and close it after the request completes."""

    # Lifespan startup is used by the server; this lazy fallback also supports
    # ASGI test transports that do not run lifespan events.
    from .migration import migrate

    migrate()
    with SessionLocal() as db:
        yield db
