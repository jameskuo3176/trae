"""Demo CSV 数据模拟上传脚本

用途:
  生成符合 DC 综合流程导出的 CSV 报告 (qor / power / violation / notes),
  通过 QoR Recorder 内部 import 流程写入数据库, 用于演示和验证。

DB 命名约定:
  本脚本会在 BASE_DIR 下创建独立的项目 DB 文件:
    ${project}_feintqor_${database_type}.db
  例如:
    myproject_feintqor_sqlite.db
    myproject_feintqor_sql.db
    myproject_feintqor_mongodb.db

支持 3 种 database_type (与系统 DB_TYPE 一致):
  - sqlite   SQLite 本地文件 (默认, 真正可执行上传+验证+清理)
  - sql      MySQL/PostgreSQL (需要预先配置 DATABASE_URL, 否则仅打印计划)
  - mongodb  MongoDB (需要预先配置 MONGODB_URI, 否则仅打印计划)

用法:
  # SQLite 模式 (默认, 完整端到端)
  python demo_csv_upload.py --project myproject --db-type sqlite

  # 仅生成 CSV 不上传
  python demo_csv_upload.py --project myproject --preview

  # 自定义版本/模块数
  python demo_csv_upload.py --project myproject --modules 4 --versions 6

  # 清理指定 DB 文件
  python demo_csv_upload.py --project myproject --db-type sqlite --cleanup

退出码:
  0 - 成功
  1 - 参数错误 / 环境错误
  2 - 上传失败
  3 - 验证失败
"""
import os
import sys
import csv
import json
import shutil
import random
import argparse
import logging
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

VALID_DB_TYPES = ('sqlite', 'sql', 'mongodb')

# 默认 demo 项目
DEMO_MODULES = [
    'cpu_core', 'lsu', 'ifu', 'decode', 'regfile',
    'csr', 'branch_pred', 'axi_xbar', 'plic', 'cache_ctrl',
]

# 时钟列样例 (与 §15 文档一致)
CLOCK_SETS = {
    'cpu_core':    ['SYS_CLK', 'CLK_CPU'],
    'lsu':         ['SYS_CLK', 'CLK_CPU'],
    'ifu':         ['SYS_CLK', 'CLK_CPU'],
    'decode':      ['SYS_CLK'],
    'regfile':     ['SYS_CLK', 'CLK_CPU'],
    'csr':         ['SYS_CLK', 'CLK_CPU'],
    'branch_pred': ['SYS_CLK', 'CLK_CPU'],
    'axi_xbar':    ['SYS_CLK', 'AXI_CLK'],
    'plic':        ['SYS_CLK'],
    'cache_ctrl':  ['SYS_CLK', 'SRAMCLK'],
}

# 数字电路合理范围
METRIC_RANGES = {
    'area_total':           (500,   30000),
    'area_combinational':   (200,   12000),
    'area_sequential':      (150,   8000),
    'area_black_box':       (0,     2000),
    'area_macro':           (0,     5000),
    'wns_setup':            (-0.8,  0.3),
    'tns_setup':            (-30.0, 2.0),
    'nvp_setup':            (0,     200),
    'wns_hold':             (-0.3,  0.2),
    'tns_hold':             (-10.0, 0.5),
    'nvp_hold':             (0,     50),
    'power_internal':       (0.1,   8.0),
    'power_switching':      (0.05,  4.0),
    'power_leakage':        (0.01,  0.8),
    'power_total':          (0.2,   12.0),
    'cell_count':           (300,   60000),
    'instance_count':       (300,   65000),
    'net_count':            (600,   120000),
    'sequential_cell_count':(30,    18000),
    'target_frequency':     (100,   1200),
    'achieved_frequency':   (100,   1200),
    'mbb_ratio':            (10.0,  95.0),
    'clock_gating_ratio':   (20.0,  98.0),
    'utilization':          (25.0,  90.0),
    'congestion_h':         (0.05,  0.85),
    'congestion_v':         (0.05,  0.85),
    'congestion_b':         (0.05,  0.85),
}
INTEGER_METRICS = {
    'nvp_setup', 'nvp_hold', 'cell_count', 'instance_count',
    'net_count', 'sequential_cell_count',
}

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
)
log = logging.getLogger('demo_csv_upload')


# ---------------------------------------------------------------------------
# DB 文件命名
# ---------------------------------------------------------------------------
# 系统实际使用: BASE_DIR/qor_p_<project_id>.db (按项目独立分库)
# demo 用户视角命名: ${project}_feintqor_${db_type}.db (仅用于日志展示和概念对齐)
# ---------------------------------------------------------------------------
def project_db_filename(project_name: str, db_type: str) -> str:
    """生成 demo 用户视角的 DB 文件名: ${project}_feintqor_${db_type}.db

    project_name 中的非法字符替换为下划线, 避免跨平台文件名问题.
    """
    safe = ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in project_name)
    return f"{safe}_feintqor_{db_type}.db"


