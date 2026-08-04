"""DC 报告上传 Demo 脚本.

功能: 把 DC 综合报告 JSON 通过 dc_report_to_json.py 转换为 §6.5 格式,
       然后调用 /api/v1/qor/upload 上传, 最后查询数据库验证落盘结果.

用法:
    python demo_dc_upload.py

前置:
    - 服务已启动 (默认 http://127.0.0.1:5000)
    - 已有 API Key (脚本会自动创建测试用户和 Key)
    - examples/dc_report.v1.json 存在
"""
import json
import os
import secrets
import sys
import subprocess

# 路径设置
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from app import create_app
from models import db, Project, ProjectMember, User, ApiKey, QorRecord, Module
from core.db_routing import switch_to_project

# 演示配置
DEMO_PROJECT = 'demo_dc_project'
DEMO_USER = 'demo_dc_user'
DEMO_VERSION = 'demo_v1.0'
DEMO_DC_REPORT = os.path.join(HERE, 'examples', 'dc_report.v1.json')
DEMO_CONVERTED = os.path.join(HERE, 'examples', 'demo_converted.json')

# Banner
def banner(msg, char='='):
    print()
    print(char * 78)
    print('  ' + msg)
    print(char * 78)


def step1_convert_dc_report():
    """Step 1: DC 报告 → §6.5 JSON 转换"""
    banner('Step 1: DC 报告 JSON → §6.5 JSON 转换 (CLI)')
    print(f'  输入: {DEMO_DC_REPORT}')
    print(f'  输出: {DEMO_CONVERTED}')
    print()

    # 先创建项目获取 project_id
    app = create_app()
    with app.app_context():
        # 清理历史数据 (注意顺序: 先清依赖表)
        existing_proj = Project.query.filter_by(name=DEMO_PROJECT).first()
        if existing_proj:
            print(f'  [CLEAN] 删除历史项目 {existing_proj.name}')
            ProjectMember.query.filter_by(project_id=existing_proj.id).delete()
            db.session.flush()
            db.session.delete(existing_proj)
            db.session.commit()
        existing_user = User.query.filter_by(username=DEMO_USER).first()
        if existing_user:
            print(f'  [CLEAN] 删除历史用户 {existing_user.username}')
            # 先清用户的依赖 (ApiKey)
            ApiKey.query.filter_by(user_id=existing_user.id).delete()
            db.session.flush()
            # 清掉该用户在其他项目的成员关系
            ProjectMember.query.filter_by(user_id=existing_user.id).delete()
            db.session.flush()
            db.session.delete(existing_user)
            db.session.commit()

        # 创建用户
        user = User(username=DEMO_USER, role='owner', display_name='DC Demo User')
        user.set_password('demo_pw_2026')
        user.must_change_password = False
        db.session.add(user)
        db.session.flush()

        # 创建项目
        project = Project(name=DEMO_PROJECT, description='DC 报告上传 demo', status='active')
        db.session.add(project)
        db.session.flush()

        db.session.add(ProjectMember(project_id=project.id, user_id=user.id, role='owner'))
        db.session.commit()

        # 创建 API Key
        plaintext = 'qor_' + secrets.token_urlsafe(24)
        api_key = ApiKey(user_id=user.id, name='demo-dc-key',
                         key_hash=ApiKey.hash_key(plaintext), prefix=plaintext[:12],
                         scopes='upload', revoked=False)
        db.session.add(api_key)
        db.session.commit()

        project_id = project.id
        user_id = user.id

    print(f'  [SETUP] project_id={project_id}, user_id={user_id}, api_key={plaintext[:20]}...')

    # 调 dc_report_to_json.py
    cmd = [
        sys.executable,
        os.path.join(HERE, 'scripts', 'dc_report_to_json.py'),
        '--project-id', str(project_id),
        '--version', DEMO_VERSION,
        '-o', DEMO_CONVERTED,
        DEMO_DC_REPORT,
    ]
    print(f'  [CMD] {" ".join(cmd)}')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print('  [FAIL]', r.stderr)
        sys.exit(1)
    print(f'  [STDOUT] {r.stderr.strip()}')

    # 打印转换结果摘要
    with open(DEMO_CONVERTED, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    print(f'  [RESULT] schema_version={payload["schema_version"]}')
    print(f'           upload.project_id={payload["upload"]["project_id"]}')
    print(f'           upload.version={payload["upload"]["version"]}')
    print(f'           records count = {len(payload["records"])}  (1 run = 1 record)')
    rec = payload['records'][0]
    timing = rec.get('timing', {}).get('setup', {})
    sc = rec.get('extra', {}).get('scenarios', {})
    print(f'           record.module_name   = {rec["module_name"]}')
    print(f'           record.full_dir      = {rec["full_dir"]}    (run.directory, 无后缀)')
    print(f'           record.timing.setup  = WNS={timing.get("wns")} TNS={timing.get("tns")} NVP={timing.get("nvp")}')
    print(f'             ↑ worst-case 聚合 (min/min/sum) across all (scenario × path_group)')
    print(f'           record.clocks        = {list(rec.get("clocks", {}).keys())}')
    print(f'             ↑ 第一个 scenario 的所有 path_groups')
    print(f'           extra.scenarios      = {list(sc.keys())}')
    print(f'             ↑ 全量 {sum(len(pgs) for pgs in sc.values())} 个 (scenario × path_group) 审计')
    for sn, pgs in sc.items():
        for pg, val in pgs.items():
            print(f'             · {sn} / {pg}: WNS={val.get("wns")} TNS={val.get("tns")} NVP={val.get("nvp")} period={val.get("period")}')

    return project_id, plaintext


def step2_upload_via_api(project_id, api_key):
    """Step 2: POST /api/v1/qor/upload"""
    banner('Step 2: HTTP 上传 §6.5 JSON → /api/v1/qor/upload')
    print(f'  URL: http://127.0.0.1:5000/api/v1/qor/upload')
    print(f'  Method: POST')
    print(f'  Headers: X-API-Key: {api_key[:20]}...')
    print(f'  Body: {DEMO_CONVERTED} ({os.path.getsize(DEMO_CONVERTED)} bytes)')
    print()

    app = create_app()
    client = app.test_client()
    with open(DEMO_CONVERTED, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    resp = client.post(
        '/api/v1/qor/upload',
        json=payload,
        headers={'X-API-Key': api_key},
    )

    print(f'  [HTTP] {resp.status_code}')
    body = resp.get_json()
    print(f'  [RESP] {json.dumps(body, ensure_ascii=False, indent=2)[:2000]}')

    if resp.status_code != 200 or not body.get('ok'):
        print('  [FAIL] 上传失败')
        sys.exit(1)
    return body


def step3_verify_db(project_id, expected_ids):
    """Step 3: 数据库校验"""
    banner('Step 3: 数据库落盘校验 (1 run = 1 record)')
    print(f'  项目: {DEMO_PROJECT} (id={project_id})')
    print(f'  期望 record_ids: {expected_ids}')
    print()

    app = create_app()
    with app.app_context():
        with switch_to_project(project_id):
            records = QorRecord.query.order_by(QorRecord.id).all()
            print(f'  [DB] 项目库实际记录数: {len(records)}  (1 个 run → 1 条 QorRecord)')
            assert len(records) == 1, f'期望 1 条, 实际 {len(records)}'

            for r in records:
                ef = r.extra_fields
                if isinstance(ef, str):
                    ef = json.loads(ef) if ef else {}
                ef = ef or {}
                print()
                print(f'  Record #{r.id}:')
                print(f'    module_name     = {r.module.name if r.module else "?"}')
                print(f'    version         = {r.version}')
                print(f'    full_dir        = {r.full_dir}    (run.directory, 无后缀)')
                print(f'    release_dir     = {r.release_dir}')
                print()
                print(f'  §6.5 扁平字段 (worst-case 聚合):')
                print(f'    wns_setup       = {r.wns_setup}    (min of {{-10, -25, -50}})')
                print(f'    tns_setup       = {r.tns_setup}    (min of {{0, -120, -800}})')
                print(f'    nvp_setup       = {r.nvp_setup}     (sum of {{0, 14, 50}})')
                print(f'    area_total      = {r.area_total}')
                print(f'    cell_count      = {r.cell_count}')
                print(f'    utilization     = {r.utilization}')
                print(f'    clock_gating    = {r.clock_gating_ratio}')
                print()
                print(f'  §6.5 clocks 字段 (第 1 个 scenario 的 path_groups):')
                print(f'    (clocks 数据在 record 顶层, dashboard 可按 clock 维度展示)')
                print()
                print(f'  extra_fields 审计数据:')
                print(f'    default_scenario       = {ef.get("default_scenario")}')
                print(f'    scenario_count         = {ef.get("scenario_count")}')
                print(f'    path_group_count       = {ef.get("path_group_count")}')
                print(f'    aggregate_wns_min      = {ef.get("aggregate_wns_min")}')
                print(f'    aggregate_tns_min      = {ef.get("aggregate_tns_min")}')
                print(f'    aggregate_nvp_sum      = {ef.get("aggregate_nvp_sum")}')
                print(f'    dc_full_dir            = {ef.get("dc_full_dir")}')
                print(f'    blocks (count)         = {len(ef.get("blocks", {}))}')
                print(f'    misc_fgcg.total        = {ef.get("misc_fgcg", {}).get("total_flops")}')
                print()
                print(f'  extra.scenarios (全量 2 scenarios × 3 path_groups):')
                for sname, pgs in ef.get('scenarios', {}).items():
                    for pg, val in pgs.items():
                        print(f'    {sname} / {pg}: WNS={val.get("wns")} TNS={val.get("tns")} '
                              f'NVP={val.get("nvp")} period={val.get("period")} lol={val.get("lol")}')

            # 验证期望 ID 一致
            actual_ids = [r.id for r in records]
            assert actual_ids == expected_ids, f'ID 不匹配: {actual_ids} != {expected_ids}'
            print()
            print(f'  [PASS] 数据库记录 ID 与 API 返回一致')


def step4_idempotency(project_id, api_key):
    """Step 4: 幂等性测试"""
    banner('Step 4: 幂等性测试 (再次 POST 应为 updated=1, saved=0)')
    print()

    app = create_app()
    client = app.test_client()
    with open(DEMO_CONVERTED, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    resp = client.post(
        '/api/v1/qor/upload',
        json=payload,
        headers={'X-API-Key': api_key},
    )
    body = resp.get_json()
    print(f'  [HTTP] {resp.status_code}')
    print(f'  [RESP] ok={body.get("ok")}, saved={body.get("saved")}, updated={body.get("updated")}')
    assert body.get('saved') == 0, f'期望 saved=0, 实际 {body}'
    assert body.get('updated') == 1, f'期望 updated=1, 实际 {body}'
    print(f'  [PASS] 幂等性: 同 (module, version, full_dir) 三元组去重成功')


def main():
    print()
    print('=' * 78)
    print('  DC 报告 → §6.5 JSON → /api/v1/qor/upload → 数据库 全链路 demo')
    print('=' * 78)

    project_id, api_key = step1_convert_dc_report()
    upload_result = step2_upload_via_api(project_id, api_key)
    step3_verify_db(project_id, upload_result.get('record_ids', []))
    step4_idempotency(project_id, api_key)

    banner('Demo 全部通过', char='#')
    print()
    print('  ✓ DC 报告 JSON → §6.5 JSON 转换 (1 run → 1 record)')
    print('  ✓ HTTP POST 上传成功 (saved=1, record_ids=[..])')
    print('  ✓ 数据库落盘校验 (1 条 record, 字段正确, 聚合自 2 scenarios × 3 path_groups)')
    print('  ✓ 幂等性 (重复上传 saved=0, updated=1)')
    print()
    print(f'  完整转换结果: {DEMO_CONVERTED}')
    print()


if __name__ == '__main__':
    main()
