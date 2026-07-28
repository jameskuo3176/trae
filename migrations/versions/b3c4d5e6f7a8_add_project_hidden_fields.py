"""add project soft delete (hidden) fields

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-28 14:30:00.000000

项目软删除:
  - 新增 status='hidden' 状态 (从 active/locked/archived 转入, 数据保留)
  - 新增 hidden_at, hidden_by 字段追踪隐藏时间和操作人
  - 默认查询 (除 admin 外) 不显示 hidden 项目
  - admin 可通过 /api/admin/projects/hidden 查看并恢复
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # 幂等添加 (与既有 migration 风格一致)
    cols = [row[1] for row in bind.execute(sa.text("PRAGMA table_info(projects)")).fetchall()]
    if 'hidden_at' not in cols:
        bind.execute(sa.text("ALTER TABLE projects ADD COLUMN hidden_at DATETIME"))
    if 'hidden_by' not in cols:
        bind.execute(sa.text("ALTER TABLE projects ADD COLUMN hidden_by INTEGER REFERENCES users(id)"))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('hidden_by')
        batch_op.drop_column('hidden_at')