def project_db_path(project_name: str, db_type: str) -> str:
    """返回 demo 用户视角的 DB 文件路径 (仅用于日志展示, 系统实际使用 qor_p_<id>.db)"""
    from config import BASE_DIR
    return os.path.join(BASE_DIR, project_db_filename(project_name, db_type))


def actual_project_db_path(project_id: int) -> str:
    """返回系统实际的项目 DB 文件路径: BASE_DIR/qor_p_<project_id>.db"""
    from core.project_db import project_db_path as _project_db_path
    return _project_db_path(project_id)


# ---------------------------------------------------------------------------
# CSV 数据生成
# ---------------------------------------------------------------------------
def _gen_metric(name: str, rand: random.Random) -> object:
    lo, hi = METRIC_RANGES[name]
    v = rand.uniform(lo, hi)
    if name in INTEGER_METRICS:
        return int(v)
    return round(v, 4)


def gen_qor_csv(project: str, modules: list, versions: list, out_dir: str,
                rand: random.Random) -> str:
    """生成 qor CSV (data_type=qor), 一行 = 一个 run, 含多时钟列"""
    path = os.path.join(out_dir, f'{project}_qor.csv')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        # 表头: 通用列 + 每个模块的时钟列 (取所有模块时钟并集)
        all_clocks = set()
        for m in modules:
            for c in CLOCK_SETS.get(m, ['SYS_CLK']):
                all_clocks.add(c)
        clock_headers = []
        for c in sorted(all_clocks):
            clock_headers.extend([f'{c}_period', f'{c}_wns', f'{c}_tns', f'{c}_path'])
        header = [
            'module_name', 'version', 'full_dir', 'comment',
            'area_total', 'area_combinational', 'area_sequential',
            'area_black_box', 'area_macro',
            'wns_setup', 'tns_setup', 'nvp_setup',
            'wns_hold', 'tns_hold', 'nvp_hold',
            'power_internal', 'power_switching', 'power_leakage', 'power_total',
            'cell_count', 'instance_count', 'net_count', 'sequential_cell_count',
            'target_frequency', 'achieved_frequency',
            'mbb_ratio', 'clock_gating_ratio', 'utilization',
            'congestion_h', 'congestion_v', 'congestion_b',
        ] + clock_headers
        w.writerow(header)
        # 数据: 每个 module × 每个 version 一行
        for mod in modules:
            clocks = CLOCK_SETS.get(mod, ['SYS_CLK'])
            for ver in versions:
                full_dir = f"/demo_runs/{project}/{ver}/{mod}"
                row = [
                    mod, ver, full_dir, f'demo run {ver}',
                    _gen_metric('area_total', rand),
                    _gen_metric('area_combinational', rand),
                    _gen_metric('area_sequential', rand),
                    _gen_metric('area_black_box', rand),
                    _gen_metric('area_macro', rand),
                    _gen_metric('wns_setup', rand),
                    _gen_metric('tns_setup', rand),
                    _gen_metric('nvp_setup', rand),
                    _gen_metric('wns_hold', rand),
                    _gen_metric('tns_hold', rand),
                    _gen_metric('nvp_hold', rand),
                    _gen_metric('power_internal', rand),
                    _gen_metric('power_switching', rand),
                    _gen_metric('power_leakage', rand),
                    _gen_metric('power_total', rand),
                    _gen_metric('cell_count', rand),
                    _gen_metric('instance_count', rand),
                    _gen_metric('net_count', rand),
                    _gen_metric('sequential_cell_count', rand),
                    _gen_metric('target_frequency', rand),
                    _gen_metric('achieved_frequency', rand),
                    _gen_metric('mbb_ratio', rand),
                    _gen_metric('clock_gating_ratio', rand),
                    _gen_metric('utilization', rand),
                    _gen_metric('congestion_h', rand),
                    _gen_metric('congestion_v', rand),
                    _gen_metric('congestion_b', rand),
                ]
                # 时钟列
                for c in sorted(all_clocks):
                    if c in clocks:
                        period = round(rand.uniform(1.0, 5.0), 2)
                        wns = round(rand.uniform(-0.5, 0.2), 3)
                        tns = round(rand.uniform(-2.0, 0.0), 3)
                        path_str = f"/{mod}/{c.lower()}/end_reg"
                    else:
                        # 该模块无此时钟, 填空
                        period, wns, tns, path_str = '', '', '', ''
                    row.extend([period, wns, tns, path_str])
                w.writerow(row)
    log.info('生成 qor CSV: %s (rows=%d)', path, len(modules) * len(versions))
    return path


