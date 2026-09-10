"""Add account credentials and client policy provisioning.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workspace_users")}
    with op.batch_alter_table("workspace_users") as batch:
        if "password_hash" not in columns:
            batch.add_column(sa.Column("password_hash", sa.String(255), nullable=True))
        if "vpn_address" not in columns:
            batch.add_column(sa.Column("vpn_address", sa.String(64), nullable=True))
        if "allowed_ips" not in columns:
            batch.add_column(sa.Column("allowed_ips", sa.String(1024), nullable=False, server_default=""))
        if "policy_version" not in columns:
            batch.add_column(sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("workspace_users") as batch:
        batch.drop_column("policy_version")
        batch.drop_column("allowed_ips")
        batch.drop_column("vpn_address")
        batch.drop_column("password_hash")
