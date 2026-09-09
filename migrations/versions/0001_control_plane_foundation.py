"""Create the initial tenant-scoped control-plane tables.

Revision ID: 0001
Revises: None
"""
from collections.abc import Callable

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _create_if_missing(name: str, create: Callable[[], None]) -> None:
    # Releases before Alembic used metadata.create_all(). This conditional
    # baseline adopts those installations without deleting their data.
    if name not in sa.inspect(op.get_bind()).get_table_names():
        create()


def upgrade() -> None:
    _create_if_missing(
        "devices",
        lambda: op.create_table(
            "devices",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("owner_id", sa.String(128), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "id"),
        ),
    )
    _create_if_missing(
        "support_requests",
        lambda: op.create_table(
            "support_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("requester_id", sa.String(128), nullable=False),
            sa.Column("target_device_id", sa.String(36), nullable=False),
            sa.Column("purpose", sa.String(500), nullable=False),
            sa.Column("permissions", sa.JSON(), nullable=False),
            sa.Column("state", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["tenant_id", "target_device_id"], ["devices.tenant_id", "devices.id"]
            ),
        ),
    )
    _create_if_missing(
        "audit_events",
        lambda: op.create_table(
            "audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("actor_id", sa.String(128), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("target_type", sa.String(50), nullable=False),
            sa.Column("target_id", sa.String(128), nullable=False),
            sa.Column("outcome", sa.String(20), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        ),
    )
    # Explicit indexes mirror the ORM declarations and avoid relying on
    # vendor-specific implicit indexes.
    inspector = sa.inspect(op.get_bind())
    for table, column in (
        ("devices", "tenant_id"),
        ("devices", "owner_id"),
        ("support_requests", "tenant_id"),
        ("audit_events", "tenant_id"),
    ):
        index_name = f"ix_{table}_{column}"
        if index_name not in {item["name"] for item in inspector.get_indexes(table)}:
            op.create_index(index_name, table, [column])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("support_requests")
    op.drop_table("devices")
