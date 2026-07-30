"""数据库初始化脚本

创建数据库表并添加默认管理员账户。

用法:
    python init_db.py              # 仅初始化表和账户
    python init_db.py --demo       # 初始化 + 生成演示数据 (保留已有)
    python init_db.py --demo --reset  # 清空所有项目/模块/记录, 然后生成 demo
"""
import os
import sys
import json
import random
import glob

from flask import Flask
from models import db, User, Project, Module, QorRecord, UserDashboard
from qor_parser import parse_csv_file
from core.db_routing import switch_to_project
from sqlalchemy import text


def reset_all_data():
    """清空所有业务数据: Project/Module/QorRecord/RunNote/ViolationPath/Review 等级联删除
    保留: User (默认管理员) / alembic_version / user_dashboards
    """
    base_dir = os.path.abspath(os.path.dirname(__file__))
    # 1) 清主库 (projects/modules/records + 关联业务表)
    print('[RESET] 清空主库业务数据...')
    db.session.execute(text("PRAGMA foreign_keys=OFF"))
    for table in [
        'violation_paths', 'run_notes', 'review_files', 'review_snapshots',
        'group_reviews', 'subsystem_reviews', 'tile_reviews',
        'qor_records', 'modules', 'projects',
        '_alembic_tmp_projects',
    ]:
        try:
            db.session.execute(text(f"DELETE FROM {table}"))
            print(f'[RESET]   cleared {table}')
        except Exception as e:
            print(f'[WARN]   skip {table}: {e}')
            db.session.rollback()
    db.session.execute(text("PRAGMA foreign_keys=ON"))
    db.session.commit()
    # 2) 清所有项目库文件 (qor_p_*.db)
    for pat in ['qor_p_*.db', 'qor_project_*.db']:
        for p in glob.glob(os.path.join(base_dir, pat)):
            try:
                os.remove(p)
                print(f'[RESET] 删除项目库: {os.path.basename(p)}')
            except Exception as e:
                print(f'[WARN] 删除项目库失败: {p}: {e}')
    print('[RESET] 所有业务数据已清空, 保留用户账户')

# 使用与 config.py 一致的数据库路径
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'qor_recorder.db')


# =========================================================================
# 演示数据 - 使用用户真实 CSV 格式
# 列: tag, full_dir, comment, reg_count, comb_count, macro_count, total_count,
#     reg_area, comb_area, macro_area, stdcell_area, total_area, no_clock,
#     {CLOCK}_period, {CLOCK}_wns, {CLOCK}_tns, {CLOCK}_path
# =========================================================================

"""时钟定义: (default_period, is_interface, kind)
   is_interface=True 的时钟会被 parser 排除 (I2C/C2O/I2O)
   kind 决定随机分布: 'core'/'cpu'/'interface'"""
DEMO_CLOCK_DEFS = {
    'SYS_CLK':  {'default_period': 2.0,  'is_interface': False, 'kind': 'core'},
    'SRAMCLK':  {'default_period': 2.5,  'is_interface': False, 'kind': 'core'},
    'CLK_CPU':  {'default_period': 1.25, 'is_interface': False, 'kind': 'cpu'},
    'I2C_CLK':  {'default_period': 10.0, 'is_interface': True,  'kind': 'interface'},
    'C2O_BUS':  {'default_period': 8.0,  'is_interface': True,  'kind': 'interface'},
    'I2O_PHY':  {'default_period': 5.0,  'is_interface': True,  'kind': 'interface'},
}


