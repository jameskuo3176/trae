"""Add owner_id column to qor_records table

为 QoR 记录添加上传者字段, 用于:
1. 记录管理界面按 owner 筛选
2. 删除权限控制: owner 本人 / admin 可删除自己上传的记录;
   项目 owner / editor 仅可删除自己上传的; admin 可删除所有.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_qor_records_owner_id', ['owner_id'])
        batch_op.create_foreign_key(
            'fk_qor_records_owner_id_users',
            'users', ['owner_id'], ['id'],
        )

    # 历史数据回填: 若该记录由某次上传产生, 尝试从 source_file 推断;
    # 兜底策略 — 历史记录统一归属 admin 账号 (id=1 通常是第一个管理员).
    bind = op.get_bind()
    try:
        # 取第一个 admin 账号作为历史记录默认 owner
        admin_row = bind.execute(
            sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
        ).fetchone()
        fallback_id = admin_row[0] if admin_row else None
        if fallback_id is not None:
            bind.execute(
                sa.text("UPDATE qor_records SET owner_id = :oid WHERE owner_id IS NULL"),
                {'oid': fallback_id}
            )
    except Exception:
        # 若 users 表尚无 admin 记录, 保持 NULL
        pass


def downgrade():
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.drop_constraint('fk_qor_records_owner_id_users', type_='foreignkey')
        batch_op.drop_index('ix_qor_records_owner_id')
        batch_op.drop_column('owner_id')
