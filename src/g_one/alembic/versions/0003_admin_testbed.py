"""Add workspace, user, role assignment and API token management.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Releases before this migration used ``Base.metadata.create_all()``. Those
    # databases already contain the latest ORM tables, so adopt them instead of
    # trying to create them again while Alembic advances the revision marker.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "workspaces" not in tables:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "workspace_users" not in tables:
        op.create_table(
            "workspace_users",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("subject", sa.String(128), nullable=False),
            sa.Column("display_name", sa.String(128), nullable=False),
            sa.Column("email", sa.String(255)),
            sa.Column("roles", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "subject"),
        )
        op.create_index("ix_workspace_users_tenant_id", "workspace_users", ["tenant_id"])
    if "api_tokens" not in tables:
        op.create_table(
            "api_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("prefix", sa.String(16), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("tenant_id", "token_hash"),
        )
        op.create_index("ix_api_tokens_tenant_id", "api_tokens", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("api_tokens")
    op.drop_table("workspace_users")
    op.drop_table("workspaces")
