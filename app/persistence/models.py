from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.constraints import (
    FINDING_SEVERITY_MAX_LENGTH,
    FINDING_TITLE_MAX_LENGTH,
    MAX_ASSESSMENT_ATTEMPTS,
    NAME_MAX_LENGTH,
    PLUGIN_ID_MAX_LENGTH,
    STORED_URL_MAX_LENGTH,
    TARGET_IMAGE_MAX_LENGTH,
)
from ..core.identity import ACTOR
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
    """A project groups targets and assessment activity."""

    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    owner_actor: Mapped[str] = mapped_column(String(200), default=ACTOR, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Target(Base):
    """An image and base URL that may be assessed."""

    __tablename__ = "targets"
    project_id: Mapped[str] = mapped_column(ForeignKey(Project.id), index=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    kind: Mapped[str] = mapped_column(
        String(20), default="docker", server_default="docker"
    )
    image: Mapped[str | None] = mapped_column(String(TARGET_IMAGE_MAX_LENGTH))
    launch_profile: Mapped[str | None] = mapped_column(String(100))
    network_profile: Mapped[str | None] = mapped_column(String(100))
    trust_profile: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(STORED_URL_MAX_LENGTH))


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
    cleanup_pending: Mapped[bool] = mapped_column(default=False, server_default="false")
    project_id: Mapped[str] = mapped_column(ForeignKey(Project.id), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey(Target.id))
    status: Mapped[str] = mapped_column(String(30), default=AssessmentStatus.queued)
    result: Mapped[dict | None] = mapped_column(JSON)
    plan_snapshot: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    @property
    def url(self) -> str:
        return self.plan_snapshot["routes"][0]["url"]

    @property
    def plugins(self) -> list[str]:
        return [plugin["id"] for plugin in self.plan_snapshot["plugins"]]


class Finding(Base):
    """A normalized security finding produced by an assessment."""

    __tablename__ = "findings"
    assessment_id: Mapped[str] = mapped_column(ForeignKey(Assessment.id), index=True)
    route_result_id: Mapped[str] = mapped_column(
        ForeignKey("route_results.id"), index=True
    )
    plugin: Mapped[str] = mapped_column(String(PLUGIN_ID_MAX_LENGTH))
    title: Mapped[str] = mapped_column(String(FINDING_TITLE_MAX_LENGTH))
    severity: Mapped[str] = mapped_column(String(FINDING_SEVERITY_MAX_LENGTH))
    description: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list["Evidence"]] = relationship(cascade="all, delete-orphan")


class Evidence(Base):
    """Evidence captured while validating an assessment finding."""

    __tablename__ = "evidence"
    finding_id: Mapped[str] = mapped_column(ForeignKey(Finding.id), index=True)
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
    number: Mapped[int] = mapped_column()
    backend: Mapped[str] = mapped_column(String(20))
    operation_journal: Mapped[dict] = mapped_column(JSON(none_as_null=True))
    execution_metadata: Mapped[dict] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_verified: Mapped[bool] = mapped_column(default=False)
    http_closed: Mapped[bool | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(String(200))


class RouteResult(Base):
    """Atomic, attempt-scoped route observations and analysis results."""

    __tablename__ = "route_results"
    __table_args__ = (
        UniqueConstraint("attempt_id", "route_key", name="route_result_unique"),
    )
    assessment_id: Mapped[str] = mapped_column(ForeignKey(Assessment.id), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey(Attempt.id), index=True)
    route_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
