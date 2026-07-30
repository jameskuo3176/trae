"""Add release_dir column to qor_records table

为 QoR 记录添加发布目录字段:
- 发布时若未提供 release_dir, 则 fallback 到 full_dir
- 发布者在发布页面可以单独提交 release_dir (覆盖原值)
- 上传 CSV 时若含 release_dir 列, 也可一并保存
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6_release_dir'
# 当前最新迁移: g7a8b9c0d1e3 (version_description) — 合并到统一 head
down_revision = 'g7a8b9c0d1e3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.add_column(sa.Column('release_dir', sa.String(length=500), nullable=True))
        batch_op.create_index('ix_qor_records_release_dir', ['release_dir'])


def downgrade():
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.drop_index('ix_qor_records_release_dir')
        batch_op.drop_column('release_dir')
