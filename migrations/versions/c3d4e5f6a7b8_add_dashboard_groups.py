"""add dashboard groups per project

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    """新增 dashboard_groups 表: 每个 project 可拥有独立 group 视图.

    设计要点:
      - 同一 (project_id, name) 唯一: 不同项目可以有同名 group, 互不干扰
      - project_id NULL 表示全局 group (跨项目共享的视图)
      - config 存 JSON (与 user_dashboards.config 一致)
      - member_ids 存 JSON 数组: 简单实现, 不再建关联表
      - owner_id + is_public 决定可见性
    """
    op.create_table(
        'dashboard_groups',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        # 所属项目: NULL = 全局 group, 非 NULL = 项目专属 group
        sa.Column('project_id', sa.Integer, sa.ForeignKey('projects.id'), nullable=True, index=True),
        # group owner
        sa.Column('owner_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False, index=True),
        # 共享成员 user_id 列表 (JSON 数组); owner 自动包含
        sa.Column('member_ids', sa.Text, nullable=False, default='[]'),
        # 共享配置 (与 user_dashboards.config 同样的 JSON 结构)
        sa.Column('config', sa.Text, nullable=False, default='{}'),
        # 成员登录时是否自动加载此 group 的 config
        sa.Column('shared_default', sa.Boolean, nullable=False, default=False),
        # 是否对项目内所有用户可见 (成员列表外的人只读)
        sa.Column('is_public', sa.Boolean, nullable=False, default=False),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        # 唯一约束: 同一项目下 group 名不能重, 但跨项目可以重
        sa.UniqueConstraint('project_id', 'name', name='uq_dashboard_groups_project_name'),
    )
    # 进一步复合索引: 加速"我加入的 group"查询
    op.create_index('idx_groups_owner', 'dashboard_groups', ['owner_id'])
    op.create_index('idx_groups_project', 'dashboard_groups', ['project_id'])


def downgrade():
    op.drop_index('idx_groups_project', table_name='dashboard_groups')
    op.drop_index('idx_groups_owner', table_name='dashboard_groups')
    op.drop_table('dashboard_groups')
