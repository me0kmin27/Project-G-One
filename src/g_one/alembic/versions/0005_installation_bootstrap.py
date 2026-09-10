"""Track the one-time administrator bootstrap.

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if "installation_state" not in sa.inspect(connection).get_table_names():
        op.create_table(
            "installation_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("initialized", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    state = connection.execute(sa.text("SELECT 1 FROM installation_state WHERE id = 1")).first()
    if state is not None:
        return
    existing_user = connection.execute(sa.text("SELECT 1 FROM workspace_users LIMIT 1")).first()
    connection.execute(
        sa.text("INSERT INTO installation_state (id, initialized) VALUES (1, :initialized)"),
        {"initialized": bool(existing_user)},
    )


def downgrade() -> None:
    op.drop_table("installation_state")
