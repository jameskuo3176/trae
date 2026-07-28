"""Add must_change_password to users table

新增字段:
  - must_change_password (Boolean, default False) - 强制改密标志
  - password_changed_at   (DateTime)             - 最近改密时间 (审计用)

触发场景:
  - 管理员调用 /api/admin/users/<id>/reset-password 重置密码时设为 True
  - 初始化默认账号 (admin/user/release) 时设为 True (首次登录必须改)
  - 用户成功改密后清零

down_revision: c4d5e6f7a8b9 (add_project_db_path) 合并分库 head
"""
from alembic import op
import sqlalchemy as sa

revision = 'g7a8b9c0d1e2'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column('must_change_password', sa.Boolean(),
                      nullable=False, server_default=sa.text('0'))
        )
        batch_op.add_column(
            sa.Column('password_changed_at', sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('password_changed_at')
        batch_op.drop_column('must_change_password')
