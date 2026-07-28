"""生成 5 个 demo 项目的 QoR 数据

结构:
  Project (5 个)
    └── Module (每个 5-10 个, 数字 IP 命名)
        └── base_dir (每个 module 2-3 个, 日期/周次)
            └── Run (每个 base_dir 2-3 个, 不同 cfg/variant)

每个 Run 一条 QorRecord, full_dir = "<base_dir>/<sub_path>/<run_name>"
指标根据方向 (min/max) 随机生成, 模拟真实的面积/时序/功耗/MBB/CG/拥塞数据。

用法:
  python seed_demo_data.py            # 实际写入数据库
  python seed_demo_data.py --preview  # 仅打印生成计划, 不写库
  python seed_demo_data.py --clean    # 清除已有 demo 数据 (按 demo 名前缀)
"""
import os
import sys
import json
import random
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Project, Module, QorRecord


# 演示项目元信息
DEMO_PROJECTS = [
    {
        'name': 'demo_riscv_soc',
        'description': 'RISC-V SoC 综合 demo (面积/时序/功耗指标)',
        'modules': ['cpu_core', 'lsu', 'ifu', 'decode', 'regfile', 'csr', 'branch_pred', 'axi_xbar', 'plic'],
    },
    {
        'name': 'demo_dsp_engine',
        'description': 'DSP 引擎 demo (高 MBB + CG 优化目标)',
        'modules': ['mac_unit', 'fft_core', 'filter_bank', 'coef_rom', 'twiddle_rom', 'addr_gen', 'data_buf'],
    },
    {
        'name': 'demo_video_codec',
        'description': '视频编解码器 demo (大模块, 高拥塞场景)',
        'modules': ['me_engine', 'mc_engine', 'intra_pred', 'deblock', 'cabac', 'transform', 'quant', 'recon'],
    },
    {
        'name': 'demo_eth_mac',
        'description': '以太网 MAC demo (时序关键路径 + 时钟域多)',
        'modules': ['mac_tx', 'mac_rx', 'fifo_async', 'pcs', 'pma', 'mgmt', 'stats'],
    },
    {
        'name': 'demo_ai_accel',
        'description': 'AI 加速器 demo (大算力, 大面积, 高功耗场景)',
        'modules': ['systolic', 'vec_reg', 'load_unit', 'store_unit', 'scheduler', 'dma', 'noc_router'],
    },
]

# 不同的 base_dir 类型: 不同项目用不同场景
BASE_DIR_TEMPLATES = {
    'default': ['2026_0728_weekly', '2026_0804_weekly', '2026_0811_weekly'],
    'short':   ['v1.0', 'v1.1', 'v2.0'],
    'dated':   ['2026Q3_w1', '2026Q3_w2', '2026Q3_w3'],
}

# Run 命名后缀: 体现不同的实现变种/配置
RUN_SUFFIXES = ['baseline', 'cfg1', 'cfg2', 'opt_speed', 'opt_area', 'mbb_aggr']

# 每个 base_dir 内的子目录 (sub_path)
SUB_PATHS = ['main', 'corner_ss', 'corner_ff', 'corner_tt']

# 数字电路指标的合理范围 (用于随机生成)
METRIC_RANGES = {
    'area_total':           (800,   50000),  # um²
    'area_combinational':   (300,   20000),
    'area_sequential':      (200,   15000),
    'area_black_box':       (0,     5000),
    'area_macro':           (0,     8000),
    'wns_setup':            (-1.0,  0.5),    # ns
    'tns_setup':            (-50.0, 5.0),
    'nvp_setup':            (0,     500),
    'wns_hold':             (-0.5,  0.3),
    'tns_hold':             (-20.0, 1.0),
    'nvp_hold':             (0,     100),
    'power_internal':       (0.1,   10.0),   # mW
    'power_switching':      (0.05,  5.0),
    'power_leakage':        (0.01,  1.0),
    'power_total':          (0.2,   15.0),
    'cell_count':           (500,   100000),
    'instance_count':       (500,   100000),
    'net_count':            (1000,  200000),
    'sequential_cell_count':(50,    30000),
    'target_frequency':     (100,   1500),   # MHz
    'achieved_frequency':   (100,   1500),
    'mbb_ratio':            (10.0,  95.0),   # %
    'clock_gating_ratio':   (20.0,  98.0),
    'utilization':          (20.0,  90.0),
    'congestion':           (0.1,   0.9),
    'congestion_h':         (0.1,   0.9),
    'congestion_v':         (0.1,   0.9),
    'congestion_b':         (0.1,   0.9),
}

# 整数型指标 (生成时不带小数)
INTEGER_METRICS = {
    'nvp_setup', 'nvp_hold', 'cell_count', 'instance_count',
    'net_count', 'sequential_cell_count',
}


