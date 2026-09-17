"""Add monthly Q&A quota columns to organizations.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-16
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "monthly_qa_quota",
            sa.Integer(),
            nullable=False,
            server_default="500",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "monthly_qa_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "monthly_qa_used")
    op.drop_column("organizations", "monthly_qa_quota")