# 各模块的时钟组合 (每模块不同时钟, 覆盖各种场景)
# - top_cpu/top_mem/top_alu: 各带一个接口时钟 (I2C/C2O/I2O), 验证排除聚合
# - top_ctrl: 纯核心+CPU, 无接口 (验证 "正 tns 按 0 累加")
# - top_dma: 全域+1 接口 (4 时钟)
# - top_uart: 核心+2 接口 (3 时钟)
# - top_jtag: 单时钟 (1 时钟)
# - top_ddr: 内存+2 接口 (4 时钟)
# - top_ahb: CPU+1 接口
# - top_axi: 全核心域, 无接口
DEMO_MODULE_CLOCK_SETS = {
    'top_cpu':   ['SYS_CLK', 'CLK_CPU', 'I2C_CLK'],
    'top_mem':   ['SYS_CLK', 'SRAMCLK', 'C2O_BUS'],
    'top_alu':   ['SYS_CLK', 'CLK_CPU', 'I2O_PHY'],
    'top_ctrl':  ['SYS_CLK', 'CLK_CPU'],
    'top_dma':   ['SYS_CLK', 'SRAMCLK', 'CLK_CPU', 'I2C_CLK'],
    'top_uart':  ['SYS_CLK', 'I2C_CLK', 'C2O_BUS'],
    'top_jtag':  ['SYS_CLK'],
    'top_ddr':   ['SYS_CLK', 'SRAMCLK', 'C2O_BUS', 'I2O_PHY'],
    'top_ahb':   ['SYS_CLK', 'CLK_CPU', 'C2O_BUS'],
    'top_axi':   ['SYS_CLK', 'SRAMCLK', 'CLK_CPU'],
    # RISC-V Demo 模块
    'cpu_core':  ['SYS_CLK', 'CLK_CPU'],
    'lsu':       ['SYS_CLK', 'CLK_CPU'],
    'ifu':       ['SYS_CLK', 'CLK_CPU'],
    'decode':    ['SYS_CLK'],
    'regfile':   ['SYS_CLK', 'CLK_CPU'],
    'csr':       ['SYS_CLK', 'CLK_CPU'],
    'exu':       ['SYS_CLK', 'CLK_CPU'],
    'fpu':       ['SYS_CLK', 'CLK_CPU'],
    'ALU':       ['SYS_CLK', 'CLK_CPU'],
    'bpu':       ['SYS_CLK', 'CLK_CPU'],
    'cache':     ['SYS_CLK', 'SRAMCLK'],
    'axi':       ['SYS_CLK', 'SRAMCLK'],
}


# CSV header 前后固定段
# Setup 段: no_clock (为兼容旧版 parser, 也输出 reg/comb/macro/total_count 等)
# Hold 段: 同样按时钟输出 _wns/_tns/_path (用于验证 hold 时序聚合)
DEMO_CSV_HEADER_PREFIX = "tag,full_dir,comment,reg_count,comb_count,macro_count,total_count,reg_area,comb_area,macro_area,stdcell_area,total_area,no_clock"
DEMO_CSV_TAIL = "mbb_ratio,clock_gating_ratio,utilization,congestion_h,congestion_v,congestion_b"


def _build_header(clock_names):
    """根据时钟列表拼 CSV header (Setup + Hold 段)"""
    cols = [DEMO_CSV_HEADER_PREFIX]
    for c in clock_names:
        # Setup: period/wns/tns/path
        cols.extend([f"{c}_period", f"{c}_wns", f"{c}_tns", f"{c}_path"])
    for c in clock_names:
        # Hold: wns/tns/path (无 period)
        cols.extend([f"{c}_hold_wns", f"{c}_hold_tns", f"{c}_hold_path"])
    cols.append(DEMO_CSV_TAIL)
    return ",".join(cols)


def _gen_clock_value(clock_name, version_idx):
    """为某时钟生成 (period, wns, tns, path_count) 四元组

    时钟的"性格"由 DEMO_CLOCK_DEFS 决定:
      - core     : 早期 -0.4~-0.05, 后期 -0.05~+0.1
      - cpu      : 早期 -0.2~0, 后期 -0.05~+0.2 (常正余量, 验证 sum 时被钳为 0)
      - interface: 一直违例 (按业务规则, 接口时钟排除累加, 但其值仍模拟真实)
    """
    defn = DEMO_CLOCK_DEFS.get(clock_name, {'kind': 'core'})
    kind = defn['kind']
    period = defn['default_period'] + random.uniform(-0.1, 0.1)

    if kind == 'core':
        base_wns = -random.uniform(0.4, 0.05) + version_idx * 0.06
    elif kind == 'cpu':
        base_wns = -random.uniform(0.2, 0.0) + version_idx * 0.05
    else:  # interface
        base_wns = -random.uniform(0.5, 0.1) + version_idx * 0.02
    wns = max(min(base_wns, 0.3), -0.6)

    if wns < -0.01:
        tns = wns * random.uniform(2.0, 6.0)  # 违例: tns 显著负值
        path_count = random.randint(1, 8)
    elif wns < 0.01:
        tns = 0.0
        path_count = 0
    else:
        # 正余量: tns 0~+1.0 (验证 sum 时被钳为 0)
        tns = random.uniform(0.0, 1.0) if random.random() < 0.3 else 0.0
        path_count = 0

    return round(period, 3), round(wns, 4), round(tns, 4), path_count


