"""add db_path to projects for per-project DB

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-28 15:00:00.000000

按项目分库: Project 表新增 db_path, 记录项目独立 .db 文件路径
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    cols = [row[1] for row in bind.execute(sa.text("PRAGMA table_info(projects)")).fetchall()]
    if 'db_path' not in cols:
        bind.execute(sa.text("ALTER TABLE projects ADD COLUMN db_path VARCHAR(500)"))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('db_path')
