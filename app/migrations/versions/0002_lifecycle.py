"""Persist bounded attempts and cleanup ownership."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assessments",
        sa.Column(
            "cleanup_pending", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_check_constraint(
        "assessment_status_valid",
        "assessments",
        "status IN ('queued', 'running', 'cancelling', 'recovering', 'completed', 'failed', 'cancelled')",
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("assessments.id"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(20), nullable=False),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cleanup_verified", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(200)),
        sa.UniqueConstraint("assessment_id", "number", name="attempt_number_unique"),
        sa.CheckConstraint("number BETWEEN 1 AND 2", name="attempt_number_bounded"),
    )
    op.create_index("ix_attempts_assessment_id", "attempts", ["assessment_id"])


def downgrade():
    op.drop_table("attempts")
    op.drop_constraint("assessment_status_valid", "assessments")
    op.drop_column("assessments", "cleanup_pending")
