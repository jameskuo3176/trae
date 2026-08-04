"""End-to-end test for DC report upload via POST /api/v1/qor/upload

测试流程:
  1. 调用 dc_report_to_json.py 把 examples/dc_report.v1.json 转 §6.5
  2. 准备用户 / 项目 / API Key
  3. POST /api/v1/qor/upload
  4. 断言: 返回 200, saved=3 (3 个 scenario×path_group 组合)
  5. 幂等性: 第二次上传 saved=0, updated=3
  6. 验证数据库里 record 的关键字段 (wns_setup / tns_setup / nvp_setup / area_total)

也直接测脚本:
  python scripts/dc_report_to_json.py --project-id 1 --version v1.0 \\
      examples/dc_report.v1.json -o /tmp/x.json
"""
import os
import sys
import json
import shutil
import subprocess
import secrets
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DB_TYPE', 'sqlite')
os.environ.setdefault('FLASK_DEBUG', '0')

from app import app
from models import db, Project, ProjectMember, User, ApiKey, QorRecord, Module
from core.db_routing import switch_to_project
from core.project_db import close_project_engine, project_db_path

with app.app_context():
    test_username = 'dcreport_test'
    test_proj = 'dc_report_test_project'
    test_version = 'v1.0'

    # ---------- 0) 干净启动 ----------
    import glob
    for old_db in glob.glob('qor_p_*.db*'):
        try:
            os.remove(old_db)
        except Exception:
            pass
    try:
        from core.project_db import _engines, _sessions
        for pid in list(_engines.keys()):
            try: _engines[pid].dispose()
            except: pass
            _engines.pop(pid, None)
        for pid in list(_sessions.keys()):
            try: _sessions[pid].remove()
            except: pass
            _sessions.pop(pid, None)
    except Exception:
        pass

    ApiKey.query.filter_by(name='dc-report-test').delete()
    ApiKey.query.filter(ApiKey.user_id.in_(
        db.session.query(User.id).filter(User.username == test_username)
    )).delete(synchronize_session=False)
    for p in Project.query.filter_by(name=test_proj).all():
        ProjectMember.query.filter_by(project_id=p.id).delete()
        db.session.delete(p)
    User.query.filter_by(username=test_username).delete()
    db.session.commit()

    # ---------- 1) 创建测试用户 / 项目 / API Key ----------
    user = User(username=test_username, role='owner', display_name='DC Report Tester')
    user.set_password('test_pw_2026')
    user.must_change_password = False
    db.session.add(user)
    db.session.flush()

    project = Project(name=test_proj, description='DC report upload e2e', status='active')
    db.session.add(project)
    db.session.flush()

    db.session.add(ProjectMember(project_id=project.id, user_id=user.id, role='owner'))
    db.session.commit()

    plaintext = 'qor_' + secrets.token_urlsafe(24)
    api_key = ApiKey(user_id=user.id, name='dc-report-test',
                     key_hash=ApiKey.hash_key(plaintext), prefix=plaintext[:12],
                     scopes='upload', revoked=False)
    db.session.add(api_key)
    db.session.commit()

    print(f'[SETUP] user={user.id} project={project.id} api_key={plaintext[:12]}...')

    # ---------- 2) 调用 dc_report_to_json.py 把 DC 报告转 §6.5 ----------
    here = os.path.dirname(os.path.abspath(__file__))
    dc_path = os.path.join(here, 'examples', 'dc_report.v1.json')
    assert os.path.exists(dc_path), f'缺少示例文件: {dc_path}'

    converted_path = os.path.join(here, 'converted_dc.json')
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(here, 'scripts', 'dc_report_to_json.py'),
             '--project-id', str(project.id), '--version', test_version,
             '-o', converted_path, dc_path],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, f'converter 退出码 {r.returncode}\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}'
        print(f'[CONVERT] OK -> {converted_path}')
    finally:
        pass

    with open(converted_path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    assert payload['schema_version'] == '1.0'
    assert payload['upload']['project_id'] == project.id
    assert payload['upload']['version'] == test_version
    # 1 DC report = 1 run = 1 record (无论内部多少 scenarios × path_groups)
    assert len(payload['records']) == 1, f'期望 1 条 record (1 run), 实际 {len(payload["records"])}'
    rec0 = payload['records'][0]
    # full_dir = run.directory, 不带 scenario#path_group 后缀
    assert rec0['full_dir'] == 'modulea_t_cfg1_rundir', f'full_dir 错: {rec0["full_dir"]}'
    # 聚合 worst-case:
    # WNS: min(-10, -25, -50) = -50
    # TNS: min(0, -120, -800) = -800
    # NVP: sum(0, 14, 50) = 64
    assert rec0['timing']['setup']['wns'] == -50.0
    assert rec0['timing']['setup']['tns'] == -800.0
    assert rec0['timing']['setup']['nvp'] == 64
    # clocks: 第一个 scenario (tt0p6v_tt) 的 path_groups
    assert 'FUNCCLK' in rec0['clocks']
    assert 'SRAMCLK' in rec0['clocks']
    assert rec0['clocks']['FUNCCLK']['period'] == 1000.0
    assert rec0['clocks']['SRAMCLK']['period'] == 800.0
    # extra.scenarios: 全量 2 scenarios × 3 path_groups
    sc = rec0['extra']['scenarios']
    assert set(sc.keys()) == {'tt0p6v_tt', 'ss0p81v_ss'}
    assert set(sc['tt0p6v_tt'].keys()) == {'FUNCCLK', 'SRAMCLK'}
    assert set(sc['ss0p81v_ss'].keys()) == {'FUNCCLK'}
    assert sc['tt0p6v_tt']['FUNCCLK']['wns'] == -10.0
    assert sc['tt0p6v_tt']['SRAMCLK']['wns'] == -25.0
    assert sc['ss0p81v_ss']['FUNCCLK']['wns'] == -50.0
    print(f'[CONVERT] records=1, wns={rec0["timing"]["setup"]["wns"]}, '
          f'scenarios={list(sc.keys())}')

    # ---------- 3) 第一次 POST ----------
    client = app.test_client()
    resp = client.post(
        '/api/v1/qor/upload',
        json=payload,
        headers={'X-API-Key': plaintext},
    )
    assert resp.status_code == 200, f'上传失败 HTTP {resp.status_code}\n{resp.get_json()}'
    body = resp.get_json()
    assert body['ok'] is True
    assert body['saved'] == 1, f'期望 saved=1 (1 run), 实际 {body}'
    assert len(body['record_ids']) == 1
    record_ids_first = body['record_ids']
    print(f'[UPLOAD #1] saved=1, record_ids={record_ids_first}')

    # ---------- 4) 数据库内容验证 ----------
    with switch_to_project(project.id):
        records = QorRecord.query.all()
        assert len(records) == 1, f'数据库期望 1 条 (1 run), 实际 {len(records)}'

        def _get_extra(rec):
            ef = rec.extra_fields
            if isinstance(ef, str):
                import json as _json
                return _json.loads(ef) if ef else {}
            return ef or {}

        r0 = records[0]
        # full_dir = run.directory (不带后缀)
        assert r0.full_dir == 'modulea_t_cfg1_rundir', f'full_dir 错: {r0.full_dir}'
        # 聚合 worst-case
        assert abs(r0.wns_setup - (-50.0)) < 0.01, f'wns_setup 错: {r0.wns_setup}'
        assert abs(r0.tns_setup - (-800.0)) < 0.01
        assert r0.nvp_setup == 64
        # area/cells/ratios 等 per-run 字段
        assert abs(r0.area_total - 23455.0) < 0.01
        assert abs(r0.clock_gating_ratio - 0.9778) < 0.001
        assert r0.cell_count == 404455454
        # extra_fields: 全量审计
        extra = _get_extra(r0)
        assert 'timing_final' in extra
        assert 'blocks' in extra
        assert 'misc_fgcg' in extra
        assert extra['default_scenario'] == 'tt0p6v_tt'
        # extra.scenarios: 全量 scenarios × path_groups
        assert 'scenarios' in extra
        assert set(extra['scenarios'].keys()) == {'tt0p6v_tt', 'ss0p81v_ss'}
        # aggregate_* 用于 dashboard 快速展示
        assert extra['aggregate_wns_min'] == -50.0
        assert extra['aggregate_tns_min'] == -800.0
        assert extra['aggregate_nvp_sum'] == 64
        assert extra['scenario_count'] == 2
        assert extra['path_group_count'] == 3
        # dc_full_dir 保留原始 run.directory
        assert extra['dc_full_dir'] == 'modulea_t_cfg1_rundir'
        # clocks 字段: 第 1 个 scenario 的 path_groups
        # (注: §6.5 扁平 clocks 字段在 record 顶层, 不在 extra_fields)
        print(f'[DB CHECK] record #{r0.id} full_dir={r0.full_dir}, wns={r0.wns_setup}, '
              f'tns={r0.tns_setup}, nvp={r0.nvp_setup}, scenarios={list(extra["scenarios"].keys())}')

    # ---------- 5) 幂等性: 第二次 POST 应该是 updated=1 ----------
    resp = client.post(
        '/api/v1/qor/upload',
        json=payload,
        headers={'X-API-Key': plaintext},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['saved'] == 0, f'幂等性检查: 期望 saved=0, 实际 {body}'
    assert body['updated'] == 1, f'幂等性检查: 期望 updated=1, 实际 {body}'
    print(f'[UPLOAD #2] saved=0, updated=1 (幂等)')

    # ---------- 6) 验证 mark_released 流程 ----------
    payload2 = dict(payload)
    payload2['upload'] = dict(payload['upload'])
    payload2['upload']['mark_released'] = True
    resp = client.post(
        '/api/v1/qor/upload',
        json=payload2,
        headers={'X-API-Key': plaintext},
    )
    assert resp.status_code == 200, f'mark_released 失败: {resp.get_json()}'
    body = resp.get_json()
    assert body['updated'] == 1
    # 数据库验证 is_released
    with switch_to_project(project.id):
        for r in QorRecord.query.all():
            assert r.is_released is True, f'record {r.id} 未标记 is_released'
    print(f'[UPLOAD #3] mark_released=True -> 1 条记录已发布')

    # ---------- 7) 错误路径: 无效 API Key ----------
    resp = client.post('/api/v1/qor/upload', json=payload,
                       headers={'X-API-Key': 'qor_invalid_xxxxxxxx'})
    assert resp.status_code in (401, 429), f'无效 API Key 应返回 401/429, 实际 {resp.status_code}'
    print(f'[ERROR PATH] 无效 API Key -> HTTP {resp.status_code}')

    # ---------- 8) 清理 ----------
    try:
        os.remove(converted_path)
    except Exception:
        pass
    # 关掉项目引擎 + 删除项目 DB 文件, 避免下次跑测试时 id 撞车
    try:
        with switch_to_project(project.id):
            QorRecord.query.delete()
            Module.query.filter_by(project_id=project.id).delete()
        db.session.commit()
    except Exception:
        pass
    try:
        close_project_engine(project.id)
    except Exception:
        pass
    try:
        db_path = project_db_path(project.id)
        for ext in ('', '-wal', '-shm'):
            p = db_path + ext
            if os.path.exists(p):
                os.remove(p)
    except Exception:
        pass
    ApiKey.query.filter_by(name='dc-report-test').delete()
    ApiKey.query.filter_by(user_id=user.id).delete()
    for p in Project.query.filter_by(name=test_proj).all():
        ProjectMember.query.filter_by(project_id=p.id).delete()
        db.session.delete(p)
    ProjectMember.query.filter_by(user_id=user.id).delete()
    User.query.filter_by(username=test_username).delete()
    db.session.commit()
    print('\n[PASS] DC 报告 e2e 测试全部通过')