def _gen_hold_value(clock_name, version_idx):
    """为某时钟生成 (hold_wns, hold_tns, hold_path) 三元组

    Hold 时序的特点: 多为正余量或轻微违例 (与 Setup 反向)
      - 早期版本 hold 违例多一些 (随 setup 优化, hold 变差)
      - 后期版本 hold 多为正余量
    """
    defn = DEMO_CLOCK_DEFS.get(clock_name, {'kind': 'core'})
    kind = defn['kind']

    if kind == 'core':
        # 核心时钟: hold 早期轻微违例, 后期正余量
        base_hold_wns = -random.uniform(0.1, 0.0) + version_idx * 0.04
    elif kind == 'cpu':
        base_hold_wns = -random.uniform(0.05, 0.0) + version_idx * 0.03
    else:  # interface
        base_hold_wns = random.uniform(-0.05, 0.1)  # 接口 hold 多为正
    hold_wns = max(min(base_hold_wns, 0.2), -0.2)

    if hold_wns < -0.005:
        hold_tns = hold_wns * random.uniform(1.5, 4.0)
        hold_path = random.randint(0, 5)
    else:
        hold_tns = 0.0
        hold_path = 0

    return round(hold_wns, 4), round(hold_tns, 4), hold_path


def _gen_csv_row(tag, module_name, version_idx, with_power=False):
    """生成单行 CSV 数据 (动态时钟列, 模拟随版本优化的趋势)"""
    random.seed(hash(module_name + tag) % 65536)

    # 随版本递增，单元数略微增加
    base_reg = random.randint(200, 2000)
    base_comb = random.randint(1000, 8000)
    macro = random.choice([0, 0, 1, 2, 4, 8])

    reg_count = base_reg + version_idx * random.randint(5, 30)
    comb_count = base_comb + version_idx * random.randint(20, 200)
    total_count = reg_count + comb_count + macro

    # 面积随版本略微优化（下降）
    reg_area = reg_count * random.uniform(0.45, 0.55) * (1 - version_idx * 0.01)
    comb_area = comb_count * random.uniform(0.18, 0.28) * (1 - version_idx * 0.015)
    macro_area = macro * random.uniform(800, 1500)
    stdcell_area = reg_area + comb_area
    total_area = stdcell_area + macro_area

    # 时钟组合: 根据模块名选, 不在表中的模块 fallback 到默认 (SYS_CLK + CLK_CPU)
    clock_names = DEMO_MODULE_CLOCK_SETS.get(module_name, ['SYS_CLK', 'CLK_CPU'])
    no_clock = len(clock_names)

    # 物理实现指标（随版本优化）
    mbb_ratio = min(0.05 + version_idx * 0.12 + random.uniform(-0.03, 0.03), 0.95)
    clock_gating_ratio = min(0.1 + version_idx * 0.15 + random.uniform(-0.05, 0.05), 0.9)
    utilization = min(0.4 + version_idx * 0.05 + random.uniform(-0.08, 0.08), 0.92)
    # 拥塞指数: H=水平, V=垂直, B=Both(综合, 通常为 max(H,V) 或加权)
    base_cong = max(0.05, min(0.5 - version_idx * 0.03 + random.uniform(-0.05, 0.05), 0.6))
    congestion_h = max(0.02, min(base_cong * random.uniform(0.8, 1.1), 0.95))
    congestion_v = max(0.02, min(base_cong * random.uniform(0.9, 1.2), 0.95))
    # B 取 H/V 较大者作为综合拥塞 (典型定义)
    congestion_b = max(congestion_h, congestion_v)

    # 频率: 随版本优化, 越后期越接近目标
    target_freq = 500.0  # 500 MHz
    achieved_freq = target_freq * (0.85 + version_idx * 0.02 + random.uniform(-0.02, 0.02))

    # 拼接 header + 数据行
    header = _build_header(clock_names)
    parts = [
        tag,
        f"/proj/demo/work/{module_name}/{tag}",
        f"{module_name} {tag} synthesis",
        reg_count, comb_count, macro, total_count,
        f"{reg_area:.2f}", f"{comb_area:.2f}", f"{macro_area:.2f}",
        f"{stdcell_area:.2f}", f"{total_area:.2f}",
        no_clock,
    ]
    # Setup 段
    for c in clock_names:
        period, wns, tns, path_count = _gen_clock_value(c, version_idx)
        parts.extend([f"{period:.3f}", f"{wns:.4f}", f"{tns:.4f}", path_count])
    # Hold 段
    for c in clock_names:
        hold_wns, hold_tns, hold_path = _gen_hold_value(c, version_idx)
        parts.extend([f"{hold_wns:.4f}", f"{hold_tns:.4f}", hold_path])
    # 物理实现段
    parts.extend([
        f"{mbb_ratio:.3f}", f"{clock_gating_ratio:.3f}", f"{utilization:.3f}",
        f"{congestion_h:.3f}", f"{congestion_v:.3f}", f"{congestion_b:.3f}",
    ])
    return f"{header}\n{','.join(str(p) for p in parts)}\n"


