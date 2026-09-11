"""Add composite index (tenant_id, deadline) on obligations.

The reminder worker queries obligations filtered by tenant_id where
deadline is within the next N days.  A composite index on these two
columns makes that scan efficient at any tenant scale.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_obligations_tenant_deadline",
        "obligations",
        ["tenant_id", "deadline"],
    )


def downgrade() -> None:
    op.drop_index("ix_obligations_tenant_deadline", table_name="obligations")
