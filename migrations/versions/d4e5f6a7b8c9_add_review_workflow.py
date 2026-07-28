"""add review workflow (tile/group/subsystem/snapshot/file)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    """新增 Review 流程相关 5 张表.

    流程:
      TileReview (weekly_reviews) -> GroupReview -> SubsystemReview -> ReviewSnapshot (含 ReviewFile)
    """
    # ---- tile_reviews ----
    op.create_table(
        'tile_reviews',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('module_id', sa.Integer, sa.ForeignKey('modules.id'), nullable=False),
        sa.Column('record_id', sa.Integer, sa.ForeignKey('qor_records.id'), nullable=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('period', sa.String(20), nullable=True, server_default='weekly'),
        sa.Column('summary', sa.Text, nullable=True),
        sa.Column('metrics_snapshot', sa.Text, nullable=True),
        sa.Column('risks', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('created_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('submitted_by', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('submitted_at', sa.DateTime, nullable=True),
        sa.Column('reviewed_by', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime, nullable=True),
        sa.Column('review_comment', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
    )
    op.create_index('ix_tile_reviews_project_id', 'tile_reviews', ['project_id'])
    op.create_index('ix_tile_reviews_module_id', 'tile_reviews', ['module_id'])
    op.create_index('ix_tile_reviews_record_id', 'tile_reviews', ['record_id'])
    op.create_index('ix_tile_reviews_status', 'tile_reviews', ['status'])

    # ---- group_reviews ----
    op.create_table(
        'group_reviews',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('group_name', sa.String(100), nullable=False),
        sa.Column('period', sa.String(20), nullable=True, server_default='weekly'),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('summary', sa.Text, nullable=True),
        sa.Column('tile_review_ids', sa.Text, nullable=True),
        sa.Column('aggregate', sa.Text, nullable=True),
        sa.Column('risks', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('leader_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('submitted_at', sa.DateTime, nullable=True),
        sa.Column('reviewed_by', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime, nullable=True),
        sa.Column('review_comment', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
    )
    op.create_index('ix_group_reviews_project_id', 'group_reviews', ['project_id'])
    op.create_index('ix_group_reviews_group_name', 'group_reviews', ['group_name'])
    op.create_index('ix_group_reviews_status', 'group_reviews', ['status'])

    # ---- subsystem_reviews ----
    op.create_table(
        'subsystem_reviews',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('subsystem', sa.String(100), nullable=False),
        sa.Column('period', sa.String(20), nullable=True, server_default='weekly'),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('summary', sa.Text, nullable=True),
        sa.Column('group_review_ids', sa.Text, nullable=True),
        sa.Column('aggregate', sa.Text, nullable=True),
        sa.Column('risks', sa.Text, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('manager_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('submitted_at', sa.DateTime, nullable=True),
        sa.Column('reviewed_by', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime, nullable=True),
        sa.Column('review_comment', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
    )
    op.create_index('ix_subsystem_reviews_project_id', 'subsystem_reviews', ['project_id'])
    op.create_index('ix_subsystem_reviews_subsystem', 'subsystem_reviews', ['subsystem'])
    op.create_index('ix_subsystem_reviews_status', 'subsystem_reviews', ['status'])

    # ---- review_snapshots ----
    op.create_table(
        'review_snapshots',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('subsystem_review_id', sa.Integer, sa.ForeignKey('subsystem_reviews.id'), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('snapshot_type', sa.String(20), nullable=True, server_default='milestone'),
        sa.Column('frozen_data', sa.Text, nullable=False),
        sa.Column('record_count', sa.Integer, nullable=True, server_default='0'),
        sa.Column('file_count', sa.Integer, nullable=True, server_default='0'),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('created_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
    )
    op.create_index('ix_review_snapshots_project_id', 'review_snapshots', ['project_id'])
    op.create_index('ix_review_snapshots_subsystem_review_id', 'review_snapshots', ['subsystem_review_id'])

    # ---- review_files ----
    op.create_table(
        'review_files',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('snapshot_id', sa.Integer, sa.ForeignKey('review_snapshots.id'), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=True),
        sa.Column('category', sa.String(50), nullable=True, server_default='rpt'),
        sa.Column('file_size', sa.Integer, nullable=True),
        sa.Column('storage_path', sa.String(1000), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('uploaded_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('uploaded_at', sa.DateTime, nullable=True, server_default=sa.func.now()),
    )
    op.create_index('ix_review_files_snapshot_id', 'review_files', ['snapshot_id'])


def downgrade():
    op.drop_index('ix_review_files_snapshot_id', 'review_files')
    op.drop_table('review_files')
    op.drop_index('ix_review_snapshots_subsystem_review_id', 'review_snapshots')
    op.drop_index('ix_review_snapshots_project_id', 'review_snapshots')
    op.drop_table('review_snapshots')
    op.drop_index('ix_subsystem_reviews_status', 'subsystem_reviews')
    op.drop_index('ix_subsystem_reviews_subsystem', 'subsystem_reviews')
    op.drop_index('ix_subsystem_reviews_project_id', 'subsystem_reviews')
    op.drop_table('subsystem_reviews')
    op.drop_index('ix_group_reviews_status', 'group_reviews')
    op.drop_index('ix_group_reviews_group_name', 'group_reviews')
    op.drop_index('ix_group_reviews_project_id', 'group_reviews')
    op.drop_table('group_reviews')
    op.drop_index('ix_tile_reviews_status', 'tile_reviews')
    op.drop_index('ix_tile_reviews_record_id', 'tile_reviews')
    op.drop_index('ix_tile_reviews_module_id', 'tile_reviews')
    op.drop_index('ix_tile_reviews_project_id', 'tile_reviews')
    op.drop_table('tile_reviews')
