"""Persist plugin selection and actionable finding remediation."""

import sqlalchemy as sa
from alembic import op

revision = "0002_plugin_selection"
down_revision = "0001_initial_schema"


def upgrade():
    op.add_column("assessments", sa.Column("plugins", sa.JSON(), nullable=True))
    op.execute("UPDATE assessments SET plugins = '[\"security-headers\"]'::json")
    op.alter_column("assessments", "plugins", nullable=False)
    op.add_column("findings", sa.Column("remediation", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE assessments
        SET result = (
            (result::jsonb - 'plugin') || jsonb_build_object(
                'plugins', jsonb_build_array(jsonb_build_object(
                    'id', result->>'plugin',
                    'finding_count', COALESCE((result->>'finding_count')::integer, 0)
                ))
            )
        )::json
        WHERE result IS NOT NULL AND result::jsonb ? 'plugin'
        """
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM assessments WHERE json_array_length(plugins) <> 1"
        )
    ):
        raise RuntimeError("cannot downgrade assessments with multiple plugins")
    op.execute(
        """
        UPDATE assessments
        SET result = (
            (result::jsonb - 'plugins') || jsonb_build_object(
                'plugin', result->'plugins'->0->>'id'
            )
        )::json
        WHERE result IS NOT NULL AND result::jsonb ? 'plugins'
        """
    )
    op.drop_column("findings", "remediation")
    op.drop_column("assessments", "plugins")
