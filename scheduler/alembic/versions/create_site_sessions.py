"""Create site_sessions table

Revision ID: 1a2b3c4d5e6f
Revises: 
Create Date: 2024-01-14 16:00:00.000000

"""
from sqlalchemy import inspect
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Check if table exists first
    conn = op.get_bind()
    inspector = inspect(conn)
    if not inspector.has_table('site_sessions'):
        op.create_table(
            'site_sessions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.String(255), unique=True),
            sa.Column('data', sa.LargeBinary(), nullable=True),
            sa.Column('expiry', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )

def downgrade():
    op.drop_table('site_sessions')
