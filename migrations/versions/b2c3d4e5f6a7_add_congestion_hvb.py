"""add congestion h v b columns

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-21 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # 给 qor_records 表添加 congestion_h / congestion_v / congestion_b 三列
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

    for col in ('congestion_h', 'congestion_v', 'congestion_b'):
        if not _column_exists('qor_records', col):
            bind.execute(sa.text(f"ALTER TABLE qor_records ADD COLUMN {col} FLOAT"))

    # 数据迁移: 将旧 congestion 值复制到 congestion_b (作为综合指数的兜底)
    # 仅对 congestion_b 为 NULL 且 congestion 非 NULL 的行生效
    bind.execute(sa.text(
        "UPDATE qor_records SET congestion_b = congestion "
        "WHERE congestion_b IS NULL AND congestion IS NOT NULL"
    ))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('qor_records', schema=None) as batch_op:
            batch_op.drop_column('congestion_b')
            batch_op.drop_column('congestion_v')
            batch_op.drop_column('congestion_h')
    else:
        for col in ('congestion_b', 'congestion_v', 'congestion_h'):
            bind.execute(sa.text(f"ALTER TABLE qor_records DROP COLUMN {col}"))
