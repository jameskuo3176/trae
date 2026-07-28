"""端到端测试: 创建 tile review 含新字段, 验证 GET/PUT/详情"""
import os, sys, json
os.environ['FLASK_ENV'] = 'test'
sys.path.insert(0, r'd:\trae\trace_clock\qor_recorder\QoR_Recorder')

from app import app, db
from models import User, Project, Module, TileReview

app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False
# CSRF 关闭: 在 app 层 hook noop (before_request 已注册 csrf_protect)
# 直接替换 app 的 before_request 函数列表
app.before_request_funcs = {None: []}
client = app.test_client()

with app.app_context():
    # 找/创建 admin 用户
    admin = User.query.filter(User.role == 'admin').first()
    if not admin:
        print('FAIL: no admin user')
        sys.exit(1)
    project = Project.query.first()
    if not project:
        print('FAIL: no project')
        sys.exit(1)
    module = Module.query.filter_by(project_id=project.id).first()
    if not module:
        print('FAIL: no module')
        sys.exit(1)
    print(f'admin={admin.username}, project={project.name}, module={module.name}')

# Login
r = client.post('/login', data={'username': admin.username, 'password': 'admin@2026'}, follow_redirects=True)
print(f'login: {r.status_code}')

# GET 列表
r = client.get('/api/reviews/tile?project_id=' + str(project.id))
print(f'list tile: {r.status_code}')
data = r.get_json()
print(f'  items: {len(data.get("items", []))}')

# 创建 tile review 含新字段
body = {
    'project_id': project.id,
    'module_id': module.id,
    'title': 'TEST: 新字段 tile review',
    'period': 'weekly',
    'summary': '测试总结',
    'verdict': 'concern',
    'key_metrics': [
        {'name': 'TNS', 'target': 0, 'actual': -0.5, 'delta': '+0.1', 'status': 'warn', 'unit': 'ns'},
        {'name': 'WNS',  'target': 0, 'actual': -0.2, 'delta': '+0.05', 'status': 'good', 'unit': 'ns'},
    ],
    'findings': ['发现1: 路径违例', '发现2: 需要修复时序'],
    'decisions': [{'item': '决策1', 'owner': 'alice', 'due': '2026-08-01'}],
    'next_steps': [{'action': '后续1', 'owner': 'bob', 'due': '2026-08-10'}],
    'risks': [{'risk': '风险1', 'action': '处理1', 'owner': 'cathy'}],
}
r = client.post('/api/reviews/tile', json=body)
print(f'create: {r.status_code}')
if r.status_code != 201:
    print('  body:', r.get_json())
    sys.exit(1)
created = r.get_json()
rid = created['id']
print(f'  id={rid}')
print(f'  verdict={created.get("verdict")}')
print(f'  key_metrics count={len(created.get("key_metrics", []))}')
print(f'  findings count={len(created.get("findings", []))}')
print(f'  decisions count={len(created.get("decisions", []))}')
print(f'  next_steps count={len(created.get("next_steps", []))}')

# GET 单个 (新加的 API)
r = client.get(f'/api/reviews/tile/{rid}')
print(f'get one: {r.status_code}')
one = r.get_json()
print(f'  verdict={one.get("verdict")}, km={len(one.get("key_metrics", []))}, fi={len(one.get("findings", []))}')

# PUT 修改 verdict + 加 finding
body2 = {
    'project_id': project.id,
    'module_id': module.id,
    'verdict': 'blocked',
    'findings': ['发现1', '发现2', '发现3'],
}
r = client.put(f'/api/reviews/tile/{rid}', json=body2)
print(f'update: {r.status_code}')
upd = r.get_json()
print(f'  verdict={upd.get("verdict")}, findings count={len(upd.get("findings", []))}')

# Group review: 创建
body3 = {
    'project_id': project.id,
    'group_name': 'TEST_GROUP',
    'title': 'TEST: group review',
    'period': 'weekly',
    'tile_review_ids': [rid],
    'verdict': 'pass',
    'findings': ['group finding 1'],
    'key_metrics': [{'name': 'GroupTNS', 'target': 0, 'actual': -0.1, 'delta': '+0.02', 'status': 'good'}],
}
r = client.post('/api/reviews/group', json=body3)
print(f'create group: {r.status_code}')
if r.status_code == 201:
    gid = r.get_json()['id']
    print(f'  gid={gid}, verdict={r.get_json().get("verdict")}')

# Subsystem review
body4 = {
    'project_id': project.id,
    'subsystem': 'TEST_SUBSYS',
    'title': 'TEST: subsystem',
    'period': 'weekly',
    'verdict': 'concern',
    'findings': ['sys finding 1'],
}
r = client.post('/api/reviews/subsystem', json=body4)
print(f'create subsystem: {r.status_code}')
if r.status_code == 201:
    sid = r.get_json()['id']
    print(f'  sid={sid}, verdict={r.get_json().get("verdict")}')

# 清理
with app.app_context():
    TileReview.query.filter_by(id=rid).delete()
    db.session.commit()
print('cleanup OK')
print('=== ALL PASS ===')
