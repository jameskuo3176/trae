"""add review detail fields (verdict/key_metrics/findings/decisions/next_steps)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-27 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    """检查列是否已存在 (用于幂等)"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return False
    cols = [c['name'] for c in inspector.get_columns(table)]
    return column in cols


def upgrade():
    """为 TileReview/GroupReview/SubsystemReview 增加细化字段."""
    new_cols = [
        ('verdict',     sa.String(20),  True),
        ('key_metrics', sa.Text,        True),
        ('findings',    sa.Text,        True),
        ('decisions',   sa.Text,        True),
        ('next_steps',  sa.Text,        True),
    ]
    for table in ('tile_reviews', 'group_reviews', 'subsystem_reviews'):
        for name, col_type, nullable in new_cols:
            if not _column_exists(table, name):
                with op.batch_alter_table(table) as batch_op:
                    batch_op.add_column(sa.Column(name, col_type, nullable=nullable))


def downgrade():
    for table in ('tile_reviews', 'group_reviews', 'subsystem_reviews'):
        for name, _, _ in (
            ('verdict', None, None),
            ('key_metrics', None, None),
            ('findings', None, None),
            ('decisions', None, None),
            ('next_steps', None, None),
        ):
            if _column_exists(table, name):
                with op.batch_alter_table(table) as batch_op:
                    batch_op.drop_column(name)
