"""Add clause_comments table.

Clause-level comments let any org member annotate a specific chunk (clause)
inside a document. The table is tenant-isolated with the standard RLS policy.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clause_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "is_resolved",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clause_comments_tenant_id", "clause_comments", ["tenant_id"])
    op.create_index(
        "ix_clause_comments_document_id", "clause_comments", ["document_id"]
    )
    op.create_index("ix_clause_comments_chunk_id", "clause_comments", ["chunk_id"])
    # Composite index: common query pattern is tenant + chunk
    op.create_index(
        "ix_clause_comments_tenant_chunk",
        "clause_comments",
        ["tenant_id", "chunk_id"],
    )

    op.execute("ALTER TABLE clause_comments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clause_comments FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON clause_comments
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON clause_comments")
    op.execute("ALTER TABLE clause_comments DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_clause_comments_tenant_chunk", table_name="clause_comments")
    op.drop_index("ix_clause_comments_chunk_id", table_name="clause_comments")
    op.drop_index("ix_clause_comments_document_id", table_name="clause_comments")
    op.drop_index("ix_clause_comments_tenant_id", table_name="clause_comments")
    op.drop_table("clause_comments")