def gen_power_csv(project: str, modules: list, versions: list, out_dir: str,
                  rand: random.Random) -> str:
    """生成 power CSV (data_type=power)"""
    path = os.path.join(out_dir, f'{project}_power.csv')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['module_name', 'version', 'power_internal',
                    'power_switching', 'power_leakage', 'power_total'])
        for mod in modules:
            for ver in versions:
                pi = round(rand.uniform(0.1, 8.0), 4)
                ps = round(rand.uniform(0.05, 4.0), 4)
                pl = round(rand.uniform(0.01, 0.8), 4)
                pt = round(pi + ps + pl, 4)
                w.writerow([mod, ver, pi, ps, pl, pt])
    log.info('生成 power CSV: %s (rows=%d)', path, len(modules) * len(versions))
    return path


def gen_violation_csv(project: str, modules: list, versions: list, out_dir: str,
                      rand: random.Random) -> list:
    """生成 violation CSV, 每个 (module, clock, version) 一个文件

    列: module_name, version, STARTPOINT, ENDPOINT, SLACK, ...
    module_name 让 save_violations_to_db 能找到 QorRecord 关联
    """
    paths = []
    for mod in modules:  # 所有模块都生成违例 (保证覆盖全模块)
        clocks = CLOCK_SETS.get(mod, ['SYS_CLK'])
        for c in clocks:
            for ver in versions:  # 所有版本
                fname = f'{project}_{mod}_{c}_v{ver.replace(".", "_")}_violations.csv'
                p = os.path.join(out_dir, fname)
                with open(p, 'w', encoding='utf-8', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(['module_name', 'version', 'STARTPOINT', 'ENDPOINT',
                                'SLACK', 'DEPTH', 'PURE_DEPTH', 'CELL_DELAY', 'NET_DELAY'])
                    n = rand.randint(2, 6)
                    for _ in range(n):
                        slack = round(rand.uniform(-0.3, -0.01), 3)
                        w.writerow([
                            mod, ver,
                            f'{mod}/reg_{rand.randint(0, 50)}/CK',
                            f'{mod}/reg_{rand.randint(51, 200)}/D',
                            slack,
                            rand.randint(5, 30),
                            rand.randint(3, 20),
                            round(rand.uniform(100, 800), 2),
                            round(rand.uniform(20, 200), 2),
                        ])
                paths.append(p)
    log.info('生成 violation CSV: %d 个文件', len(paths))
    return paths


def gen_notes_csv(project: str, modules: list, versions: list, out_dir: str) -> str:
    """生成 notes CSV (data_type=notes) - 3 列: item, description, full_dir

    关联到 QorRecord 通过 (module_name, version, full_dir) 自动匹配
    """
    path = os.path.join(out_dir, f'{project}_notes.csv')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['item', 'description', 'full_dir', 'module_name', 'version'])
        notes_items = [
            ('综合策略', 'compile_ultra'),
            ('目标频率', '500MHz'),
            ('修改内容', '优化关键路径, 插入 buffer 解决 hold 违例'),
            ('PPA 目标', 'area < 10000um2, wns_setup > -0.1ns'),
        ]
        for mod in modules:
            for ver in versions:
                full_dir = f"/demo_runs/{project}/{ver}/{mod}"
                for item, desc in notes_items:
                    w.writerow([item, f"{desc} ({mod}@{ver})", full_dir, mod, ver])
    log.info('生成 notes CSV: %s', path)
    return path