def _gen_power_csv_row(tag, module_name, version_idx):
    """生成单行功耗 CSV 数据"""
    random.seed(hash(module_name + tag + 'power') % 65536)
    # 功耗随版本略微下降
    internal = random.uniform(2.0, 15.0) * (1 - version_idx * 0.02)
    switching = random.uniform(1.0, 8.0) * (1 - version_idx * 0.025)
    leakage = random.uniform(0.05, 0.5)
    total = internal + switching + leakage
    return f"tag,power_internal,power_switching,power_leakage,power_total\n{tag},{internal:.3f},{switching:.3f},{leakage:.3f},{total:.3f}\n"


def gen_demo_data():
    """生成演示数据: 3 个项目, 每个项目 6-12 个模块, 每个模块 4-6 个版本
    时钟组合按模块名自动选择 (见 DEMO_MODULE_CLOCK_SETS)
    """
    project_specs = [
        {
            'name': 'ChipA',
            # 涵盖: 单时钟, 多接口, CPU域, SRAM域, 各种组合
            'modules': ['top_cpu', 'top_mem', 'top_alu', 'top_ctrl', 'top_dma', 'top_uart', 'top_jtag', 'top_ddr'],
        },
        {
            'name': 'ChipB',
            'modules': ['top_ahb', 'top_axi', 'top_cpu', 'top_mem', 'top_ctrl', 'top_dma'],
        },
        {
            'name': 'RISC-V Demo',
            'modules': ['cpu_core', 'lsu', 'ifu', 'decode', 'regfile', 'csr', 'exu', 'fpu', 'ALU', 'bpu', 'cache', 'axi'],
        },
    ]
    tags = ['v1.0', 'v1.1', 'v1.2', 'v2.0', 'v2.1', 'v2.2']

    for spec in project_specs:
        # 创建项目
        proj = Project.query.filter_by(name=spec['name']).first()
        if not proj:
            proj = Project(name=spec['name'], description=f'{spec["name"]} demo project')
            db.session.add(proj)
            db.session.flush()
        # 提交主库 (Project 在主库), 然后切换到项目库操作 Module/Record
        db.session.commit()

        # 切到项目库 (自动创建项目库文件 + 启用 ORM 路由)
        with switch_to_project(proj.id):
            for mod_name in spec['modules']:
                mod = Module.query.filter_by(project_id=proj.id, name=mod_name).first()
                if not mod:
                    mod = Module(project_id=proj.id, name=mod_name, description=f'{mod_name} module')
                    db.session.add(mod)
                    db.session.flush()

                # 清理旧记录
                QorRecord.query.filter_by(module_id=mod.id).delete()

            # 每个 module 随机生成 4-6 个版本
            num_versions = random.randint(4, 6)
            version_tags = tags[:num_versions]

            for vi, tag in enumerate(version_tags):
                # 生成 QoR CSV 行
                csv_line = _gen_csv_row(tag, mod_name, vi)
                result = parse_csv_file(csv_line.encode('utf-8'),
                                        default_project=proj.name,
                                        default_module=mod_name,
                                        default_version=tag)
                if result['records']:
                    rec = result['records'][0]
                    
                    # 从 extra_fields 中解析物理实现指标
                    extra = {}
                    if rec.get('extra_fields'):
                        try:
                            extra = json.loads(rec['extra_fields'])
                            if isinstance(extra, str):
                                extra = json.loads(extra)
                        except:
                            extra = {}
                    
                    qor = QorRecord(
                            module_id=mod.id,
                            version=tag,
                            full_dir=f"/proj/demo/work/{mod_name}/{tag}",
                            area_total=rec.get('area_total'),
                            area_combinational=rec.get('area_combinational'),
                            area_sequential=rec.get('area_sequential'),
                            area_macro=rec.get('area_macro'),
                            cell_count=rec.get('cell_count'),
                            instance_count=rec.get('instance_count') or rec.get('comb_count'),
                            net_count=rec.get('net_count') or rec.get('reg_count'),
                            sequential_cell_count=rec.get('sequential_cell_count'),
                            wns_setup=rec.get('wns_setup'),
                            tns_setup=rec.get('tns_setup'),
                            nvp_setup=rec.get('nvp_setup'),
                            wns_hold=rec.get('wns_hold'),
                            tns_hold=rec.get('tns_hold'),
                            nvp_hold=rec.get('nvp_hold'),
                            target_frequency=rec.get('target_frequency') or 500.0,
                            achieved_frequency=rec.get('achieved_frequency'),
                            source_file=f'{mod_name}_{tag}.csv',
                            # 物理实现指标（新解析器已识别到顶级字段；旧 CSV 则从 extra_fields 兜底）
                            mbb_ratio=rec.get('mbb_ratio') or (float(extra.get('mbb_ratio')) if extra.get('mbb_ratio') else None),
                            clock_gating_ratio=rec.get('clock_gating_ratio') or (float(extra.get('clock_gating_ratio')) if extra.get('clock_gating_ratio') else None),
                            utilization=rec.get('utilization') or (float(extra.get('utilization')) if extra.get('utilization') else None),
                            congestion=rec.get('congestion') or (float(extra.get('congestion')) if extra.get('congestion') else None),
                            congestion_h=rec.get('congestion_h'),
                            congestion_v=rec.get('congestion_v'),
                            congestion_b=rec.get('congestion_b'),
                        )
                    # 拥塞指数向后兼容同步 (congestion <-> congestion_b)
                    if qor.congestion_b is not None and qor.congestion is None:
                        qor.congestion = qor.congestion_b
                    elif qor.congestion is not None and qor.congestion_b is None:
                        qor.congestion_b = qor.congestion
                    # extra_fields 保存 comment, full_dir, stdcell_area, clocks 等
                    # 注意: parser 返回的 extra_fields 已是 JSON 字符串，直接赋值即可
                    qor.extra_fields = rec.get('extra_fields')
                    db.session.add(qor)

                    # 给约 40% 的版本添加功耗数据
                    if random.random() < 0.4:
                        power_csv = _gen_power_csv_row(tag, mod_name, vi)
                        p_result = parse_csv_file(power_csv.encode('utf-8'),
                                                  default_project=proj.name,
                                                  default_module=mod_name,
                                                  default_version=tag)
                        if p_result['records']:
                            prec = p_result['records'][0]
                            qor.power_internal = prec.get('power_internal')
                            qor.power_switching = prec.get('power_switching')
                            qor.power_leakage = prec.get('power_leakage')
                            qor.power_total = prec.get('power_total')
            # 提交项目库 (Module/QorRecord 在项目库)
            db.session.commit()
    print('[OK] 演示数据生成完成')


