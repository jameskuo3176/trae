"""Group API 端到端 HTTP 测试 (模拟登录 session)"""
import os
os.environ['DATABASE_BACKEND'] = 'sqlite'
import sys
import json
import logging
logging.basicConfig(level=logging.WARNING)

import app as app_module
# 单元测试模式: 关闭 CSRF
app_module.app.config['TESTING'] = True
app_module.app.config['WTF_CSRF_ENABLED'] = False
# patch csrf_protect 为 noop
import security as _sec
_sec.csrf_protect = lambda: None
app_module.csrf_protect = lambda: None
# patch rate_limit: 让 _limiter.check 永远返回 allowed
class _AllowAll:
    def check(self, *a, **kw): return (True, 9999, 0)
_sec._limiter = _AllowAll()

from models import db, User, Project, Module, DashboardGroup, QorRecord

PASS, FAIL = '✓', '✗'
results = []


def check(name, cond, detail=''):
    if cond:
        print(f'  {PASS} {name}'); results.append(True)
    else:
        print(f'  {FAIL} {name}  {detail}'); results.append(False)


def login_and_get_token(username, password):
    """为单个用户创建独立 client, login, 返回 (client, token)"""
    c = app_module.app.test_client()
    r = c.post('/login', data={
        'username': username, 'password': password
    }, follow_redirects=False)
    # 立刻 follow redirect 确保 client cookie 写回 (Flask-Login 写入 session)
    if r.status_code == 302:
        c.get(r.headers.get('Location') or '/', follow_redirects=False)
    with c.session_transaction() as sess:
        token = sess.get('_csrf_token', '')
        sess_user = sess.get('_user_id')
    print(f'  [login] {username} sess_user_id={sess_user} token={token[:8]}...')
    return c, token or ''


def post(client, url, token, data):
    return client.post(url, data=json.dumps(data),
                       content_type='application/json',
                       headers={'X-CSRFToken': token})


def put(client, url, token, data):
    return client.put(url, data=json.dumps(data),
                      content_type='application/json',
                      headers={'X-CSRFToken': token})


def prepare_data():
    """在 with app_context 中准备数据, 退出 with 后再 login"""
    with app_module.app.app_context():
        admin = User.query.filter_by(username='admin').first()
        u1 = User.query.filter_by(username='user').first()
        rel = User.query.filter_by(username='release').first()
        if u1:
            u1.set_password('user@2026'); db.session.commit()
        if rel:
            rel.set_password('release@2026'); db.session.commit()
        p1 = Project.query.filter_by(name='TestP1').first()
        if p1 is None:
            p1 = Project(name='TestP1', description='for test')
            db.session.add(p1)
        p2 = Project.query.filter_by(name='TestP2').first()
        if p2 is None:
            p2 = Project(name='TestP2', description='for test')
            db.session.add(p2)
        db.session.commit()
        DashboardGroup.query.delete()
        db.session.commit()
        # 退出 with 块前, 把 id 取出 (避免 detached instance)
        return p1.id, p2.id, u1.id if u1 else None, rel.id if rel else None


def main():
    p1_id, p2_id, u1_id, rel_id = prepare_data()
    # 退出 with 块后再 login (避免 outer app context 干扰)
    admin_c, admin_token = login_and_get_token('admin', 'admin@2026')
    user_c, user_token = login_and_get_token('user', 'user@2026')
    rel_c, rel_token = login_and_get_token('release', 'release@2026')
    for c, name in [(admin_c, 'admin'), (user_c, 'user'), (rel_c, 'release')]:
        with c.session_transaction() as sess:
            print(f'  [verify] {name} user_id={sess.get("_user_id")}')

        # 1) admin 创建 p1 group
        r = post(admin_c, '/api/groups', admin_token, {
            'name': 'Floorplan-Team',
            'project_id': p1_id,
            'config': {'modules': ['1']},
            'shared_default': True,
            'is_public': True,
        })
        check('admin 创建 p1 group 201', r.status_code == 201,
              f'status={r.status_code} body={r.get_data(as_text=True)[:200]}')
        g1 = r.get_json()
        check('返回值含 id', 'id' in g1)
        check('返回值含 owner_name=admin', g1.get('owner_name') == 'admin')

        # 2) 同 project 同名 400
        r = post(admin_c, '/api/groups', admin_token, {
            'name': 'Floorplan-Team', 'project_id': p1_id
        })
        check('同 project 同名 400', r.status_code == 400)

        # 3) 不同 project 同名 201 (也设 is_public 让 user 可见)
        r = post(admin_c, '/api/groups', admin_token, {
            'name': 'Floorplan-Team', 'project_id': p2_id, 'is_public': True
        })
        check('不同 project 同名 201', r.status_code == 201,
              f'body={r.get_data(as_text=True)[:200]}')

        # 4) admin 列表 2 个
        r = admin_c.get('/api/groups')
        check('admin 列表 2 个 group', len(r.get_json()) == 2)

        # 5) user 看到 2 个公开 group
        r = user_c.get('/api/groups')
        items = r.get_json()
        check('user 看到 2 个公开 group', len(items) == 2)

        # 6) user 调 my-default -> null (不是成员)
        r = user_c.get('/api/groups/my-default')
        check('user my-default null', r.get_json()['group'] is None)

        # 7) admin 把 user 加入 p1 group
        r = put(admin_c, f'/api/groups/{g1["id"]}', admin_token, {'member_ids': [u1_id]})
        check('admin 把 user 加入 member', r.status_code == 200,
              f'body={r.get_data(as_text=True)[:200]}')

        # 8) user 现在拿到 my-default
        r = user_c.get('/api/groups/my-default')
        my = r.get_json()
        check('user my-default 返回 g1', my['group'] is not None and my['group']['id'] == g1['id'])
        check('user my-default config.modules=["1"]',
              my['config'].get('modules') == ['1'])

        # 9) user 不可编辑别人的 group
        r = put(user_c, f'/api/groups/{g1["id"]}', user_token, {'name': 'hacked'})
        check('非 owner 编辑被拒 403', r.status_code == 403)

        # 10) release 在无发布数据时 0 个
        r = rel_c.get('/api/groups')
        check('release 在无发布数据时 0 个 group', len(r.get_json()) == 0)

        # 11) release 不能创建
        r = post(rel_c, '/api/groups', rel_token, {'name': 'evil'})
        check('release 创建 group 403', r.status_code == 403)

        # 12) 清理
        with app_module.app.app_context():
            DashboardGroup.query.delete()
            db.session.commit()

        print(f'\n==========  {"全部通过" if all(results) else f"{results.count(False)} 项失败"} ==========')
        sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
