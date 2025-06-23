"""Add webshare service configuration table

Revision ID: e8c7f5d2b9a1
Revises: add_user_webshare
Create Date: 2025-06-19 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8c7f5d2b9a1'
down_revision = 'add_user_webshare'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'services_webshare',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('srv_truenas_host', sa.String(length=255), nullable=False),
        sa.Column('srv_log_level', sa.String(length=20), nullable=False),
        sa.Column('srv_session_log_retention', sa.Integer(), nullable=False),
        sa.Column('srv_enable_web_terminal', sa.Boolean(), nullable=False),
        sa.Column('srv_bulk_download_pool', sa.String(length=255), nullable=True),
        sa.Column('srv_search_index_pool', sa.String(length=255), nullable=True),
        sa.Column('srv_altroots', sa.JSON(), nullable=False),
        sa.Column('srv_search_enabled', sa.Boolean(), nullable=False),
        sa.Column('srv_search_directories', sa.JSON(), nullable=False),
        sa.Column('srv_search_max_file_size', sa.Integer(), nullable=False),
        sa.Column('srv_search_supported_types', sa.JSON(), nullable=False),
        sa.Column('srv_search_worker_count', sa.Integer(), nullable=False),
        sa.Column('srv_search_archive_enabled', sa.Boolean(), nullable=False),
        sa.Column('srv_search_archive_max_depth', sa.Integer(), nullable=False),
        sa.Column('srv_search_archive_max_size', sa.Integer(), nullable=False),
        sa.Column('srv_search_index_max_size', sa.Integer(), nullable=False),
        sa.Column('srv_search_index_cleanup_enabled', sa.Boolean(), nullable=False),
        sa.Column('srv_search_index_cleanup_threshold', sa.Float(), nullable=False),
        sa.Column('srv_search_pruning_enabled', sa.Boolean(), nullable=False),
        sa.Column('srv_search_pruning_schedule', sa.String(length=20), nullable=False),
        sa.Column('srv_search_pruning_start_time', sa.String(length=10), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Insert default configuration
    op.execute("""
        INSERT INTO services_webshare (
            id,
            srv_truenas_host,
            srv_log_level,
            srv_session_log_retention,
            srv_enable_web_terminal,
            srv_bulk_download_pool,
            srv_search_index_pool,
            srv_altroots,
            srv_search_enabled,
            srv_search_directories,
            srv_search_max_file_size,
            srv_search_supported_types,
            srv_search_worker_count,
            srv_search_archive_enabled,
            srv_search_archive_max_depth,
            srv_search_archive_max_size,
            srv_search_index_max_size,
            srv_search_index_cleanup_enabled,
            srv_search_index_cleanup_threshold,
            srv_search_pruning_enabled,
            srv_search_pruning_schedule,
            srv_search_pruning_start_time
        ) VALUES (
            1,
            'localhost',
            'info',
            20,
            false,
            NULL,
            NULL,
            '{}',
            false,
            '[]',
            104857600,
            '["image", "audio", "video", "document", "archive", "text", "disk_image"]',
            4,
            true,
            2,
            524288000,
            10737418240,
            true,
            0.9,
            false,
            'daily',
            '23:00'
        )
    """)


def downgrade():
    op.drop_table('services_webshare')