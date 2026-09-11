"""Add file servers and web client distribution profiles.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "file_servers" not in existing:
        op.create_table(
            "file_servers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("host", sa.String(255), nullable=False),
            sa.Column("shares", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "id"),
            sa.UniqueConstraint("tenant_id", "name"),
        )
    if "client_deployment_profiles" not in existing:
        op.create_table(
            "client_deployment_profiles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("vpn_network_id", sa.String(36), nullable=False),
            sa.Column("allowed_ips", sa.String(1024), nullable=False),
            sa.Column("file_server_ids", sa.JSON(), nullable=False),
            sa.Column("target_subjects", sa.JSON(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "id"),
            sa.UniqueConstraint("tenant_id", "name"),
        )
    if "client_enrollment_codes" not in existing:
        op.create_table(
            "client_enrollment_codes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
            sa.Column("profile_id", sa.String(36), nullable=False, index=True),
            sa.Column("subject", sa.String(128), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("client_enrollment_codes")
    op.drop_table("client_deployment_profiles")
    op.drop_table("file_servers")
