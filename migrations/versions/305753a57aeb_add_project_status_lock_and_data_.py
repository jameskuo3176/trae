"""add project status lock and data snapshots

Revision ID: 305753a57aeb
Revises: fa9d72c024cd
Create Date: 2026-07-20 17:32:50.737092

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '305753a57aeb'
down_revision = 'fa9d72c024cd'
branch_labels = None
depends_on = None


def upgrade():
    # data_snapshots / backup_records 表已由前一次部分执行创建, 此处跳过
    # 仅补齐 projects 表的状态字段 (用原生 SQL 避免 SQLite batch mode 重建表)

    bind = op.get_bind()

    # 检查列是否已存在 (幂等)
    cols = [row[1] for row in bind.execute(sa.text("PRAGMA table_info(projects)")).fetchall()]
    if 'status' not in cols:
        bind.execute(sa.text("ALTER TABLE projects ADD COLUMN status VARCHAR(20) DEFAULT 'active' NOT NULL"))
    if 'locked_at' not in cols:
        bind.execute(sa.text("ALTER TABLE projects ADD COLUMN locked_at DATETIME"))
    if 'locked_by' not in cols:
        bind.execute(sa.text("ALTER TABLE projects ADD COLUMN locked_by INTEGER"))
    if 'lock_reason' not in cols:
        bind.execute(sa.text("ALTER TABLE projects ADD COLUMN lock_reason VARCHAR(500)"))

    # 创建索引
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_status ON projects(status)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_projects_status")
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('lock_reason')
        batch_op.drop_column('locked_by')
        batch_op.drop_column('locked_at')
        batch_op.drop_column('status')