# ---------------------------------------------------------------------------
# 通过内部 import 流程上传 (复用系统的 qor_parser + qor_import)
# ---------------------------------------------------------------------------
def _upload_via_test_client(project_id: int, csv_paths: dict) -> dict:
    """通过 Flask test_client + /api/v1/upload 端点上传

    使用 X-API-Key 认证, 绕过 CSRF + 登录复杂度:
      1) 程序化给 admin 用户创建/获取一个 upload scope API Key
      2) 直接用该 Key 调 /api/v1/upload (API Key 路径免 CSRF)
    """
    from app import app
    from models import ApiKey, User, db

    result = {'qor_saved': 0, 'qor_updated': 0, 'power': 0,
              'violation': 0, 'notes': 0, 'errors': []}

    # 1) 创建 API Key (upload scope) — 明文只生成一次, 需立即使用
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            result['errors'].append('admin 用户不存在')
            return result
        # 每次脚本运行都新建一个, 避免历史 key 失效 / 吊销
        plaintext = ApiKey.generate_key()
        new_key = ApiKey(
            user_id=admin.id,
            key_hash=ApiKey.hash_key(plaintext),
            prefix=plaintext[:12],
            name='demo_csv_upload (auto)',
            scopes='upload,read',
        )
        db.session.add(new_key)
        db.session.commit()
        api_key = plaintext
        log.info('已创建 API Key: %s...%s', plaintext[:8], plaintext[-4:])

    # 2) 用 API Key 上传
    # 重要: project_id 必须在 URL path 或 query 中, before_request hook
    # 才会设置 g.current_project_id, Module.query 才能路由到正确的项目库
    with app.test_client() as client:
        headers = {'X-API-Key': api_key}

        # qor
        for p in csv_paths.get('qor', []):
            with open(p, encoding='utf-8') as fh:
                rdr = csv.DictReader(fh)
                first = next(rdr, None)
            version = (first or {}).get('version', 'v1.0')
            with open(p, 'rb') as fh:
                r = client.post(f'/api/v1/upload?project_id={project_id}', headers=headers,
                                data={
                                    'project_id': str(project_id),
                                    'version': version,
                                    'data_type': 'qor',
                                    'mark_released': '1',
                                    'files': (fh, os.path.basename(p)),
                                },
                                content_type='multipart/form-data')
            body = r.get_json() or {}
            if r.status_code == 200 and body.get('ok'):
                result['qor_saved'] += body.get('saved_count', 0)
                result['qor_updated'] += body.get('updated_count', 0)
                log.info('  qor: saved=%d updated=%d skipped=%d (%s) [body=%s]',
                         body.get('saved_count', 0), body.get('updated_count', 0),
                         body.get('skipped_count', 0), os.path.basename(p),
                         {k: v for k, v in body.items() if k != 'file_results'})
                for fr in body.get('file_results', []):
                    if not fr.get('ok'):
                        log.error('    qor file_result ERROR: %s', fr)
            else:
                result['errors'].append(f'qor 失败 {p}: {r.status_code} {body}')
                log.error('  qor 失败: %s %s', r.status_code, body)

        # power
        for p in csv_paths.get('power', []):
            with open(p, encoding='utf-8') as fh:
                rdr = csv.DictReader(fh)
                first = next(rdr, None)
            version = (first or {}).get('version', 'v1.0')
            with open(p, 'rb') as fh:
                r = client.post(f'/api/v1/upload?project_id={project_id}', headers=headers,
                                data={
                                    'project_id': str(project_id),
                                    'version': version,
                                    'data_type': 'power',
                                    'mark_released': '1',
                                    'files': (fh, os.path.basename(p)),
                                },
                                content_type='multipart/form-data')
            body = r.get_json() or {}
            if r.status_code == 200 and body.get('ok'):
                merged = body.get('merged_count', 0) + body.get('saved_count', 0)
                result['power'] += merged
                log.info('  power: merged+created=%d (%s)',
                         merged, os.path.basename(p))
            else:
                result['errors'].append(f'power 失败 {p}: {r.status_code} {body}')
                log.error('  power 失败: %s %s', r.status_code, body)

        # violation
        for p in csv_paths.get('violation', []):
            # version 从 CSV 第一行提取 (同一文件内所有行 version 相同)
            with open(p, encoding='utf-8') as fh:
                rdr = csv.DictReader(fh)
                first = next(rdr, None)
            version = (first or {}).get('version', 'v1.0')
            with open(p, 'rb') as fh:
                r = client.post(f'/api/v1/upload?project_id={project_id}', headers=headers,
                                data={
                                    'project_id': str(project_id),
                                    'version': version,
                                    'data_type': 'violation',
                                    'mark_released': '1',
                                    'files': (fh, os.path.basename(p)),
                                },
                                content_type='multipart/form-data')
            body = r.get_json() or {}
            if r.status_code == 200 and body.get('ok'):
                result['violation'] += body.get('saved_count', 0)
                log.info('  violation: saved=%d skipped=%d (%s) [body=%s]',
                         body.get('saved_count', 0), body.get('skipped_count', 0),
                         os.path.basename(p),
                         {k: v for k, v in body.items() if k != 'file_results'})
            else:
                result['errors'].append(f'violation 失败 {p}: {r.status_code} {body}')
                log.error('  violation 失败: %s %s', r.status_code, body)

        # notes
        for p in csv_paths.get('notes', []):
            with open(p, encoding='utf-8') as fh:
                rdr = csv.DictReader(fh)
                first = next(rdr, None)
            version = (first or {}).get('version', 'v1.0')
            with open(p, 'rb') as fh:
                r = client.post(f'/api/v1/upload?project_id={project_id}', headers=headers,
                                data={
                                    'project_id': str(project_id),
                                    'version': version,
                                    'data_type': 'notes',
                                    'mark_released': '1',
                                    'files': (fh, os.path.basename(p)),
                                },
                                content_type='multipart/form-data')
            body = r.get_json() or {}
            if r.status_code == 200 and body.get('ok'):
                result['notes'] += body.get('saved_count', 0)
                log.info('  notes: saved=%d (%s)',
                         body.get('saved_count', 0), os.path.basename(p))
            else:
                result['errors'].append(f'notes 失败 {p}: {r.status_code} {body}')
                log.error('  notes 失败: %s %s', r.status_code, body)
    return result


