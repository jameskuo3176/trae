"""为数据库中已有违例的 QorRecord 生成 demo ViolationPath 数据"""
import random
import os
from app import app, db
from models import QorRecord, ViolationPath

random.seed(42)

with app.app_context():
    # 找出所有有时序违例的 QorRecord (wns_setup < 0 或 wns_hold < 0)
    records = QorRecord.query.filter(
        db.or_(QorRecord.wns_setup < 0, QorRecord.wns_hold < 0)
    ).all()
    print(f'找到 {len(records)} 条有违例的 QorRecord')

    # 对每条记录生成违例路径
    timing_groups_pool = ['SRAMCLK', 'CLK_CPU', 'CLK_BUS', 'default', 'REG2REG', 'IN2REG', 'REG2OUT']
    startpoints_pool = [
        'top_alu/inst_alu/U123', 'top_ctrl/state_reg_0_/Q', 'mem_ctrl/inst_buf/U45',
        'data_path/inst_dpath/U234', 'intf_axi/inst_axi/U56', 'core_rf/rf_inst/reg_0_/Q',
        'core_decode/dec_inst/U78', 'clk_div/clk_div_inst/div_reg/Q'
    ]
    endpoints_pool = [
        'top_alu/inst_alu/U456', 'top_ctrl/next_state_reg_1_/D', 'mem_ctrl/inst_buf/U90',
        'data_path/inst_dpath/U345', 'intf_axi/inst_axi/U78', 'core_rf/rf_inst/reg_1_/D',
        'core_decode/dec_inst/U90', 'clk_div/clk_div_inst/sync_reg/D'
    ]

    total_inserted = 0
    for rec in records:
        # 基于 wns 负值判定违例数 (nvp 字段可能为 None, 用 wns 推断)
        # setup 违例: wns_setup 越负, 违例越多
        wns_s = rec.wns_setup or 0
        wns_h = rec.wns_hold or 0
        n_setup = rec.nvp_setup if rec.nvp_setup else (max(1, int(abs(wns_s) * 100)) if wns_s < 0 else 0)
        n_hold = rec.nvp_hold if rec.nvp_hold else (max(1, int(abs(wns_h) * 100)) if wns_h < 0 else 0)
        n_total = min(n_setup + n_hold, 50)  # 每条记录最多 50 条 demo 数据

        if n_total == 0:
            continue

        # 选择 1-2 个 timing group
        n_groups = min(2, max(1, n_total // 10 + 1))
        groups = random.sample(timing_groups_pool, n_groups)

        # 决定 source_file (用第一个 group 作为文件名)
        source_file = f"{groups[0]}.csv"

        paths = []
        for i in range(n_total):
            grp = random.choice(groups)
            # setup 违例 slack 取自 wns_setup 附近的负值, hold 违例取自 wns_hold
            if i < n_setup:
                base_slack = wns_s if wns_s < 0 else -0.1
                slack = base_slack + random.uniform(0, 0.05)  # 略好于 wns
            else:
                base_slack = wns_h if wns_h < 0 else -0.05
                slack = base_slack + random.uniform(0, 0.02)

            paths.append(ViolationPath(
                qor_record_id=rec.id,
                timing_group=grp,
                startpoint=random.choice(startpoints_pool) + f'_{i%5}',
                endpoint=random.choice(endpoints_pool) + f'_{i%5}',
                slack=round(slack, 4),
                depth=random.randint(8, 25),
                pure_depth=random.randint(5, 18),
                cell_delay=round(random.uniform(0.3, 1.5), 4),
                net_delay=round(random.uniform(0.2, 1.0), 4),
                et_slack=round(slack + random.uniform(-0.05, 0.05), 4),
                st_slack=round(slack + random.uniform(-0.05, 0.05), 4),
                st_fanin=random.randint(2, 10),
                st_fanout=random.randint(1, 6),
                et_fanin=random.randint(2, 8),
                et_fanout=random.randint(1, 5),
                source_file=source_file,
            ))

        db.session.bulk_save_objects(paths)
        total_inserted += len(paths)
        print(f'  rec id={rec.id} module={rec.module.name if rec.module else "?"} version={rec.version}: +{len(paths)} paths')

    db.session.commit()
    print(f'\n完成, 共插入 {total_inserted} 条 ViolationPath')

    # 验证
    total = db.session.query(db.func.count(ViolationPath.id)).scalar()
    print(f'数据库 ViolationPath 总数: {total}')
