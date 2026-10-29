"""Add oauth_state table for OAuth login state tracking

Revision ID: 3c4d5e6f7g8h
Revises: 2b3c4d5e6f7g
Create Date: 2026-02-05 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "3c4d5e6f7g8h"
down_revision = "2b3c4d5e6f7g"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table("oauth_state"):
        op.create_table(
            "oauth_state",
            sa.Column("state", sa.String(128), nullable=False),
            sa.Column("nonce", sa.String(128), nullable=False),
            sa.Column("redirect_next", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("state"),
        )


def downgrade():
    op.drop_table("oauth_state")
