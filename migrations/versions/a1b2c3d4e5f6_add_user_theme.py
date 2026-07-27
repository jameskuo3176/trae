"""add user theme column

Revision ID: a1b2c3d4e5f6
Revises: 305753a57aeb
Create Date: 2026-07-21 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '305753a57aeb'
branch_labels = None
depends_on = None


def upgrade():
    # 给 users 表添加 theme 列 (JSON 字符串, 可为 null)
    # 用原生 SQL + 列存在性检查, 兼容 SQLite/MySQL 且幂等
    bind = op.get_bind()

    def _column_exists(table_name, column_name):
        if bind.dialect.name == 'sqlite':
            rows = bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()
            return any(row[1] == column_name for row in rows)
        else:
            rows = bind.execute(sa.text(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = DATABASE() AND table_name = '{table_name}'"
            )).fetchall()
            return any(row[0] == column_name for row in rows)

    if not _column_exists('users', 'theme'):
        bind.execute(sa.text("ALTER TABLE users ADD COLUMN theme TEXT"))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        # SQLite 不支持直接 DROP COLUMN (老版本), 用 batch_alter_table
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('theme')
    else:
        bind.execute(sa.text("ALTER TABLE users DROP COLUMN theme"))
