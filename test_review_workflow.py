"""Review 流程 HTTP 端点测试.

覆盖:
  - Tile / Group / Subsystem / Snapshot 的 CRUD + 状态机
  - 权限控制 (admin / editor / viewer / 跨项目)
  - 文件上传/下载
  - 数据冻结与校验
"""
import io
import os
import sys
import json
import logging
logging.basicConfig(level=logging.WARNING)

# 先关闭 CSRF + rate limit (必须在 import app 之前)
os.environ['DATABASE_BACKEND'] = 'sqlite'
os.environ['ENABLE_RATE_LIMIT'] = '0'
# 强制测试使用独立 DB, 避免污染线上数据
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'qor_recorder_test.db'
)

import app as app_module
app_module.app.config['TESTING'] = True
app_module.app.config['WTF_CSRF_ENABLED'] = False

import security as _sec
_sec.csrf_protect = lambda: None
app_module.csrf_protect = lambda: None
class _AllowAll:
    def check(self, *a, **kw): return (True, 9999, 0)
_sec._limiter = _AllowAll()

from models import db, User, Project, Module, QorRecord, ProjectMember

PASS, FAIL = '✓', '✗'
results = []


def check(name, cond, detail=''):
    if cond:
        print(f'  {PASS} {name}'); results.append(True)
    else:
        print(f'  {FAIL} {name}  {detail}'); results.append(False)


def login(username, password="user@2026"):
    if username == "admin":
        password = "admin@2026"
    elif username == "rel":
        password = "release@2026"
    c = app_module.app.test_client()
    r = c.post('/login', data={'username': username, 'password': password}, follow_redirects=False)
    if r.status_code == 302:
        c.get(r.headers.get('Location') or '/', follow_redirects=False)
    return c


# 测试期间禁用 CSRF 保护, 避免 POST 请求被拦截
import security as _sec
_sec.csrf_protect = lambda: None
# core.security 通过 _security 模块代理, 同步替换
import core.security as _core_sec
_core_sec._security.csrf_protect = lambda: None


# ============== 数据准备 ==============
def prepare_data():
    """每次跑测试前重置 db, 插入 fixture 数据. 返回 id 字典."""
    with app_module.app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(username='admin', role='admin'); admin.set_password('admin@2026')
        owner = User(username='tileowner', role='user'); owner.set_password('user@2026')
        leader = User(username='groupleader', role='user'); leader.set_password('user@2026')
        manager = User(username='sysmgr', role='user'); manager.set_password('user@2026')
        viewer = User(username='viewer', role='user'); viewer.set_password('user@2026')
        rel = User(username='rel', role='release'); rel.set_password('release@2026')
        for u in [admin, owner, leader, manager, viewer, rel]:
            db.session.add(u)
        db.session.flush()
        proj = Project(name='RISC-V Demo', description='test project')
        db.session.add(proj)
        db.session.flush()
        mods = [Module(project_id=proj.id, name=n) for n in ('ALU', 'RF', 'CTRL')]
        for m in mods:
            db.session.add(m)
        db.session.flush()
        rec = QorRecord(
            module_id=mods[0].id, version='v1',
            area_total=1000.0, area_combinational=600.0, area_sequential=400.0,
            wns_setup=-0.1, tns_setup=-1.0, nvp_setup=2,
            power_total=10.0, cell_count=5000,
        )
        db.session.add(rec)
        db.session.flush()
        for u, role in [(owner, 'editor'), (leader, 'editor'), (manager, 'editor'),
                        (viewer, 'viewer')]:
            db.session.add(ProjectMember(project_id=proj.id, user_id=u.id, role=role))
        db.session.commit()
        return {
            'admin': admin.id, 'owner': owner.id, 'leader': leader.id,
            'manager': manager.id, 'viewer': viewer.id, 'release': rel.id,
            'project_id': proj.id, 'module_id': mods[0].id, 'module2_id': mods[1].id,
            'record_id': rec.id,
        }


def _create_approved_tile(c, env, module_id=None, record_id=None, title='tile'):
    module_id = module_id or env['module_id']
    r = c.post('/api/reviews/tile', json={
        'project_id': env['project_id'],
        'module_id': module_id,
        'record_id': record_id,
        'title': title,
    })
    assert r.status_code == 201, r.data
    tid = r.get_json()['id']
    r = c.post(f'/api/reviews/tile/{tid}/submit')
    assert r.status_code == 200, r.data
    admin_c = login('admin')
    r = admin_c.post(f'/api/reviews/tile/{tid}/review', json={'action': 'approve'})
    assert r.status_code == 200, r.data
    return tid


