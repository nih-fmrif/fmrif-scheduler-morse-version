"""Remove reset_tokens table - Phase 2 JWT auth

Revision ID: 2b3c4d5e6f7g
Revises: 1a2b3c4d5e6f
Create Date: 2025-12-09 14:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "2b3c4d5e6f7g"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    # Check if table exists before dropping
    conn = op.get_bind()
    inspector = inspect(conn)
    if inspector.has_table("reset_tokens"):
        op.drop_table("reset_tokens")


def downgrade():
    # Recreate table if needed (unlikely to be used)
    op.create_table(
        "reset_tokens",
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("for_user", sa.String(20), nullable=False),
        sa.Column(
            "issued",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("token"),
        sa.ForeignKeyConstraint(
            ["for_user"],
            ["tlkpresearcher.researchercode"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
    )