def init_database(with_demo=False):
    """初始化数据库

    复用 create_app() 工厂 (与主程序一致, 启用 db_routing 事件监听)
    """
    from app import create_app

    app = create_app()

    # 初始化 Flask-Migrate
    try:
        from flask_migrate import Migrate, upgrade, stamp
        Migrate(app, db)
        migrations_dir = os.path.join(BASE_DIR, 'migrations')
        has_migrations = os.path.isdir(migrations_dir)
    except ImportError:
        has_migrations = False
        upgrade = stamp = None

    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        print(f'[DB] 使用数据库: {db_uri.split("@")[-1] if "@" in db_uri else db_uri}')

        # MySQL: 先创建数据库 (若不存在)
        if db_uri.startswith('mysql'):
            try:
                from sqlalchemy import create_engine, text
                # 连接到 MySQL 服务器 (不指定数据库), 创建目标数据库
                db_name = db_uri.split('/')[-1].split('?')[0]
                server_uri = '/'.join(db_uri.split('/')[:-1]) + '/?charset=utf8mb4'
                server_engine = create_engine(server_uri)
                with server_engine.connect() as conn:
                    conn.execute(text(
                        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    ))
                    conn.commit()
                server_engine.dispose()
                print(f'[OK] MySQL 数据库 `{db_name}` 已就绪')
            except Exception as e:
                print(f'[WARN] MySQL 数据库创建失败 (可能无权限, 请手动创建): {e}')

        # 尝试用 Flask-Migrate 升级 schema
        migrate_ok = False
        if has_migrations:
            try:
                # 检查是否已有 alembic_version 表 (即是否已接入 migrate)
                from sqlalchemy import inspect
                inspector = inspect(db.engine)
                if inspector.has_table('alembic_version'):
                    # 已接入, 执行 upgrade
                    upgrade()
                    print('[OK] Flask-Migrate schema 已升级到最新版本')
                else:
                    # 首次接入: 先用 create_all 创建表, 再 stamp 标记当前版本
                    db.create_all()
                    stamp()
                    print('[OK] 数据库表已创建 (Flask-Migrate 首次接入, 已 stamp 当前版本)')
                migrate_ok = True
            except Exception as e:
                print(f'[WARN] Flask-Migrate 升级失败, 回退到 db.create_all(): {e}')

        if not migrate_ok:
            db.create_all()
            print('[OK] 数据库表已创建 (db.create_all)')

        # 创建默认管理员
        # 注意: admin@2026 符合密码策略 (8+ 位, 含字母+数字), 首次登录后请立即修改
        if User.query.filter_by(username='admin').first() is None:
            admin = User(username='admin', role='admin', display_name='管理员')
            admin.set_password('admin@2026')
            db.session.add(admin)
            print('[OK] 默认管理员已创建 (用户名: admin, 密码: admin@2026)')

        # 创建默认普通用户
        if User.query.filter_by(username='user').first() is None:
            user = User(username='user', role='user', display_name='普通用户')
            user.set_password('user@2026')
            db.session.add(user)
            print('[OK] 默认普通用户已创建 (用户名: user, 密码: user@2026)')

        # 创建默认 release 账号 (对外只读, 仅可查看已发布数据)
        if User.query.filter_by(username='release').first() is None:
            rel = User(username='release', role='release', display_name='Release 客户')
            rel.set_password('release@2026')
            db.session.add(rel)
            print('[OK] 默认 release 账号已创建 (用户名: release, 密码: release@2026)')

        db.session.commit()

        # 可选: 生成演示数据
        if with_demo:
            gen_demo_data()

        print('[OK] 数据库初始化完成')


if __name__ == '__main__':
    demo_mode = '--demo' in sys.argv
    reset_mode = '--reset' in sys.argv
    if reset_mode:
        # 先创建 app 拿到 db session, 再清空
        from app import create_app
        app = create_app()
        with app.app_context():
            reset_all_data()
    init_database(with_demo=demo_mode)