# ============== 测试用例 ==============
def run_all():
    print('===== Review workflow tests =====')
    env = prepare_data()

    # 1. 页面加载
    c = login('tileowner')
    r = c.get('/review')
    check('1. tileowner 加载 /review 200', r.status_code == 200,
          f'got {r.status_code} body={r.data[:200]}')

    c2 = login('rel')
    r = c2.get('/review', follow_redirects=False)
    check('2. release 角色 403', r.status_code == 403, f'got {r.status_code}')

    # 3. options API
    c = login('tileowner')
    r = c.get('/api/reviews/options')
    check('3. options 200', r.status_code == 200, f'got {r.status_code}')
    data = r.get_json()
    check('4. options 包含当前项目', any(p['id'] == env['project_id'] for p in data.get('projects', [])))

    c = login('admin')
    r = c.get('/api/reviews/options')
    data = r.get_json()
    check('5. admin 也能看到项目', any(p['id'] == env['project_id'] for p in data.get('projects', [])))

    # 6. tile 创建 - 提交 - approve
    c = login('tileowner')
    r = c.post('/api/reviews/tile', json={
        'project_id': env['project_id'],
        'module_id': env['module_id'],
        'record_id': env['record_id'],
        'title': 'W35 ALU review',
        'period': 'weekly',
        'summary': 'WNS -0.1',
        'risks': [{'risk': 'hold', 'action': 'fix', 'owner': 'alice'}],
    })
    check('6. tile create 201', r.status_code == 201, f'got {r.status_code} body={r.data[:200]}')
    tile = r.get_json()
    check('7. tile status=draft', tile.get('status') == 'draft')
    check('8. tile metrics_snapshot 已生成', tile.get('metrics_snapshot') is not None
          and tile['metrics_snapshot'].get('area_total') == 1000.0)
    tid = tile['id']

    r = c.post(f'/api/reviews/tile/{tid}/submit')
    check('9. tile submit 200', r.status_code == 200)
    check('10. tile status=submitted', r.get_json()['status'] == 'submitted')

    c2 = login('groupleader')
    r = c2.post(f'/api/reviews/tile/{tid}/review', json={'action': 'approve', 'comment': 'ok'})
    check('11. tile approve 200', r.status_code == 200)
    check('12. tile status=approved', r.get_json()['status'] == 'approved')

    # 13. viewer 无权创建
    c = login('viewer')
    r = c.post('/api/reviews/tile', json={
        'project_id': env['project_id'],
        'module_id': env['module_id'],
        'title': 'viewer test',
    })
    check('13. viewer 创建 tile 403', r.status_code == 403, f'got {r.status_code} body={r.data[:200]}')

    # 14. reject 后可重新编辑
    c = login('tileowner')
    r = c.post('/api/reviews/tile', json={
        'project_id': env['project_id'],
        'module_id': env['module_id'],
        'title': 'W34',
    })
    tid2 = r.get_json()['id']
    c.post(f'/api/reviews/tile/{tid2}/submit')
    c2 = login('groupleader')
    c2.post(f'/api/reviews/tile/{tid2}/review', json={'action': 'reject', 'comment': 'redo'})
    r = c.put(f'/api/reviews/tile/{tid2}', json={'title': 'W34 revised'})
    check('14. rejected 后可 edit 200', r.status_code == 200, f'got {r.status_code}')
    r = c.post(f'/api/reviews/tile/{tid2}/submit')
    check('15. revised 后可 submit 200', r.status_code == 200)

    # 16. 重复 submit 失败
    c = login('tileowner')
    r = c.post('/api/reviews/tile', json={
        'project_id': env['project_id'],
        'module_id': env['module_id'],
        'title': 'twice',
    })
    tid3 = r.get_json()['id']
    c.post(f'/api/reviews/tile/{tid3}/submit')
    r = c.post(f'/api/reviews/tile/{tid3}/submit')
    check('16. 重复 submit 400', r.status_code == 400)

    # 17. group review
    c = login('tileowner')
    t1 = _create_approved_tile(c, env, record_id=env['record_id'], title='g tile 1')
    t2 = _create_approved_tile(c, env, title='g tile 2')
    c2 = login('groupleader')
    r = c2.post('/api/reviews/group', json={
        'project_id': env['project_id'],
        'group_name': 'CPU',
        'title': 'W35 CPU group',
        'tile_review_ids': [t1, t2],
    })
    check('17. group create 201', r.status_code == 201, f'got {r.status_code} body={r.data[:200]}')
    g = r.get_json()
    check('18. group aggregate 包含 area_total', g.get('aggregate', {}).get('area_total') is not None)
    gid = g['id']

    # 18. group 不可引用 draft tile
    c3 = login('tileowner')
    r = c3.post('/api/reviews/tile', json={
        'project_id': env['project_id'],
        'module_id': env['module_id'],
        'title': 'draft tile',
    })
    draft_tid = r.get_json()['id']
    r = c2.post('/api/reviews/group', json={
        'project_id': env['project_id'],
        'group_name': 'CPU',
        'tile_review_ids': [draft_tid],
    })
    check('19. 引用 draft tile 应 400', r.status_code == 400)

    # 20. 不能自审
    c = login('tileowner')
    r = c.post('/api/reviews/group', json={
        'project_id': env['project_id'],
        'group_name': 'CPU2',
        'title': 'self-review test',
        'tile_review_ids': [t1],
    })
    gid2 = r.get_json()['id']
    c.post(f'/api/reviews/group/{gid2}/submit')
    r = c.post(f'/api/reviews/group/{gid2}/review', json={'action': 'approve'})
    check('20. self review 400', r.status_code == 400)

    # 21. subsystem review
    c2.post(f'/api/reviews/group/{gid}/submit')
    admin_c = login('admin')
    admin_c.post(f'/api/reviews/group/{gid}/review', json={'action': 'approve'})
    c3 = login('sysmgr')
    r = c3.post('/api/reviews/subsystem', json={
        'project_id': env['project_id'],
        'subsystem': 'TOP',
        'title': 'TOP subsystem review',
        'group_review_ids': [gid],
    })
    check('21. subsystem create 201', r.status_code == 201, f'got {r.status_code} body={r.data[:200]}')
    s = r.get_json()
    check('22. subsystem aggregate count=1',
          s.get('aggregate', {}).get('area_total', {}).get('count') == 1)
    sid_review = s['id']
    c3.post(f'/api/reviews/subsystem/{sid_review}/submit')
    admin_c.post(f'/api/reviews/subsystem/{sid_review}/review', json={'action': 'approve'})

    # 23. snapshot 仅 admin
    c = login('sysmgr')
    r = c.post('/api/reviews/snapshot', json={'project_id': env['project_id'], 'name': 'x'})
    check('23. non-admin snapshot 403', r.status_code == 403)

    # 24. admin 创建 snapshot + 校验和 + 上传 + 下载
    r = admin_c.post('/api/reviews/snapshot', json={
        'project_id': env['project_id'],
        'subsystem_review_id': sid_review,
        'name': 'Tapeout v1.0',
        'snapshot_type': 'tapeout',
    })
    check('24. admin snapshot 201', r.status_code == 201, f'got {r.status_code} body={r.data[:200]}')
    snap = r.get_json()
    check('25. snapshot verified', snap.get('verified') is True)
    check('26. snapshot record_count=1', snap.get('record_count') == 1)
    snap_id = snap['id']

    # 上传附件
    r = admin_c.post(f'/api/reviews/snapshot/{snap_id}/upload', data={
        'file': (io.BytesIO(b'QOR report content here'), 'alu.rpt'),
        'category': 'rpt',
        'description': 'ALU report',
    }, content_type='multipart/form-data')
    check('27. 上传附件 201', r.status_code == 201, f'got {r.status_code} body={r.data[:200]}')

    # 详情
    r = admin_c.get(f'/api/reviews/snapshot/{snap_id}')
    s = r.get_json()
    check('28. 详情 file_count=1', s.get('file_count') == 1)
    check('29. 详情 files 列表 1 项', len(s.get('files', [])) == 1)

    # 下载
    fid = s['files'][0]['id']
    r = admin_c.get(f'/api/reviews/file/{fid}/download')
    check('30. 下载 200', r.status_code == 200, f'got {r.status_code}')
    check('31. 下载内容正确', r.data == b'QOR report content here')

    # 32. non-admin 不可删 snapshot
    c = login('sysmgr')
    r = c.delete(f'/api/reviews/snapshot/{snap_id}')
    check('32. non-admin delete snapshot 403', r.status_code == 403)

    # 33. admin 删 snapshot
    r = admin_c.delete(f'/api/reviews/snapshot/{snap_id}')
    check('33. admin delete snapshot 200', r.status_code == 200)

    # 34. 列表权限
    c = login('tileowner')
    r = c.get(f'/api/reviews/tile?project_id={env["project_id"]}')
    check('34. 列表 200', r.status_code == 200)
    items = r.get_json()['items']
    check('35. 列表有数据', len(items) >= 1)

    # 36. 跨项目 403
    c = login('tileowner')
    r = c.get(f'/api/reviews/tile?project_id=99999')
    check('36. 越权访问 403', r.status_code == 403)

    # ===== summary =====
    total = len(results)
    passed = sum(results)
    print(f'\n===== {passed}/{total} passed =====')
    if passed != total:
        sys.exit(1)


if __name__ == '__main__':
    run_all()
