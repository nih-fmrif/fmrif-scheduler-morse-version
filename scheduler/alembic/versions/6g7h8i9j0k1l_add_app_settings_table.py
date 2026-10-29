"""Add app_settings table for runtime admin configuration overrides

Revision ID: 6g7h8i9j0k1l
Revises: 6f7g8h9i0j1k
Create Date: 2026-03-10 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "6g7h8i9j0k1l"
down_revision = "6f7g8h9i0j1k"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if inspector.has_table("app_settings"):
        return
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", sa.String(20), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("app_settings")
