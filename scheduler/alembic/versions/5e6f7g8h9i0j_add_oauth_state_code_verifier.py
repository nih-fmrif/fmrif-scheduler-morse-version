"""Add code_verifier to oauth_state table

Revision ID: 5e6f7g8h9i0j
Revises: 4d5e6f7g8h9i
Create Date: 2026-02-11 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "5e6f7g8h9i0j"
down_revision = "4d5e6f7g8h9i"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table("oauth_state"):
        return
    columns = [col["name"] for col in inspector.get_columns("oauth_state")]
    if "code_verifier" in columns:
        return
    with op.batch_alter_table("oauth_state") as batch:
        batch.add_column(sa.Column("code_verifier", sa.String(128), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table("oauth_state"):
        return
    columns = [col["name"] for col in inspector.get_columns("oauth_state")]
    if "code_verifier" not in columns:
        return
    with op.batch_alter_table("oauth_state") as batch:
        batch.drop_column("code_verifier")
