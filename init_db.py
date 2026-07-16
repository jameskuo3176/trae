"""数据库初始化脚本

创建数据库表并添加默认管理员账户。

用法:
    python init_db.py            # 仅初始化表和账户
    python init_db.py --demo     # 同时生成演示数据
"""
import os
import sys
import json
import random

from flask import Flask
from models import db, User, Project, Module, QorRecord, UserDashboard
from qor_parser import parse_csv_file

# 使用与 config.py 一致的数据库路径
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'qor_recorder.db')


# =========================================================================
# 演示数据 - 使用用户真实 CSV 格式
# 列: tag, full_dir, comment, reg_count, comb_count, macro_count, total_count,
#     reg_area, comb_area, macro_area, stdcell_area, total_area, no_clock,
#     {CLOCK}_period, {CLOCK}_wns, {CLOCK}_tns, {CLOCK}_path
# =========================================================================

DEMO_CSV_TEMPLATE = """tag,full_dir,comment,reg_count,comb_count,macro_count,total_count,reg_area,comb_area,macro_area,stdcell_area,total_area,no_clock,SRAMCLK_period,SRAMCLK_wns,SRAMCLK_tns,SRAMCLK_path,CLK_CPU_period,CLK_CPU_wns,CLK_CPU_tns,CLK_CPU_path
{tag},{full_dir},{comment},{reg_count},{comb_count},{macro_count},{total_count},{reg_area:.2f},{comb_area:.2f},{macro_area:.2f},{stdcell_area:.2f},{total_area:.2f},{no_clock},{sram_period:.2f},{sram_wns:.3f},{sram_tns:.3f},{sram_path},{cpu_period:.2f},{cpu_wns:.3f},{cpu_tns:.3f},{cpu_path}
"""


def _gen_csv_row(tag, module_name, version_idx, with_power=False):
    """生成单行 CSV 数据（模拟随版本优化的趋势）"""
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

    no_clock = 2
    sram_period = random.choice([2.0, 2.5, 3.0, 4.0])
    cpu_period = random.choice([1.0, 1.25, 1.5, 2.0])

    # WNS 随版本改善（更接近 0 或变正）
    sram_wns = -random.uniform(0.4, 0.01) + version_idx * 0.05
    cpu_wns = -random.uniform(0.3, 0.0) + version_idx * 0.04
    sram_wns = min(sram_wns, 0.1)
    cpu_wns = min(cpu_wns, 0.1)

    sram_tns = sram_wns * random.uniform(1.5, 8.0) * (-1 if sram_wns < 0 else 1)
    cpu_tns = cpu_wns * random.uniform(1.0, 5.0) * (-1 if cpu_wns < 0 else 1)

    sram_path = f"/clk_div/SRAMCLK/inst_{module_name}/end_reg"
    cpu_path = f"/clk_div/CPU_CLK/inst_{module_name}/out_reg"

    return DEMO_CSV_TEMPLATE.format(
        tag=tag,
        full_dir=f"/proj/demo/work/{module_name}/{tag}",
        comment=f"{module_name} {tag} synthesis",
        reg_count=reg_count,
        comb_count=comb_count,
        macro_count=macro,
        total_count=total_count,
        reg_area=reg_area,
        comb_area=comb_area,
        macro_area=macro_area,
        stdcell_area=stdcell_area,
        total_area=total_area,
        no_clock=no_clock,
        sram_period=sram_period,
        sram_wns=sram_wns,
        sram_tns=sram_tns,
        sram_path=sram_path,
        cpu_period=cpu_period,
        cpu_wns=cpu_wns,
        cpu_tns=cpu_tns,
        cpu_path=cpu_path,
    )


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
    """生成演示数据: 2 个项目, 每个项目 6-8 个模块, 每个模块 4-6 个版本"""
    project_specs = [
        {
            'name': 'ChipA',
            'modules': ['top_alu', 'top_ctrl', 'mem_ctrl', 'data_path', 'clk_div', 'intf_axi', 'intf_ahb', 'debug_top'],
        },
        {
            'name': 'ChipB',
            'modules': ['core_rf', 'core_alu', 'core_decode', 'mem_dp', 'sram_wrap', 'pll_wrap'],
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
                    qor = QorRecord(
                        module_id=mod.id,
                        version=tag,
                        area_total=rec.get('area_total'),
                        area_combinational=rec.get('area_combinational'),
                        area_sequential=rec.get('area_sequential'),
                        area_macro=rec.get('area_macro'),
                        wns_setup=rec.get('wns_setup'),
                        tns_setup=rec.get('tns_setup'),
                        cell_count=rec.get('cell_count'),
                        sequential_cell_count=rec.get('sequential_cell_count'),
                        source_file=f'{mod_name}_{tag}.csv',
                    )
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

    db.session.commit()
    print('[OK] 演示数据生成完成')


def init_database(with_demo=False):
    """初始化数据库

    复用 config.py 的配置, 支持 SQLite 与 MySQL 后端。
    通过环境变量 DATABASE_URL 切换:
      - 未设置: 默认 SQLite
      - mysql+pymysql://...: 使用 MySQL

    Schema 管理:
      - 优先使用 Flask-Migrate (flask db upgrade) 管理表结构
      - 若 migrations 目录不存在或迁移失败, 回退到 db.create_all()
      - 对于已有数据库首次接入 Flask-Migrate, 执行 flask db stamp head 标记当前版本
    """
    from config import Config

    app = Flask(__name__)
    app.config.from_object(Config)

    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    print(f'[DB] 使用数据库: {db_uri.split("@")[-1] if "@" in db_uri else db_uri}')

    db.init_app(app)

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
        if User.query.filter_by(username='admin').first() is None:
            admin = User(username='admin', role='admin', display_name='管理员')
            admin.set_password('admin123')
            db.session.add(admin)
            print('[OK] 默认管理员已创建 (用户名: admin, 密码: admin123)')

        # 创建默认普通用户
        if User.query.filter_by(username='user').first() is None:
            user = User(username='user', role='user', display_name='普通用户')
            user.set_password('user123')
            db.session.add(user)
            print('[OK] 默认普通用户已创建 (用户名: user, 密码: user123)')

        db.session.commit()

        # 可选: 生成演示数据
        if with_demo:
            gen_demo_data()

        print('[OK] 数据库初始化完成')


if __name__ == '__main__':
    demo_mode = '--demo' in sys.argv
    init_database(with_demo=demo_mode)

