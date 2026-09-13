from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class AssessmentStatus(StrEnum):
    """Allowed lifecycle states for an assessment."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Project(Base):
    """A project groups targets, authorization, and assessment activity."""

    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    targets: Mapped[list["Target"]] = relationship(cascade="all, delete-orphan")
    scopes: Mapped[list["AuthorizationScope"]] = relationship(cascade="all, delete-orphan")


class Target(Base):
    """An authorized software target that may be assessed."""

    __tablename__ = "targets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    image: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(500))
    owned_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthorizationScope(Base):
    """A time-bounded URL scope authorizing testing of a target."""

    __tablename__ = "authorization_scopes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id"))
    allowed_url: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Assessment(Base):
    """A single execution of a selected assessment profile."""

    __tablename__ = "assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id"))
    scope_id: Mapped[str] = mapped_column(ForeignKey("authorization_scopes.id"))
    profile: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default=AssessmentStatus.queued)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    findings: Mapped[list["Finding"]] = relationship(cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(cascade="all, delete-orphan")


class Finding(Base):
    """A normalized security finding produced by an assessment."""

    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    plugin: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)


class Evidence(Base):
    """Evidence captured while validating an assessment finding."""

    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)


class AuditEvent(Base):
    """Append-oriented record of a security-sensitive platform action."""

    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
"""SQLAlchemy persistence models for the MVP-0 domain."""