def _gen_metric_value(name, rng, rand):
    lo, hi = METRIC_RANGES[name]
    v = rand.uniform(lo, hi)
    if name in INTEGER_METRICS:
        return int(v)
    if abs(lo) >= 1 or abs(hi) >= 1:
        return round(v, 4)
    return round(v, 4)


def _build_record(module, version, full_dir, base_seed, rand, days_ago):
    """生成一条 QorRecord, 用 base_seed 决定该 base_dir 的整体趋势"""
    rec = QorRecord(
        module_id=module.id,
        version=version,
        full_dir=full_dir,  # 写到独立列, 便于索引/聚合
        extra_fields=json.dumps({'full_dir': full_dir}),  # 兼容旧数据回填
        recorded_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    # base_seed 控制在 0.7~1.3 之间, 用于模拟"某个 base_dir 整体偏优/偏差"
    factor = 0.7 + (base_seed % 7) * 0.1   # 0.7 ~ 1.3
    for m in METRIC_RANGES:
        v = _gen_metric_value(m, random, rand)
        # 用户约定: 全部时序指标统一为越小越好, 因此和面积/功耗/拥塞一样乘以 factor
        # (优秀的 base_dir 时序违例更小 -> 数值更小)
        # 越大越好: 除以 factor 让优秀 base_dir 数值更大
        # 越小越好: 乘以 factor 让优秀 base_dir 数值更小
        if m in ('area_total', 'area_combinational', 'area_sequential',
                 'area_black_box', 'area_macro', 'cell_count', 'instance_count',
                 'net_count', 'sequential_cell_count',
                 'power_internal', 'power_switching', 'power_leakage', 'power_total',
                 'congestion', 'congestion_h', 'congestion_v', 'congestion_b',
                 'wns_setup', 'wns_hold',
                 'tns_setup', 'tns_hold', 'nvp_setup', 'nvp_hold'):
            v = v * factor
        elif m in ('mbb_ratio', 'clock_gating_ratio', 'achieved_frequency'):
            v = v / factor
        setattr(rec, m, v)
    return rec


def _build_full_dir(base_dir, sub_path, run_name):
    return f"{base_dir}/{sub_path}/{run_name}"


def plan_one_project(proj_def, rand):
    """生成单个项目的所有 record 计划 (不写库)"""
    records = []
    n_modules = rand.randint(5, 10)
    modules = proj_def['modules'][:n_modules] if len(proj_def['modules']) >= n_modules else \
              proj_def['modules'] + [f"{proj_def['name']}_extra_m{i}" for i in range(n_modules - len(proj_def['modules']))]
    # 选一个 base_dir 模板
    bds_template = rand.choice(list(BASE_DIR_TEMPLATES.values()))
    days_offset = 0
    for m_name in modules:
        n_base = rand.randint(2, 3)
        base_dirs = bds_template[:n_base]
        for bd_idx, bd in enumerate(base_dirs):
            n_runs = rand.randint(2, 3)
            sub = rand.choice(SUB_PATHS)
            for run_idx in range(n_runs):
                # run_name: <m_name>_<suffix> 避免同 module 跨 base_dir 歧义
                suffix = RUN_SUFFIXES[run_idx % len(RUN_SUFFIXES)]
                run_name = f"{m_name}_{suffix}"
                full_dir = _build_full_dir(bd, sub, run_name)
                version = f"{bd}_{suffix}"  # version 字段保留 base_dir 信息
                # base_seed 跟 bd_idx 关联, 让同一 base_dir 趋势一致
                base_seed = hash(bd) & 0xFFFF
                days_ago = days_offset % 90
                days_offset += rand.randint(1, 5)
                records.append({
                    'module': m_name,
                    'base_dir': bd,
                    'sub_path': sub,
                    'run_name': run_name,
                    'version': version,
                    'full_dir': full_dir,
                    'base_seed': base_seed,
                    'days_ago': days_ago,
                })
    return records


def write_one_project(proj_def, rand, mark_released=True, verbose=True):
    """实际写入数据库: 返回 (proj, module_count, record_count)"""
    proj = Project.query.filter_by(name=proj_def['name']).first()
    if proj:
        if verbose:
            print(f'  ! 项目 {proj_def["name"]} 已存在, 跳过 (id={proj.id})')
        return proj, 0, 0
    proj = Project(name=proj_def['name'], description=proj_def['description'])
    db.session.add(proj)
    db.session.flush()  # 拿 id

    plan = plan_one_project(proj_def, rand)
    # 按 module 名聚合 records
    mod_index = {}  # name -> Module
    for item in plan:
        m = mod_index.get(item['module'])
        if not m:
            m = Module(project_id=proj.id, name=item['module'], description='')
            db.session.add(m)
            db.session.flush()
            mod_index[item['module']] = m
        rec = _build_record(m, item['version'], item['full_dir'],
                            item['base_seed'], rand, item['days_ago'])
        if mark_released:
            rec.is_released = True
        db.session.add(rec)
    db.session.commit()
    if verbose:
        print(f'  + 项目 {proj.name}: {len(mod_index)} 模块 / {len(plan)} records')
    return proj, len(mod_index), len(plan)


def preview_all():
    """打印生成计划, 不写库"""
    print('===== Demo 数据生成计划 =====\n')
    rand = random.Random(20260728)
    total_records = 0
    for proj_def in DEMO_PROJECTS:
        plan = plan_one_project(proj_def, rand)
        modules = set(it['module'] for it in plan)
        bds = set(it['base_dir'] for it in plan)
        print(f'📦 项目: {proj_def["name"]}')
        print(f'   描述: {proj_def["description"]}')
        print(f'   模块数: {len(modules)}')
        print(f'   base_dir: {sorted(bds)}')
        # 抽样显示一个 module 的 run
        if plan:
            first_mod = plan[0]['module']
            mod_records = [it for it in plan if it['module'] == first_mod]
            print(f'   示例 ({first_mod} 的所有 run):')
            for r in mod_records:
                print(f'     - {r["full_dir"]:<55}  version={r["version"]}')
        print()
        total_records += len(plan)
    print(f'总计: 5 项目 / {total_records} records')


def clean_existing(include_all=False):
    """删除所有 demo 开头的数据 (按名称前缀)

    include_all=True 时, 删除所有非 admin 内部项目 + 它们的模块/记录
    (用于 --clean-all 模式: 完全重置 demo 数据, 留下 admin 账号 / 系统项目)
    """
    if include_all:
        # 先删依赖项目的实体 (按依赖关系反向顺序)
        from models import (
            GroupReview, SubsystemReview, TileReview,
            ProjectMember, DashboardGroup,
            ReviewSnapshot, ReviewFile,
        )
        # 1) reviews
        for M in (TileReview, GroupReview, SubsystemReview, ReviewSnapshot, ReviewFile):
            cnt = M.query.delete()
            if cnt:
                print(f'    - 删除 {M.__name__}: {cnt}')
        # 2) 成员 / dashboard
        for M in (ProjectMember, DashboardGroup):
            cnt = M.query.delete()
            if cnt:
                print(f'    - 删除 {M.__name__}: {cnt}')
        # 3) 项目及其模块/记录 (级联)
        projs = Project.query.all()
        system_names = ['_system', 'system', 'admin', 'default']
        projs = [p for p in projs if p.name.lower() not in system_names]
        for p in projs:
            db.session.delete(p)
        db.session.commit()
        print(f'  全清: 删除 {len(projs)} 非系统项目及其模块/记录')
        return

    demo_names = [d['name'] for d in DEMO_PROJECTS]
    projs = Project.query.filter(Project.name.in_(demo_names)).all()
    rec_count = 0
    mod_count = 0
    for p in projs:
        for m in p.modules.all():
            rec_count += m.records.count()
            mod_count += 1
        db.session.delete(p)
    db.session.commit()
    print(f'  已清理 {len(projs)} 项目 / {mod_count} 模块 / {rec_count} records')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true', help='仅打印计划, 不写库')
    parser.add_argument('--clean', action='store_true', help='清除已有 demo 数据 (按 demo 名前缀)')
    parser.add_argument('--clean-all', action='store_true', help='清除所有非系统项目后重新生成')
    parser.add_argument('--seed', type=int, default=20260728, help='随机种子 (默认 20260728)')
    args = parser.parse_args()

    if args.preview:
        preview_all()
        return

    print('===== 生成 demo 数据 =====')
    rand = random.Random(args.seed)
    with app.app_context():
        if args.clean_all:
            print('清理所有非系统项目...')
            clean_existing(include_all=True)
        elif args.clean:
            print('清理旧 demo 数据...')
            clean_existing()
        total_proj, total_mod, total_rec = 0, 0, 0
        for proj_def in DEMO_PROJECTS:
            proj, mc, rc = write_one_project(proj_def, rand)
            if mc > 0 or rc > 0:
                total_proj += 1
            total_mod += mc
            total_rec += rc
        print(f'\n完成: 新增 {total_proj} 项目 / {total_mod} 模块 / {total_rec} records')
        # 总览
        all_demo = Project.query.filter(Project.name.like('demo_%')).all()
        print(f'当前 demo 数据: {len(all_demo)} 项目')


if __name__ == '__main__':
    main()
