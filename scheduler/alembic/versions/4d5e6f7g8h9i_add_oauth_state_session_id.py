"""Add session_id to oauth_state table

Revision ID: 4d5e6f7g8h9i
Revises: 3c4d5e6f7g8h
Create Date: 2026-02-05 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "4d5e6f7g8h9i"
down_revision = "3c4d5e6f7g8h"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table("oauth_state"):
        return
    columns = [col["name"] for col in inspector.get_columns("oauth_state")]
    if "session_id" in columns:
        return
    with op.batch_alter_table("oauth_state") as batch:
        batch.add_column(sa.Column("session_id", sa.String(255), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table("oauth_state"):
        return
    columns = [col["name"] for col in inspector.get_columns("oauth_state")]
    if "session_id" not in columns:
        return
    with op.batch_alter_table("oauth_state") as batch:
        batch.drop_column("session_id")
