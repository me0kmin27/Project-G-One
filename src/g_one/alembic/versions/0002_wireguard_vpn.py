"""Add tenant WireGuard networks and peers.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "vpn_networks" not in tables:
        op.create_table(
            "vpn_networks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("address_cidr", sa.String(64), nullable=False),
            sa.Column("endpoint", sa.String(255), nullable=False),
            sa.Column("listen_port", sa.Integer(), nullable=False),
            sa.Column("dns", sa.String(255), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id"),
            sa.UniqueConstraint("tenant_id", "id"),
        )
        op.create_index("ix_vpn_networks_tenant_id", "vpn_networks", ["tenant_id"])
    if "vpn_peers" not in tables:
        op.create_table(
            "vpn_peers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("network_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("public_key", sa.String(44), nullable=False),
            sa.Column("address", sa.String(64), nullable=False),
            sa.Column("allowed_ips", sa.String(1024), nullable=False),
            sa.Column("persistent_keepalive", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["tenant_id", "network_id"], ["vpn_networks.tenant_id", "vpn_networks.id"]
            ),
            sa.UniqueConstraint("tenant_id", "network_id", "public_key"),
            sa.UniqueConstraint("tenant_id", "network_id", "address"),
        )
        op.create_index("ix_vpn_peers_tenant_id", "vpn_peers", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("vpn_peers")
    op.drop_table("vpn_networks")
