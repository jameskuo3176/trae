"""按维度聚合 QoR 端点测试 (group_by=base_dir|module|run)

验证:
  1. parse_full_dir 正确解析路径
  2. /api/qor/aggregate?group_by=run 返回每条 run 一行
  3. /api/qor/aggregate?group_by=base_dir 按 base_dir 跨模块汇总
  4. /api/qor/aggregate?group_by=module 按模块跨 base_dir 汇总
  5. 指标方向 (min/max) 正确返回
  6. full_dir 拼接为唯一 tag, 避免跨 base_dir 的 run 重名
"""
import os
import sys
import json
import random
import string

# 允许直接 python test_qor_aggregate.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db  # noqa
from routes.qor import parse_full_dir as _parse_full_dir  # noqa
from models import User, Project, Module, QorRecord
from core.db_routing import switch_to_project
from core.project_db import create_project_db, project_session_scope
from datetime import datetime, timedelta


def _random_str(n=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _ensure_admin():
    admin = User.query.filter_by(username='agg_admin').first()
    if not admin:
        admin = User(username='agg_admin', role='admin')
        admin.set_password('admin')
        db.session.add(admin)
        db.session.commit()
    return admin


def _ensure_project():
    proj = Project.query.filter_by(name='AggTestProj').first()
    if not proj:
        proj = Project(name='AggTestProj', description='aggregate test')
        db.session.add(proj)
        db.session.commit()
        # 为该项目创建独立 DB (按项目分库架构)
        create_project_db(proj.id)
    return proj


def _ensure_modules(proj):
    """创建/获取测试模块, 写入项目库 (使用 project_session_scope)

    Module / QorRecord 在项目库中, 需要在项目上下文 (project_session_scope) 中操作
    """
    names = ['modulea', 'moduleb']
    mods = []
    with project_session_scope(proj.id) as sess:
        for n in names:
            m = sess.query(Module).filter_by(project_id=proj.id, name=n).first()
            if not m:
                m = Module(project_id=proj.id, name=n, description='')
                sess.add(m)
                sess.flush()
            mods.append(m)
    return mods


def _add_record(module, version, full_dir, **metrics):
    """添加测试 record, 写入项目库 (使用 project_session_scope)"""
    with project_session_scope(module.project_id) as sess:
        rec = QorRecord(
            module_id=module.id,
            version=version,
            full_dir=full_dir,
            recorded_at=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
        )
        for k, v in metrics.items():
            setattr(rec, k, v)
        sess.add(rec)
    return rec


# 路径解析
def test_parse_full_dir():
    assert _parse_full_dir('') == {'base_dir': '', 'sub_path': '', 'run_name': '', 'level': 0}
    assert _parse_full_dir('solo')['run_name'] == 'solo'
    assert _parse_full_dir('solo')['base_dir'] == ''
    a = _parse_full_dir('v1/foo')
    assert a['base_dir'] == 'v1' and a['run_name'] == 'foo' and a['level'] == 2
    b = _parse_full_dir('2026_0728_weekly/main/modulea_run1')
    assert b['base_dir'] == '2026_0728_weekly'
    assert b['sub_path'] == 'main'
    assert b['run_name'] == 'modulea_run1'
    assert b['level'] == 3
    c = _parse_full_dir('a/b/c/d/run_x')
    assert c['base_dir'] == 'a'
    assert c['sub_path'] == 'b/c/d'
    assert c['run_name'] == 'run_x'
    print('  ✓ parse_full_dir')


def main():
    print('===== QoR aggregate tests =====')
    with app.app_context():
        # 清理旧测试数据
        proj = Project.query.filter_by(name='AggTestProj').first()
        if proj:
            with project_session_scope(proj.id) as sess:
                sess.query(QorRecord).filter(QorRecord.module_id.in_(
                    [m.id for m in sess.query(Module).filter_by(project_id=proj.id).all()]
                )).delete(synchronize_session=False)
                sess.query(Module).filter_by(project_id=proj.id).delete()
            db.session.delete(proj)
            db.session.commit()

        proj = _ensure_project()
        mods = _ensure_modules(proj)
        ma, mb = mods

        # 构造 4 条记录, 两个 base_dir 各 2 个 module + 1 run
        # base_dir=v1: modulea_run1, moduleb_run1
        # base_dir=v2: modulea_run1, moduleb_run2
        records_data = [
            (ma, 'v1', 'v1/main/modulea_run1', {'area_total': 1000, 'wns_setup': -0.1, 'cell_count': 500}),
            (mb, 'v1', 'v1/main/moduleb_run1', {'area_total': 2000, 'wns_setup': -0.2, 'cell_count': 800}),
            (ma, 'v2', 'v2/main/modulea_run1', {'area_total': 1100, 'wns_setup': -0.05, 'cell_count': 550}),
            (mb, 'v2', 'v2/main/moduleb_run2', {'area_total': 1900, 'wns_setup': -0.3,  'cell_count': 700}),
        ]
        for m, v, fd, mt in records_data:
            _add_record(m, v, fd, **mt)
        db.session.commit()

        client = app.test_client()
        # 登录
        admin = _ensure_admin()
        client.post('/login', data={'username': 'agg_admin', 'password': 'admin'})

        # 1. group_by=run -> 4 行, 各自 area_total 不同
        r = client.get(f'/api/qor/aggregate?project_ids={proj.id}&group_by=run')
        data = r.get_json()
        assert r.status_code == 200, f'got {r.status_code}'
        assert data['group_by'] == 'run'
        assert data['group_count'] == 4, f"expect 4 runs, got {data['group_count']}"
        # 验证 label 拼接: 跨 base_dir 同一 run_name 应有不同 label
        labels = [it['label'] for it in data['items']]
        assert 'v1/main/modulea_run1' in labels, f'labels={labels}'
        assert 'v2/main/modulea_run1' in labels, f'labels={labels}'  # 不同 base_dir 区分开了
        # 验证有 area_total
        for it in data['items']:
            assert 'area_total' in it and it['area_total']['count'] == 1
        print('  ✓ group_by=run: 4 行, label 跨 base_dir 唯一')

        # 2. group_by=base_dir -> 2 个 base_dir, 跨 module 汇总
        r = client.get(f'/api/qor/aggregate?project_ids={proj.id}&group_by=base_dir')
        data = r.get_json()
        assert r.status_code == 200
        assert data['group_count'] == 2, f"expect 2 base_dirs, got {data['group_count']}"
        bd_v1 = next(it for it in data['items'] if it['label'] == 'v1')
        bd_v2 = next(it for it in data['items'] if it['label'] == 'v2')
        # v1 = (1000+2000)/2 = 1500
        assert abs(bd_v1['area_total']['avg'] - 1500) < 0.01, f"v1 avg={bd_v1['area_total']['avg']}"
        # v2 = (1100+1900)/2 = 1500
        assert abs(bd_v2['area_total']['avg'] - 1500) < 0.01
        # v1 area_total min=1000, max=2000
        assert bd_v1['area_total']['min'] == 1000
        assert bd_v1['area_total']['max'] == 2000
        # v1 WNS = min(-0.1, -0.2) = -0.2, max = -0.1
        assert abs(bd_v1['wns_setup']['min'] - (-0.2)) < 1e-6
        print('  ✓ group_by=base_dir: 2 组, avg/min/max 正确')

        # 3. group_by=module -> 2 个 module, 跨 base_dir 汇总
        r = client.get(f'/api/qor/aggregate?project_ids={proj.id}&group_by=module')
        data = r.get_json()
        assert r.status_code == 200
        assert data['group_count'] == 2
        ma_row = next(it for it in data['items'] if it['label'] == 'modulea')
        mb_row = next(it for it in data['items'] if it['label'] == 'moduleb')
        # modulea 跨 v1/v2: area_total avg = (1000+1100)/2 = 1050
        assert abs(ma_row['area_total']['avg'] - 1050) < 0.01
        # moduleb 跨 v1/v2: cell_count avg = (800+700)/2 = 750
        assert abs(mb_row['cell_count']['avg'] - 750) < 0.01
        # 包含 v1 + v2 两条记录
        assert ma_row['count'] == 2
        print('  ✓ group_by=module: 2 个 module 跨 base_dir 汇总')

        # 4. metric_directions 正确
        assert 'area_total' in data['metric_directions']
        assert data['metric_directions']['area_total'] == 'min'
        # 用户约定: 时序类指标全部按"越小越好"处理, 与 setup 一致
        assert data['metric_directions']['wns_setup'] == 'min'
        assert data['metric_directions']['wns_hold'] == 'min'
        assert data['metric_directions']['tns_setup'] == 'min'
        assert data['metric_directions']['tns_hold'] == 'min'
        assert data['metric_directions']['nvp_setup'] == 'min'
        assert data['metric_directions']['nvp_hold'] == 'min'
        assert data['metric_directions']['mbb_ratio'] == 'max'
        print('  ✓ metric_directions: 时序统一 min, mbb_ratio=max')

        # 5. group_by 错误返回 400
        r = client.get(f'/api/qor/aggregate?project_ids={proj.id}&group_by=bad')
        assert r.status_code == 400
        print('  ✓ group_by 错误 400')

        # 6. parse_path 端点
        r = client.get('/api/qor/parse_path?full_dir=v1/main/modulea_run1')
        assert r.status_code == 200
        d = r.get_json()
        assert d['base_dir'] == 'v1' and d['run_name'] == 'modulea_run1'
        print('  ✓ parse_path API')

        # 7. 单 metric 过滤
        r = client.get(f'/api/qor/aggregate?project_ids={proj.id}&group_by=base_dir&metric=wns_setup')
        d = r.get_json()
        for it in d['items']:
            assert 'wns_setup' in it
            assert 'area_total' not in it
        print('  ✓ 单 metric 过滤生效')

    print('===== ALL PASSED =====')


if __name__ == '__main__':
    test_parse_full_dir()
    main()