def upload_csvs(project_name: str, db_type: str, csv_paths: dict, out_dir: str):
    """调用 /api/v1/upload 端点上传 (db_type 决定是否真正执行)

    db_type:
      - sqlite   通过 Flask test_client 调用 API, 走完整认证流
      - sql      需要预配置 DATABASE_URL, 否则仅打印计划
      - mongodb  需要预配置 MONGODB_URI, 否则仅打印计划
    """
    if db_type not in ('sqlite',):
        log.warning('[%s] 模式仅打印计划, 不实际执行 (需要预配置 %s 后端)',
                    db_type, db_type.upper())
        for kind, paths in csv_paths.items():
            if not paths:
                continue
            log.info('  [plan] %s: %d 个文件', kind, len(paths))
            for p in paths:
                log.info('    - %s', os.path.basename(p))
        return None

    # sqlite 模式: 通过 test_client 上传
    os.environ['DB_TYPE'] = 'sqlite'
    from app import app, db
    from models import Project, ProjectMember, User

    was_new = False
    with app.app_context():
        # 1) 找 / 创建项目
        proj = Project.query.filter_by(name=project_name).first()
        if proj is None:
            proj = Project(name=project_name, description=f'demo project (db_type={db_type})')
            db.session.add(proj)
            db.session.flush()
            admin = User.query.filter_by(username='admin').first()
            if admin:
                db.session.add(ProjectMember(
                    project_id=proj.id, user_id=admin.id, role='owner',
                ))
            db.session.commit()
            log.info('创建项目: %s (id=%d)', proj.name, proj.id)
            was_new = True
        else:
            log.info('项目已存在: %s (id=%d), 复用', proj.name, proj.id)
        pid = proj.id

    # 2) 通过 test_client 上传 (独立于 app_context)
    result = _upload_via_test_client(pid, csv_paths)
    if result is None:
        return None
    if result.get('errors'):
        log.warning('上传过程有错误:')
        for e in result['errors']:
            log.warning('  - %s', e)
    return {'project_id': pid, 'was_new': was_new, **result}


# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------
def verify_upload(project_name: str, db_type: str, expected: dict) -> bool:
    """验证上传结果, 实际从 DB 读 records / modules / violations / notes 数量"""
    if db_type != 'sqlite':
        log.warning('[%s] 模式不支持自动验证, 跳过', db_type)
        return True

    os.environ['DB_TYPE'] = 'sqlite'
    from app import app
    from models import Project
    from core.db_routing import switch_to_project
    from sqlalchemy import text

    ok = True
    with app.app_context():
        proj = Project.query.filter_by(name=project_name).first()
        if proj is None:
            log.error('验证失败: 项目不存在')
            return False
        with switch_to_project(proj.id):
            from core.db_routing import _build_project_session
            sess = _build_project_session(proj.id)
            try:
                mod_n = sess.execute(text('SELECT COUNT(*) FROM modules')).scalar()
                rec_n = sess.execute(text('SELECT COUNT(*) FROM qor_records')).scalar()
                vio_n = sess.execute(text('SELECT COUNT(*) FROM violation_paths')).scalar()
                notes_n = sess.execute(text('SELECT COUNT(*) FROM run_notes')).scalar()
            finally:
                sess.close()

            log.info('验证: project=%s id=%d', proj.name, proj.id)
            log.info('  modules=%d (期望 %d)', mod_n, expected.get('modules', 0))
            log.info('  qor_records=%d (期望 >= %d)', rec_n, expected.get('qor_records', 0))
            log.info('  violation_paths=%d (期望 >= %d)', vio_n, expected.get('violation', 0))
            log.info('  run_notes=%d (期望 >= %d)', notes_n, expected.get('notes', 0))

            if mod_n < expected.get('modules', 0):
                log.error('  ✗ modules 数量不足')
                ok = False
            if rec_n < expected.get('qor_records', 0):
                log.error('  ✗ qor_records 数量不足')
                ok = False
            if vio_n < expected.get('violation', 0) and expected.get('violation', 0) > 0:
                log.error('  ✗ violation_paths 数量不足')
                ok = False
            if notes_n < expected.get('notes', 0) and expected.get('notes', 0) > 0:
                log.error('  ✗ run_notes 数量不足')
                ok = False
    return ok


