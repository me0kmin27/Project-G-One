"""Remove workspaces and add client login delivery flags.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "client_deployment_profiles" in tables:
        columns = {column["name"] for column in inspector.get_columns("client_deployment_profiles")}
        with op.batch_alter_table("client_deployment_profiles") as batch:
            if "deliver_vpn_on_login" not in columns:
                batch.add_column(sa.Column("deliver_vpn_on_login", sa.Boolean(), nullable=False, server_default=sa.true()))
            if "deliver_file_servers_on_login" not in columns:
                batch.add_column(sa.Column("deliver_file_servers_on_login", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "workspaces" in tables:
        op.drop_table("workspaces")


def downgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("client_deployment_profiles") as batch:
        batch.drop_column("deliver_file_servers_on_login")
        batch.drop_column("deliver_vpn_on_login")
