"""Current PostgreSQL baseline, defined independently of application models."""

import sqlalchemy as sa
from alembic import op

revision = "0001_current_schema"
down_revision = None

PROJECT_ID_REFERENCE = "projects.id"
ASSESSMENT_ID_REFERENCE = "assessments.id"


def upgrade():
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_actor", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_owner_actor", "projects", ["owner_actor"])
    op.create_table(
        "targets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("image", sa.String(300), nullable=True),
        sa.Column("kind", sa.String(20), server_default="docker", nullable=False),
        sa.Column("launch_profile", sa.String(100), nullable=True),
        sa.Column("network_profile", sa.String(100), nullable=True),
        sa.Column("trust_profile", sa.String(100), nullable=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], [PROJECT_ID_REFERENCE]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_targets_project_id", "targets", ["project_id"])
    op.create_table(
        "assessments",
        sa.Column(
            "cleanup_pending", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("plan_snapshot", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancelling', 'recovering', 'completed', 'failed', 'cancelled')",
            name="assessment_status_valid",
        ),
        sa.ForeignKeyConstraint(["project_id"], [PROJECT_ID_REFERENCE]),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessments_project_id", "assessments", ["project_id"])
    op.create_table(
        "attempts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(20), nullable=False),
        sa.Column("execution_metadata", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("http_closed", sa.Boolean(), nullable=True),
        sa.Column("operation_journal", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_verified", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
        sa.CheckConstraint("number BETWEEN 1 AND 2", name="attempt_number_bounded"),
        sa.ForeignKeyConstraint(["assessment_id"], [ASSESSMENT_ID_REFERENCE]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "number", name="attempt_number_unique"),
    )
    op.create_index("ix_attempts_assessment_id", "attempts", ["assessment_id"])
    op.create_table(
        "route_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("assessments.id"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id", sa.String(36), sa.ForeignKey("attempts.id"), nullable=False
        ),
        sa.Column("route_key", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("attempt_id", "route_key", name="route_result_unique"),
    )
    op.create_index(
        "ix_route_results_assessment_id", "route_results", ["assessment_id"]
    )
    op.create_index("ix_route_results_attempt_id", "route_results", ["attempt_id"])
    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column(
            "route_result_id",
            sa.String(36),
            sa.ForeignKey("route_results.id"),
            nullable=False,
        ),
        sa.Column("plugin", sa.String(100), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], [ASSESSMENT_ID_REFERENCE]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_assessment_id", "findings", ["assessment_id"])
    op.create_index("ix_findings_route_result_id", "findings", ["route_result_id"])
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("finding_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_finding_id", "evidence", ["finding_id"])


def downgrade():
    op.drop_table("evidence")
    op.drop_table("findings")
    op.drop_table("route_results")
    op.drop_table("attempts")
    op.drop_table("assessments")
    op.drop_table("targets")
    op.drop_table("projects")
    op.drop_table("audit_events")