# ---------------------------------------------------------------------------
# 清理 DB 文件
# ---------------------------------------------------------------------------
def cleanup_db(project_name: str, db_type: str, project_id: int = None, keep: bool = False) -> list:
    """删除项目 DB 文件 (含 WAL/SHM)

    系统实际使用 qor_p_<project_id>.db 命名, 但同时按 demo 约定
    ${project}_feintqor_${db_type}.db 也尝试清理 (兼容历史误生成的文件).

    返回删除的文件列表
    """
    # 1) 强制关闭所有项目 DB engine 缓存 (避免 Windows 文件锁)
    if project_id is not None:
        try:
            from core.project_db import close_project_engine
            close_project_engine(project_id)
        except Exception as e:
            log.warning('  关闭 project engine 失败: %s', e)
        try:
            from core import db_routing
            sess = db_routing._project_sessions.pop(project_id, None)
            if sess is not None:
                try:
                    sess.remove()
                except Exception:
                    pass
        except Exception as e:
            log.warning('  关闭 _project_sessions 失败: %s', e)
    # 强制 GC 回收
    try:
        import gc
        gc.collect()
    except Exception:
        pass

    deleted = []
    candidates = []
    # 2) 系统实际项目 DB
    if project_id is not None:
        sys_path = actual_project_db_path(project_id)
        candidates.extend([sys_path, sys_path + '-wal', sys_path + '-shm', sys_path + '-journal'])
    # 3) demo 约定命名 (兼容)
    demo_path = project_db_path(project_name, db_type)
    candidates.extend([demo_path, demo_path + '-wal', demo_path + '-shm', demo_path + '-journal'])
    # 去重
    seen = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if os.path.exists(p):
            if keep:
                log.info('  保留: %s', p)
                continue
            try:
                os.remove(p)
                deleted.append(p)
                log.info('  删除: %s', p)
            except Exception as e:
                log.error('  删除失败 %s: %s', p, e)
    return deleted


def cleanup_project_record(project_name: str):
    """从主库 project 表删除项目记录 (sqlite 模式)

    按依赖关系反向删除: ProjectMember → Project
    同时关闭项目 DB engine 缓存, 避免 Windows 文件锁导致删除失败.
    """
    pid = None
    try:
        os.environ['DB_TYPE'] = 'sqlite'
        from app import app
        from models import Project, ProjectMember, User, db
        with app.app_context():
            proj = Project.query.filter_by(name=project_name).first()
            if proj is None:
                log.info('  主库无项目记录: %s', project_name)
                return
            pid = proj.id
            # 1) 删除 project_members (外键依赖)
            ProjectMember.query.filter_by(project_id=pid).delete()
            # 2) 关闭可能缓存的引擎 (Windows 必须, 否则文件占用)
            try:
                from core.project_db import close_project_engine
                close_project_engine(pid)
            except Exception:
                pass
            # 3) 关闭 _project_sessions 缓存 (core.db_routing)
            try:
                from core import db_routing
                db_routing._project_sessions.pop(pid, None)
            except Exception:
                pass
            # 4) 删除项目
            db.session.delete(proj)
            db.session.commit()
            log.info('  主库已删除项目记录: %s (id=%d)', project_name, pid)
    except Exception as e:
        log.warning('  主库清理跳过: %s', e)


