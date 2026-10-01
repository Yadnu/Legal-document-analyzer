"""Add workspace invites and a unique membership key.

Invites let an admin add someone to the shared workspace. The raw token is
never stored. A second RLS policy allows lookup by token hash so the invitee
can accept before they belong to the tenant.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep one membership row per person per workspace.
    op.execute("""
        DELETE FROM users a
        USING users b
        WHERE a.tenant_id = b.tenant_id
          AND a.clerk_user_id = b.clerk_user_id
          AND a.id <> b.id
          AND (
              a.created_at < b.created_at
              OR (a.created_at = b.created_at AND a.id::text < b.id::text)
          )
    """)
    op.create_index(
        "uq_users_tenant_clerk",
        "users",
        ["tenant_id", "clerk_user_id"],
        unique=True,
    )

    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("invited_by", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin', 'editor', 'viewer')",
            name="ck_workspace_invites_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_workspace_invites_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invites_token_hash"),
    )
    op.create_index(
        "ix_workspace_invites_tenant_id", "workspace_invites", ["tenant_id"]
    )
    op.create_index("ix_workspace_invites_email", "workspace_invites", ["email"])
    op.create_index(
        "ix_workspace_invites_token_hash", "workspace_invites", ["token_hash"]
    )
    op.create_index("ix_workspace_invites_status", "workspace_invites", ["status"])
    op.create_index(
        "uq_workspace_invites_pending_email",
        "workspace_invites",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.execute("ALTER TABLE workspace_invites ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workspace_invites FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON workspace_invites
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
    """)
    # Redeeming a secret token is the only read that is not tenant-scoped.
    # The hash is unguessable; an empty setting matches nothing.
    op.execute("""
        CREATE POLICY invite_token_lookup ON workspace_invites
        FOR SELECT
        USING (
            current_setting('app.invite_token_hash', true) <> ''
            AND token_hash = current_setting('app.invite_token_hash', true)
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS invite_token_lookup ON workspace_invites")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON workspace_invites")
    op.execute("ALTER TABLE workspace_invites DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "uq_workspace_invites_pending_email", table_name="workspace_invites"
    )
    op.drop_index("ix_workspace_invites_status", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_token_hash", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_email", table_name="workspace_invites")
    op.drop_index("ix_workspace_invites_tenant_id", table_name="workspace_invites")
    op.drop_table("workspace_invites")
    op.drop_index("uq_users_tenant_clerk", table_name="users")
