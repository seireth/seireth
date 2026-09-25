from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .constraints import (
    FINDING_SEVERITY_MAX_LENGTH,
    FINDING_TITLE_MAX_LENGTH,
    MAX_ASSESSMENT_ATTEMPTS,
    NAME_MAX_LENGTH,
    PLUGIN_ID_MAX_LENGTH,
    STORED_URL_MAX_LENGTH,
    TARGET_IMAGE_MAX_LENGTH,
)
from .db import Base


def now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class AssessmentStatus(StrEnum):
    """Allowed lifecycle states for an assessment."""

    queued = "queued"
    running = "running"
    cancelling = "cancelling"
    recovering = "recovering"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Project(Base):
    """A project groups targets, authorization, and assessment activity."""

    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    owner_actor: Mapped[str] = mapped_column(
        String(200), default="local-development", index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Target(Base):
    """An authorized software target that may be assessed."""

    __tablename__ = "targets"
    project_id: Mapped[str] = mapped_column(ForeignKey(Project.id), index=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    image: Mapped[str] = mapped_column(String(TARGET_IMAGE_MAX_LENGTH))
    url: Mapped[str] = mapped_column(String(STORED_URL_MAX_LENGTH))


class AuthorizationScope(Base):
    """A time-bounded URL scope authorizing testing of a target."""

    __tablename__ = "authorization_scopes"
    project_id: Mapped[str] = mapped_column(ForeignKey(Project.id), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey(Target.id))
    allowed_url: Mapped[str] = mapped_column(String(STORED_URL_MAX_LENGTH))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Assessment(Base):
    """A single execution of selected assessment plugins."""

    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{status.value}'" for status in AssessmentStatus)
            + ")",
            name="assessment_status_valid",
        ),
    )
    cleanup_pending: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    project_id: Mapped[str] = mapped_column(ForeignKey(Project.id), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey(Target.id))
    scope_id: Mapped[str] = mapped_column(ForeignKey(AuthorizationScope.id))
    plugins: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default=AssessmentStatus.queued)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    findings: Mapped[list["Finding"]] = relationship(cascade="all, delete-orphan")


class Finding(Base):
    """A normalized security finding produced by an assessment."""

    __tablename__ = "findings"
    assessment_id: Mapped[str] = mapped_column(ForeignKey(Assessment.id), index=True)
    plugin: Mapped[str] = mapped_column(String(PLUGIN_ID_MAX_LENGTH))
    title: Mapped[str] = mapped_column(String(FINDING_TITLE_MAX_LENGTH))
    severity: Mapped[str] = mapped_column(String(FINDING_SEVERITY_MAX_LENGTH))
    description: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)


class Evidence(Base):
    """Evidence captured while validating an assessment finding."""

    __tablename__ = "evidence"
    assessment_id: Mapped[str] = mapped_column(ForeignKey(Assessment.id), index=True)
    kind: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)


class AuditEvent(Base):
    """Append-oriented record of a security-sensitive platform action."""

    __tablename__ = "audit_events"
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Attempt(Base):
    """Durable ownership of one execution, committed before creating resources."""

    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("assessment_id", "number", name="attempt_number_unique"),
        CheckConstraint(
            f"number BETWEEN 1 AND {MAX_ASSESSMENT_ATTEMPTS}",
            name="attempt_number_bounded",
        ),
    )
    assessment_id: Mapped[str] = mapped_column(ForeignKey(Assessment.id), index=True)
    number: Mapped[int] = mapped_column(Integer)
    backend: Mapped[str] = mapped_column(String(20))
    resources: Mapped[dict] = mapped_column(JSON)
    operation_journal: Mapped[dict] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(200))