# ---------------------------------------------------------------------------
# 批量清理遗留 demo 项目
# ---------------------------------------------------------------------------
def _purge_stale_demo_projects(prefixes=('e2e_', 'demo_', 'test_e2e_')):
    """清理主库中所有指定前缀的项目, 同时删除对应项目 DB 文件.

    用于清理脚本早期测试遗留的脏数据, 避免污染下拉/对比 UI.
    """
    import gc
    os.environ['DB_TYPE'] = 'sqlite'
    from app import app
    from models import Project, ProjectMember, db

    removed = 0
    with app.app_context():
        q = Project.query
        for pre in prefixes:
            q = q.filter(db.or_(Project.name.like(f'{pre}%'),
                                Project.name == pre))
        # UNION 写法
        from sqlalchemy import or_
        cond = or_(*[Project.name.like(f'{p}%') for p in prefixes])
        stale = Project.query.filter(cond).all()
        if not stale:
            log.info('  无遗留 demo 项目 (前缀: %s)', ','.join(prefixes))
            return 0
        for p in stale:
            pid = p.id
            pname = p.name
            try:
                ProjectMember.query.filter_by(project_id=pid).delete()
            except Exception as e:
                log.warning('  delete members %s: %s', pname, e)
            # 关闭引擎
            try:
                from core.project_db import close_project_engine
                close_project_engine(pid)
            except Exception:
                pass
            try:
                from core import db_routing
                db_routing._project_sessions.pop(pid, None)
            except Exception:
                pass
            try:
                db.session.delete(p)
                db.session.commit()
            except Exception as e:
                log.warning('  delete project %s: %s', pname, e)
                continue
            log.info('  移除: %s (id=%d)', pname, pid)
            removed += 1
            # 强制 GC, 释放 Windows 文件锁
            gc.collect()
            # 删除项目 DB 文件 (qor_p_<id>.db + WAL/SHM)
            for ext in ('', '-wal', '-shm', '-journal'):
                fp = os.path.join(SCRIPT_DIR, f'qor_p_{pid}.db' + ext)
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                        log.info('    删除文件: %s', os.path.basename(fp))
                    except Exception as e:
                        log.warning('    文件删除失败 %s: %s', fp, e)
    log.info('[purge-stale] 完成, 共清理 %d 个项目', removed)
    return removed


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='Demo CSV 数据模拟上传脚本 (qor/power/violation/notes)',
    )
    parser.add_argument('--project', default=None,
                        help='项目名 (DB 文件名前缀, 同时作为主库 project.name). '
                             '使用 --purge-stale 时可不填.')
    parser.add_argument('--db-type', choices=VALID_DB_TYPES, default='sqlite',
                        help='数据库类型: sqlite / sql / mongodb (默认 sqlite)')
    parser.add_argument('--modules', type=int, default=5,
                        help='模块数量 (默认 5)')
    parser.add_argument('--versions', type=int, default=4,
                        help='每个模块的版本数 (默认 4)')
    parser.add_argument('--seed', type=int, default=20260729,
                        help='随机种子 (默认 20260729)')
    parser.add_argument('--out-dir', default=None,
                        help='CSV 输出目录 (默认 ./demo_csv_out/<project>)')
    parser.add_argument('--preview', action='store_true',
                        help='仅生成 CSV 不上传')
    parser.add_argument('--cleanup', action='store_true',
                        help='仅清理 DB 文件, 不上传')
    parser.add_argument('--keep-db', action='store_true',
                        help='上传后保留 DB 文件, 不自动清理')
    parser.add_argument('--purge-stale', action='store_true',
                        help='清理主库与项目库中所有 e2e_*/demo_* 前缀的遗留项目 '
                             '(无需 --project)')
    args = parser.parse_args()

    if not args.purge_stale and not args.project:
        parser.error('--project 必填 (除 --purge-stale 模式外)')

    log.info('=' * 60)
    log.info('Demo CSV Upload')
    log.info('  project   = %s', args.project or '(N/A, --purge-stale)')
    log.info('  db_type   = %s', args.db_type)
    log.info('  modules   = %d', args.modules)
    log.info('  versions  = %d', args.versions)
    log.info('  seed      = %d', args.seed)
    log.info('  db_file   = %s',
             project_db_filename(args.project, args.db_type) if args.project else '(N/A)')
    log.info('=' * 60)

    # 批量清理遗留 demo 项目
    if args.purge_stale:
        log.info('[purge-stale] 清理主库与项目库中 e2e_*/demo_* 遗留项目...')
        _purge_stale_demo_projects()
        return 0

    # 仅清理
    if args.cleanup:
        log.info('[清理] 删除 DB 文件...')
        # 查找项目 ID (如存在)
        pid = _find_project_id(args.project)
        cleanup_db(args.project, args.db_type, project_id=pid)
        cleanup_project_record(args.project)
        return 0

    # 选择模块
    n_mod = min(args.modules, len(DEMO_MODULES))
    modules = DEMO_MODULES[:n_mod]
    versions = [f'v{i+1}.0' for i in range(args.versions)]

    # 输出目录
    out_dir = args.out_dir or os.path.join(SCRIPT_DIR, 'demo_csv_out', args.project)
    os.makedirs(out_dir, exist_ok=True)

    # 1) 生成 CSV
    rand = random.Random(args.seed)
    log.info('[1/4] 生成 CSV 数据到 %s', out_dir)
    qor_csv = gen_qor_csv(args.project, modules, versions, out_dir, rand)
    power_csv = gen_power_csv(args.project, modules, versions, out_dir, rand)
    vio_csvs = gen_violation_csv(args.project, modules, versions, out_dir, rand)
    notes_csv = gen_notes_csv(args.project, modules, versions, out_dir)

    csv_paths = {
        'qor': [qor_csv],
        'power': [power_csv],
        'violation': vio_csvs,
        'notes': [notes_csv],
    }

    if args.preview:
        log.info('[预览模式] 仅生成 CSV, 不上传')
        for kind, paths in csv_paths.items():
            log.info('  %s: %d 文件', kind, len(paths))
        return 0

    # 2) 上传 -> 3) 验证 -> 4) 清理
    # 使用 try/finally 确保失败时也 best-effort 清理, 避免遗留 e2e_*/demo_* 项目
    # 污染主库下拉/对比 UI.
    result = None
    exit_code = 0
    try:
        # 2) 上传
        log.info('[2/4] 上传 CSV 到 DB (db_type=%s)...', args.db_type)
        result = upload_csvs(args.project, args.db_type, csv_paths, out_dir)
        if result is None and args.db_type == 'sqlite':
            log.error('上传失败: sqlite 模式必须返回结果')
            exit_code = 2
        else:
            if result:
                log.info('  上传汇总: %s', result)

            # 3) 验证
            log.info('[3/4] 验证上传结果...')
            # gen_violation_csv / gen_notes_csv 现在覆盖所有模块 × 所有版本
            # violation 总数 = sum(len(CLOCK_SETS[mod]) for mod in modules) * 2 ~ 6 paths/file
            n_clocks = sum(len(CLOCK_SETS.get(m, ['SYS_CLK'])) for m in modules)
            expected = {
                'modules': n_mod,
                'qor_records': n_mod * args.versions,
                'violation': n_clocks * args.versions * 2,  # 保守估计: 每文件 >= 2 行
                'notes': n_mod * args.versions * 4,
            }
            ok = verify_upload(args.project, args.db_type, expected)
            if not ok:
                log.error('验证失败!')
                exit_code = 3
    except Exception as e:
        log.exception('主流程异常: %s', e)
        exit_code = 99
    finally:
        # 4) 清理 (除非 --keep-db, 或已经在 --preview/--cleanup 提前返回)
        if args.keep_db:
            log.info('[4/4] --keep-db 已指定, 保留 DB 文件')
            log.info('  DB 路径: %s', project_db_path(args.project, args.db_type))
            if result and result.get('project_id'):
                log.info('  系统实际项目 DB: %s',
                         actual_project_db_path(result['project_id']))
        elif exit_code != 0:
            # 失败时也 best-effort 清理, 避免遗留脏数据
            log.warning('[4/4] 失败时 best-effort 清理...')
            pid = result.get('project_id') if isinstance(result, dict) else None
            was_new = result.get('was_new', True) if isinstance(result, dict) else True
            try:
                if was_new:
                    cleanup_db(args.project, args.db_type, project_id=pid)
                    if args.db_type == 'sqlite':
                        cleanup_project_record(args.project)
                else:
                    log.warning('  目标项目已存在, 仅清理本次上传的临时数据, 保留项目记录')
            except Exception as e:
                log.warning('  失败清理异常: %s', e)
        else:
            log.info('[4/4] 清理 DB 文件...')
            pid = result.get('project_id') if result else None
            was_new = result.get('was_new', True) if isinstance(result, dict) else True
            if was_new:
                # 新建项目 → 完整清理 (DB + 项目记录)
                cleanup_db(args.project, args.db_type, project_id=pid)
                if args.db_type == 'sqlite':
                    cleanup_project_record(args.project)
            else:
                # 已有项目 → 保留项目记录, 但仍清掉 demo 命名的临时文件
                log.info('  目标项目已存在 (%s), 保留项目记录与数据', args.project)
                # 可选: 清掉 demo 约定的临时 ${project}_feintqor_${db_type}.db (实际不存在)
                cleanup_db(args.project, args.db_type, project_id=pid, keep=True)
    if exit_code == 0:
        log.info('完成!')
    return exit_code


def _find_project_id(project_name: str):
    """从主库查找项目 ID (sqlite 模式), 找不到返回 None"""
    try:
        os.environ['DB_TYPE'] = 'sqlite'
        from app import app
        from models import Project
        with app.app_context():
            proj = Project.query.filter_by(name=project_name).first()
            return proj.id if proj else None
    except Exception:
        return None


if __name__ == '__main__':
    sys.exit(main())
