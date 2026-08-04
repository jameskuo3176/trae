"""Add register_count and raw_dc_report to qor_records

register_count: DC 报告的 total_flops (寄存器数), 与 cell_count (总单元数) 区分
raw_dc_report:  DC 报告原始 JSON 内容, dashboard 表格视图直接渲染
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a8'
down_revision = 'a1b2c3d4e5f6_release_dir'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.add_column(sa.Column('register_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('raw_dc_report', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('qor_records') as batch_op:
        batch_op.drop_column('raw_dc_report')
        batch_op.drop_column('register_count')
