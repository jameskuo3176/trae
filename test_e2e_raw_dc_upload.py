"""端到端测试: 原始 DC 报告 JSON 直接 POST /api/v1/qor/upload.

测试覆盖:
  1. 直接 POST 原始 DC 报告 (不带 upload 包装, project/version 走 query 参数)
  2. 1 DC 报告 = 1 QorRecord
  3. register_count = misc.fgcg.total_flops
  4. raw_dc_report 字段被正确存储
  5. Module 按 top_module 自动创建
  6. 幂等性: 重复 POST 应 updated=1
  7. CLI 转换路径 (CLI 仍可独立转换)
"""
import json
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app import create_app
from models import db, User, Project, ProjectMember, ApiKey, QorRecord, Module
from core.db_routing import switch_to_project


def banner(msg, char='='):
    print()
    print(char * 78)
    print('  ' + msg)
    print(char * 78)


def main():
    DC_REPORT = os.path.join(HERE, 'examples', 'dc_report.v1.json')
    TEST_USER = 'raw_dc_test_user'
    TEST_PROJ = 'raw_dc_test_project'
    TEST_VERSION = 'v1.0'

    # ----- 1. 干净启动 -----
    app = create_app()
    with app.app_context():
        # 清理历史数据
        existing_proj = Project.query.filter_by(name=TEST_PROJ).first()
        if existing_proj:
            # 同时清理 project DB 里的 records/modules
            try:
                with switch_to_project(existing_proj.id):
                    QorRecord.query.delete()
                    Module.query.filter_by(project_id=existing_proj.id).delete()
                    db.session.commit()
            except Exception as e:
                print(f'  [CLEAN-WARN] project DB cleanup: {e}')
            ProjectMember.query.filter_by(project_id=existing_proj.id).delete()
            db.session.flush()
            db.session.delete(existing_proj)
            db.session.commit()
        existing_user = User.query.filter_by(username=TEST_USER).first()
        if existing_user:
            ApiKey.query.filter_by(user_id=existing_user.id).delete()
            ProjectMember.query.filter_by(user_id=existing_user.id).delete()
            db.session.flush()
            db.session.delete(existing_user)
            db.session.commit()

        # 2. 创建测试用户 / 项目 / API Key
        user = User(username=TEST_USER, role='owner', display_name='Raw DC Tester')
        user.set_password('test_pw_2026')
        user.must_change_password = False
        db.session.add(user)
        db.session.flush()

        project = Project(name=TEST_PROJ, description='Raw DC upload e2e', status='active')
        db.session.add(project)
        db.session.flush()

        db.session.add(ProjectMember(project_id=project.id, user_id=user.id, role='owner'))
        db.session.commit()

        plaintext = 'qor_' + secrets.token_urlsafe(24)
        api_key = ApiKey(user_id=user.id, name='raw-dc-test',
                         key_hash=ApiKey.hash_key(plaintext), prefix=plaintext[:12],
                         scopes='upload', revoked=False)
        db.session.add(api_key)
        db.session.commit()

        project_id = project.id
        user_id = user.id
        api_plain = plaintext

    print(f'[SETUP] project_id={project_id}, user_id={user_id}')

    # ----- 3. 加载 DC 报告 (原始格式) -----
    with open(DC_REPORT, 'r', encoding='utf-8') as f:
        dc = json.load(f)
    assert 'top_module' in dc
    assert 'timing' in dc and 'area' in dc and 'misc' in dc
    assert 'upload' not in dc or not dc.get('upload'), 'DC 报告不应含 upload 包装'
    assert 'records' not in dc, 'DC 报告不应含 records 数组'
    print(f'[DC] top_module={dc["top_module"]}, run.directory={dc["run"]["directory"]}')

    # ----- 4. POST 原始 DC 报告 -----
    banner('Step 1: POST 原始 DC 报告 JSON (?project_id=&version=)')
    client = app.test_client()
    resp = client.post(
        f'/api/v1/qor/upload?project_id={project_id}&version={TEST_VERSION}',
        json=dc,
        headers={'X-API-Key': api_plain},
    )
    assert resp.status_code == 200, f'上传失败 HTTP {resp.status_code}\n{resp.get_json()}'
    body = resp.get_json()
    print(f'  [HTTP] {resp.status_code}')
    print(f'  [RESP] {json.dumps(body, ensure_ascii=False)[:500]}')
    assert body['ok'] is True
    assert body['format'] == 'dc_report'
    assert body['module_name'] == 'modulea_t'
    assert body['saved'] == 1, f'期望 saved=1, 实际 {body}'
    assert len(body['record_ids']) == 1
    record_id = body['record_ids'][0]
    print(f'  [OK] saved=1, record_id={record_id}')

    # ----- 5. 数据库校验 -----
    banner('Step 2: 数据库内容校验')
    with app.app_context(), switch_to_project(project_id):
        # Module 按 top_module 自动创建
        mod = Module.query.filter_by(project_id=project_id, name='modulea_t').first()
        assert mod is not None, 'Module 应该已自动创建'
        print(f'  [MODULE] auto-created id={mod.id}, name={mod.name}')

        records = QorRecord.query.all()
        assert len(records) == 1, f'期望 1 条 record (1 run), 实际 {len(records)}'

        r = records[0]
        # 1. QorRecord 主键
        assert r.full_dir == 'modulea_t_cfg1_rundir', f'full_dir 错: {r.full_dir}'
        # 2. 聚合字段 (worst-case)
        assert abs(r.wns_setup - (-50.0)) < 0.01, f'wns_setup={r.wns_setup}'
        assert abs(r.tns_setup - (-800.0)) < 0.01
        assert r.nvp_setup == 64
        # 3. register_count = total_flops (1,218,349)
        assert r.register_count == 1218349, f'register_count 错: {r.register_count}'
        # 4. raw_dc_report 字段 (完整原文)
        assert r.raw_dc_report is not None, 'raw_dc_report 应被存储'
        raw = json.loads(r.raw_dc_report)
        assert raw['top_module'] == 'modulea_t'
        assert raw['run']['directory'] == 'modulea_t_cfg1_rundir'
        assert 'timing' in raw and 'area' in raw and 'misc' in raw
        # 5. area / cells / ratios
        assert abs(r.area_total - 23455.0) < 0.01
        assert r.cell_count == 404455454
        assert abs(r.clock_gating_ratio - 0.9778) < 0.001

        print(f'  [PASS] full_dir={r.full_dir}')
        print(f'  [PASS] wns_setup={r.wns_setup} tns_setup={r.tns_setup} nvp_setup={r.nvp_setup}')
        print(f'  [PASS] register_count={r.register_count} (from misc.fgcg.total_flops)')
        print(f'  [PASS] raw_dc_report 长度={len(r.raw_dc_report)} chars, 含 top_module={raw["top_module"]}')

    # ----- 6. 幂等性: 再次 POST -----
    banner('Step 3: 幂等性 (再次 POST 应为 updated=1, saved=0)')
    resp = client.post(
        f'/api/v1/qor/upload?project_id={project_id}&version={TEST_VERSION}',
        json=dc,
        headers={'X-API-Key': api_plain},
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body['saved'] == 0
    assert body['updated'] == 1
    print(f'  [PASS] saved=0, updated=1 (幂等)')

    # ----- 7. CLI 转换路径 (库函数调用) -----
    banner('Step 4: 库函数 convert_dc_to_qor_record 直接调用')
    sys.path.insert(0, os.path.join(HERE, 'scripts'))
    from dc_report_to_json import convert_dc_to_qor_record, validate_dc_report
    validate_dc_report(dc)
    payload = convert_dc_to_qor_record(dc, project_id=99, version='cli_v2', mark_released=True)
    assert payload['schema_version'] == '1.0'
    assert payload['upload']['project_id'] == 99
    assert payload['upload']['version'] == 'cli_v2'
    assert payload['upload']['mark_released'] is True
    assert len(payload['records']) == 1
    rec = payload['records'][0]
    assert rec['module_name'] == 'modulea_t'
    assert rec['full_dir'] == 'modulea_t_cfg1_rundir'
    assert rec['register_count'] == 1218349
    assert rec['timing']['setup']['wns'] == -50.0
    assert 'FUNCCLK' in rec['clocks']  # 第一个 scenario 的 path_groups
    assert 'SRAMCLK' in rec['clocks']
    print(f'  [PASS] records=1, wns={rec["timing"]["setup"]["wns"]}, '
          f'clocks={list(rec["clocks"].keys())}, register_count={rec["register_count"]}')

    # ----- 8. 错误: 缺 project_id -----
    banner('Step 5: 错误处理 (缺 project_id)')
    resp = client.post(
        f'/api/v1/qor/upload?version={TEST_VERSION}',
        json=dc,
        headers={'X-API-Key': api_plain},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert 'project_id' in body.get('error', '')
    print(f'  [PASS] HTTP 400, error={body["error"]}')

    # ----- 9. 错误: 缺 version -----
    resp = client.post(
        f'/api/v1/qor/upload?project_id={project_id}',
        json=dc,
        headers={'X-API-Key': api_plain},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert 'version' in body.get('error', '')
    print(f'  [PASS] HTTP 400, error={body["error"]}')

    # ----- 10. 错误: 缺 top_module -----
    bad_dc = dict(dc)
    bad_dc['top_module'] = ''
    resp = client.post(
        f'/api/v1/qor/upload?project_id={project_id}&version={TEST_VERSION}',
        json=bad_dc,
        headers={'X-API-Key': api_plain},
    )
    assert resp.status_code == 400
    print(f'  [PASS] HTTP 400, top_module 空 -> 拒绝')

    # ----- 总结 -----
    banner('全部测试通过', char='#')
    print()
    print('  ✓ 原始 DC 报告 JSON 直接 POST (query 参数传 project_id/version)')
    print('  ✓ 1 DC = 1 QorRecord, full_dir = run.directory')
    print('  ✓ register_count = misc.fgcg.total_flops = 1,218,349')
    print('  ✓ raw_dc_report 字段存储完整原始 JSON')
    print('  ✓ Module 按 top_module 自动创建')
    print('  ✓ 聚合字段: wns=-50 tns=-800 nvp=64 (worst-case)')
    print('  ✓ 幂等性 (重复 POST: saved=0, updated=1)')
    print('  ✓ 库函数 convert_dc_to_qor_record 可独立调用')
    print('  ✓ 错误处理: 缺 project_id / version / top_module 全部 400')
    print()


if __name__ == '__main__':
    main()
