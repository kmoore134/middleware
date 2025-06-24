"""Add altroots_metadata column to webshare service

Revision ID: add_altroots_metadata
Revises: add_webshare_to_services
Create Date: 2025-06-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'add_altroots_metadata'
down_revision = 'add_webshare_to_services'
branch_labels = None
depends_on = None


def upgrade():
    # Check if column already exists
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('services_webshare')]
    
    if 'srv_altroots_metadata' not in columns:
        # Add the new column with a default value
        # Note: SQLite doesn't support dropping defaults, so we just add the column
        op.add_column(
            'services_webshare',
            sa.Column('srv_altroots_metadata', sa.JSON(), nullable=False, server_default='{}')
        )


def downgrade():
    # Check if column exists before trying to drop it
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('services_webshare')]
    
    if 'srv_altroots_metadata' in columns:
        op.drop_column('services_webshare', 'srv_altroots_metadata')