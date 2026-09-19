"""Record creation intent and resource identities before advancing execution."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attempts", sa.Column("operation_journal", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("attempts", "operation_journal")
