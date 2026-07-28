"""Add full_dir column to qor_records table

将 full_dir 从 extra_fields JSON 中提取为独立列, 便于按路径聚合和查询。
"""
import json
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    # 添加 full_dir 列
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.add_column(sa.Column('full_dir', sa.String(length=500), nullable=True))
        batch_op.create_index('ix_qor_records_full_dir', ['full_dir'])

    # 回填: 从 extra_fields JSON 中提取 full_dir 到新列
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, extra_fields FROM qor_records WHERE extra_fields IS NOT NULL")).fetchall()
    updated = 0
    for row in rows:
        rec_id, ef = row[0], row[1]
        if not ef:
            continue
        try:
            d = json.loads(ef)
            if isinstance(d, str):
                d = json.loads(d)
            if not isinstance(d, dict):
                continue
            fd = d.get('full_dir')
            if not fd:
                continue
            bind.execute(
                sa.text("UPDATE qor_records SET full_dir = :fd WHERE id = :id"),
                {'fd': str(fd)[:500], 'id': rec_id}
            )
            updated += 1
        except (json.JSONDecodeError, TypeError):
            continue
    print(f'  backfilled full_dir for {updated} existing records')


def downgrade():
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.drop_index('ix_qor_records_full_dir')
        batch_op.drop_column('full_dir')
