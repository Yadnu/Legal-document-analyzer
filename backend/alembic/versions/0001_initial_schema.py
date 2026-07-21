"""Initial schema: pgvector extension, all domain tables, RLS policies.

Revision ID: 0001
Revises:
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Tables that hold tenant data and must be protected by RLS.
_TENANT_TABLES = [
    "organizations",
    "users",
    "documents",
    "chunks",
    "conversations",
    "messages",
    "obligations",
    "audit_events",
]


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── organizations ─────────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sqlmodel.AutoString(), nullable=False),
        sa.Column("slug", sqlmodel.AutoString(), nullable=False),
        sa.Column("clerk_org_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("plan", sqlmodel.AutoString(), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_documents", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("max_members", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("logo_url", sqlmodel.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("clerk_org_id"),
    )
    op.create_index("ix_organizations_tenant_id", "organizations", ["tenant_id"])
    op.create_index("ix_organizations_slug", "organizations", ["slug"])
    op.create_index("ix_organizations_clerk_org_id", "organizations", ["clerk_org_id"])

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clerk_user_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.AutoString(), nullable=False),
        sa.Column("full_name", sqlmodel.AutoString(), nullable=True),
        sa.Column("role", sqlmodel.AutoString(), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_seen_at", sqlmodel.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_clerk_user_id", "users", ["clerk_user_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # ── documents ─────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sqlmodel.AutoString(), nullable=False),
        sa.Column("original_filename", sqlmodel.AutoString(), nullable=False),
        sa.Column("content_type", sqlmodel.AutoString(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("s3_key", sqlmodel.AutoString(), nullable=False),
        sa.Column("idempotency_key", sqlmodel.AutoString(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.AutoString(),
            nullable=False,
            server_default="processing",
        ),
        sa.Column("error_reason", sqlmodel.AutoString(), nullable=True),
        sa.Column("uploaded_by", sqlmodel.AutoString(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("s3_key"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_s3_key", "documents", ["s3_key"])
    op.create_index("ix_documents_idempotency_key", "documents", ["idempotency_key"])
    op.create_index("ix_documents_status", "documents", ["status"])

    # ── chunks ────────────────────────────────────────────────────────────────
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("section_number", sqlmodel.AutoString(), nullable=True),
        sa.Column("heading", sqlmodel.AutoString(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("cross_refs", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sqlmodel.AutoString(), nullable=False),
        sa.Column("embedding_model_version", sqlmodel.AutoString(), nullable=False),
        # 1024-dim vector for voyage-law-2 / Bedrock Titan
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("search_vector", TSVECTOR(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_tenant_id", "chunks", ["tenant_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # HNSW index for approximate nearest-neighbour dense retrieval (cosine distance)
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
    # GIN index for sparse tsvector full-text search
    op.execute(
        "CREATE INDEX ix_chunks_search_vector_gin ON chunks USING gin (search_vector)"
    )

    # ── conversations ─────────────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("title", sqlmodel.AutoString(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_document_id", "conversations", ["document_id"])

    # ── messages ──────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sqlmodel.AutoString(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    # ── obligations ───────────────────────────────────────────────────────────
    op.create_table(
        "obligations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("description", sqlmodel.AutoString(), nullable=False),
        sa.Column("obligation_type", sqlmodel.AutoString(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_days_before", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("assigned_to", sqlmodel.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_obligations_tenant_id", "obligations", ["tenant_id"])
    op.create_index("ix_obligations_document_id", "obligations", ["document_id"])
    op.create_index("ix_obligations_chunk_id", "obligations", ["chunk_id"])
    op.create_index("ix_obligations_deadline", "obligations", ["deadline"])

    # ── audit_events ──────────────────────────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sqlmodel.AutoString(), nullable=False),
        sa.Column("action", sqlmodel.AutoString(), nullable=False),
        sa.Column("resource_type", sqlmodel.AutoString(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("ip_address", sqlmodel.AutoString(), nullable=True),
        sa.Column("user_agent", sqlmodel.AutoString(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_resource_id", "audit_events", ["resource_id"])

    # ── Row-Level Security ────────────────────────────────────────────────────
    # Every tenant table gets RLS enabled and a single SELECT/INSERT/UPDATE/DELETE
    # policy that checks the per-connection session variable set by get_rls_db.
    #
    # FORCE ROW LEVEL SECURITY applies the policy even to table owners (the DB
    # superuser is exempted only for maintenance tasks performed outside the app).
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)
            )
            WITH CHECK (
                tenant_id = current_setting('app.current_tenant_id', true)
            )
            """
        )


def downgrade() -> None:
    # Remove RLS policies first, then drop tables in reverse dependency order.
    for table in reversed(_TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("audit_events")
    op.drop_table("obligations")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("users")
    op.drop_table("organizations")
