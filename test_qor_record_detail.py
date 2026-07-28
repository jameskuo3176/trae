"""测试新增的 full_dir 列 / 记录详情 / 跳转 API

验证:
  1. QorRecord 有 full_dir 列, 旧数据回填成功
  2. /api/qor/record/<id> 返回详情 + 同 module+version 横向对比
  3. /qor_record/<id> 页面路由返回 200
  4. /dashboard?focus_record_id=<id> 页面路由接受参数
  5. /dashboard 预选 project_id/module_id/version/full_dir
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Project, Module, QorRecord
import json


def test_qor_record_detail():
    with app.app_context():
        client = app.test_client()
        admin = User.query.filter_by(role='admin').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True

        # 找一条 demo 数据
        rec = QorRecord.query.filter(QorRecord.full_dir.isnot(None)).first()
        assert rec, '没有 full_dir 数据, 请先跑 seed_demo_data.py'
        assert rec.full_dir, f'full_dir 为空: {rec.id}'

        # 1. 详情 API
        r = client.get(f'/api/qor/record/{rec.id}')
        assert r.status_code == 200, f'got {r.status_code}'
        d = r.get_json()
        assert d['record']['id'] == rec.id
        assert d['record']['full_dir'] == rec.full_dir
        # 同 module+version 横向对比
        assert 'siblings' in d
        assert isinstance(d['siblings'], list)
        assert d['sibling_count'] == len(d['siblings'])
        # 当前记录在 siblings 中
        assert any(s['id'] == rec.id for s in d['siblings'])
        # siblings 包含关键指标
        if d['siblings']:
            s0 = d['siblings'][0]
            for k in ('id', 'full_dir', 'area_total', 'wns_setup', 'cell_count'):
                assert k in s0, f'siblings 缺少 {k}'
        print(f'  ✓ 详情 API: rec#{rec.id} full_dir={rec.full_dir} siblings={d["sibling_count"]}')

        # 2. 页面路由
        r = client.get(f'/qor_record/{rec.id}')
        assert r.status_code == 200
        assert b'QoR \xe8\xae\xb0\xe5\xbd\x95\xe8\xaf\xa6\xe6\x83\x85' in r.data  # UTF-8 "QoR 记录详情"
        assert b'pathFullDir' in r.data
        assert b'siblingsBody' in r.data
        print('  ✓ 详情页面 /qor_record/<id> 200')

        # 3. 不存在的记录 404
        r = client.get('/api/qor/record/999999')
        assert r.status_code == 404
        print('  ✓ 不存在记录 404')

        # 4. dashboard focus_record_id
        r = client.get(f'/dashboard?focus_record_id={rec.id}&project_id={rec.module.project_id}&module_id={rec.module_id}&version={rec.version}&full_dir={rec.full_dir}')
        assert r.status_code == 200
        assert f'FOCUS_RECORD_ID = {rec.id}'.encode() in r.data
        assert b'handleFocusRecord' in r.data
        print('  ✓ dashboard focus_record_id 参数注入')

        # 5. aggregate API 用新的 full_dir 列 (没回退到 extra_fields)
        r = client.get(f'/api/qor/aggregate?project_ids={rec.module.project_id}&group_by=run')
        d = r.get_json()
        assert d['group_by'] == 'run'
        labels = [it['label'] for it in d['items']]
        # 至少有一条 label 包含 demo full_dir
        demo_labels = [l for l in labels if 'main' in l or 'corner' in l or 'Q3' in l or 'v1.' in l or 'v2.' in l]
        assert demo_labels, f'未发现 demo full_dir label, 示例: {labels[:3]}'
        print(f'  ✓ aggregate 解析新 full_dir 列: 找到 {len(demo_labels)} 个 demo 路径标签')

        # 6. full_dir 列在 to_dict 中返回
        d = rec.to_dict()
        assert d['full_dir'] == rec.full_dir
        print(f'  ✓ to_dict 返回 full_dir = {d["full_dir"]}')


def test_release_role_access():
    """release 账号现在可查看所有记录 (v4.x 权限升级)"""
    with app.app_context():
        client = app.test_client()
        # 找 release 角色账号
        release = User.query.filter_by(role='release').first()
        if not release:
            print('  - 无 release 账号, 跳过')
            return
        with client.session_transaction() as sess:
            sess['_user_id'] = str(release.id)
            sess['_fresh'] = True
        # release 现在可查看所有数据 (含未发布)
        rec = QorRecord.query.filter_by(is_released=False).first()
        if rec:
            r = client.get(f'/api/qor/record/{rec.id}')
            assert r.status_code == 200, f'release 应可看未发布 200, 实际 {r.status_code}'
            print('  ✓ release 可看未发布记录 (权限升级)')
        rec2 = QorRecord.query.filter_by(is_released=True).first()
        if rec2:
            r = client.get(f'/api/qor/record/{rec2.id}')
            assert r.status_code == 200
            print('  ✓ release 可看已发布记录')


def main():
    print('===== full_dir + 详情页 + 跳转测试 =====')
    test_qor_record_detail()
    test_release_role_access()
    print('===== ALL PASSED =====')


if __name__ == '__main__':
    main()
