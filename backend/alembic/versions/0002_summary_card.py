"""Add document_summary_cards table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_summary_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("parties", JSONB(), nullable=True),
        sa.Column("effective_date", JSONB(), nullable=True),
        sa.Column("term_length", JSONB(), nullable=True),
        sa.Column("payment_terms", JSONB(), nullable=True),
        sa.Column("termination_rights", JSONB(), nullable=True),
        sa.Column("liability_caps", JSONB(), nullable=True),
        sa.Column("governing_law", JSONB(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_summary_cards_tenant_id",
        "document_summary_cards",
        ["tenant_id"],
    )
    op.create_index(
        "ix_document_summary_cards_document_id",
        "document_summary_cards",
        ["document_id"],
    )

    # Row-Level Security — same pattern as all other tenant tables.
    op.execute("ALTER TABLE document_summary_cards ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_summary_cards FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON document_summary_cards
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
    """)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON document_summary_cards"
    )
    op.execute(
        "ALTER TABLE document_summary_cards DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "ix_document_summary_cards_document_id",
        table_name="document_summary_cards",
    )
    op.drop_index(
        "ix_document_summary_cards_tenant_id",
        table_name="document_summary_cards",
    )
    op.drop_table("document_summary_cards")
