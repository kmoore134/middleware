"""Add webshare to services_services table

Revision ID: add_webshare_to_services
Revises: e8c7f5d2b9a1
Create Date: 2025-06-23 10:30:00.000000+00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_webshare_to_services'
down_revision = 'e8c7f5d2b9a1'
branch_labels = None
depends_on = None


def upgrade():
    # Add webshare to the services_services table
    op.execute("INSERT INTO services_services (srv_service, srv_enable) VALUES ('webshare', 0)")


def downgrade():
    # Remove webshare from services_services
    op.execute("DELETE FROM services_services WHERE srv_service = 'webshare'")