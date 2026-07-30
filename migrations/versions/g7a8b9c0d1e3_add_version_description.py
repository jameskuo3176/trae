"""Add version_description column to qor_records table

为 QoR 记录添加版本描述字段:
- owner 角色可在页面上为版本添加描述 (特点/改动/注意事项等)
- viewer 角色只读
- 数据结构无法统一, 字段专门为此场景而设
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g7a8b9c0d1e3'
down_revision = 'g7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'qor_records' not in insp.get_table_names():
        return
    cols = [c['name'] for c in insp.get_columns('qor_records')]
    if 'version_description' not in cols:
        op.add_column('qor_records', sa.Column('version_description', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'qor_records' not in insp.get_table_names():
        return
    cols = [c['name'] for c in insp.get_columns('qor_records')]
    if 'version_description' in cols:
        op.drop_column('qor_records', 'version_description')
