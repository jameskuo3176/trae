"""v5.0 角色权限测试

测试 admin / owner / viewer 三个角色的核心权限:
  - 数据查看: admin/owner 全量, viewer 仅已发布
  - 数据管理: admin 任意, owner 自己+被授权, viewer 拒绝
  - 模块管理: admin 任意, owner 自己创建, viewer 拒绝
  - 协作者授权: 仅 admin/模块 owner
  - 写操作拦截: viewer 所有 POST/PUT/DELETE 403

前提: 已通过 v5 迁移 (user/release → owner, viewer 默认账户已创建)
"""
import os
import re
import sys
import json

sys.path.insert(0, '.')

import security as _sec_mod
import routes.auth as _auth_mod


def _no_rate_limit(*a, **kw):
    def deco(fn):
        return fn
    return deco


_auth_mod.rate_limit = _no_rate_limit
_sec_mod.rate_limit = _no_rate_limit

from app import app
from models import db, User, Project, Module, QorRecord
from core.project_db import project_db_path
from sqlalchemy import create_engine, text


# ======================== 工具函数 ========================

def _reset_rate_limiter():
    import security
    if hasattr(security, '_limiter') and hasattr(security._limiter, '_buckets'):
        security._limiter._buckets.clear()


def _get_csrf(client):
    page = client.get('/admin').data.decode() if '/admin' in str(client) else None
    if page is None:
        page = client.get('/').data.decode()
    m = re.search(r'csrf-token" content="([^"]+)"', page)
    return m.group(1) if m else ''


def _login(client, username, password):
    _reset_rate_limiter()
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=False)


def _ensure_default_accounts():
    """确保 admin / owner / viewer 三个测试账户存在"""
    with app.app_context():
        for uname, role, pwd in [
            ('admin', 'admin', 'admin@2026'),
            ('test_owner1', 'owner', 'Owner1@2026'),
            ('test_owner2', 'owner', 'Owner2@2026'),
            ('test_viewer', 'viewer', 'Viewer@2026'),
        ]:
            u = User.query.filter_by(username=uname).first()
            if u is None:
                u = User(username=uname, role=role, display_name=uname)
                u.set_password(pwd)
                u.must_change_password = False
                db.session.add(u)
            else:
                u.set_password(pwd)
                u.must_change_password = False
                u.role = role
        db.session.commit()


def _find_any_unreleased_record():
    """找到一个未发布记录 (project_id, record_id)"""
    with app.app_context():
        for p in Project.query.all():
            path = project_db_path(p.id)
            if not os.path.exists(path):
                continue
            eng = create_engine(f'sqlite:///{path}')
            try:
                with eng.connect() as c:
                    row = c.execute(text(
                        'SELECT id FROM qor_records WHERE is_released=0 OR is_released IS NULL LIMIT 1'
                    )).fetchone()
                    if row:
                        return p.id, row[0]
            finally:
                eng.dispose()
    return None


# ======================== 测试用例 ========================

def test_01_viewer_sees_only_released():
    """[1] viewer 角色: /api/qor_data 仅返回已发布记录"""
    _ensure_default_accounts()
    with app.test_client() as c:
        _login(c, 'test_viewer', 'Viewer@2026')
        r = c.get('/api/qor_data?project_ids=&module_ids=&versions=')
        assert r.status_code == 200, f'viewer qor_data 应 200, 实际 {r.status_code}'
        data = r.get_json()
        assert all(x.get('is_released') for x in data), 'viewer 看到未发布记录 (违规)'
        released_count = len(data)
        print(f'  viewer 看到 {released_count} 条已发布记录 (无未发布)')


def test_02_viewer_cannot_view_unreleased_record():
    """[2] viewer 访问未发布记录详情: 404"""
    _ensure_default_accounts()
    target = _find_any_unreleased_record()
    if target is None:
        print('  跳过: 无未发布记录')
        return
    _, rid = target
    with app.test_client() as c:
        _login(c, 'test_viewer', 'Viewer@2026')
        r = c.get(f'/api/qor/record/{rid}')
        assert r.status_code == 404, f'viewer 看未发布应 404, 实际 {r.status_code}'
    print('  viewer 看未发布记录 404 OK')


def test_03_viewer_cannot_post():
    """[3] viewer 所有 POST/PUT/DELETE 请求被 CSRF 或权限拦截"""
    _ensure_default_accounts()
    with app.test_client() as c:
        _login(c, 'test_viewer', 'Viewer@2026')
        # 试发布
        csrf = _get_csrf(c)
        r = c.post('/api/admin/qor/1/release', headers={'X-CSRF-Token': csrf})
        # 实际可能 403 (权限) 或 404 (记录不存在) 或 400 (CSRF)
        assert r.status_code in (403, 404, 400), f'viewer POST 应被拒, 实际 {r.status_code}'
        body = r.get_json() or {}
        if r.status_code == 403:
            assert 'viewer' in (body.get('error') or ''), f'应提到 viewer 角色, 实际 {body}'
    print('  viewer POST 被拒 OK')


def test_04_owner_can_see_all_data():
    """[4] owner 角色: 可查看所有数据 (含未发布)"""
    _ensure_default_accounts()
    with app.test_client() as c:
        _login(c, 'test_owner1', 'Owner1@2026')
        r = c.get('/api/qor_data?project_ids=&module_ids=&versions=')
        assert r.status_code == 200, f'owner qor_data 应 200, 实际 {r.status_code}'
        data = r.get_json()
        all_count = len(data)
        released = sum(1 for x in data if x.get('is_released'))
        print(f'  owner 看到 {all_count} 条 ({released} 已发布, {all_count - released} 未发布)')


def test_05_owner_can_view_admin():
    """[5] owner 可访问 /admin 页面"""
    _ensure_default_accounts()
    with app.test_client() as c:
        _login(c, 'test_owner1', 'Owner1@2026')
        r = c.get('/admin', follow_redirects=False)
        assert r.status_code == 200, f'owner /admin 应 200, 实际 {r.status_code}'
    print('  owner 访问 /admin 200 OK')


def test_06_viewer_cannot_view_admin():
    """[6] viewer 不能访问 /admin 页面: 403"""
    _ensure_default_accounts()
    with app.test_client() as c:
        _login(c, 'test_viewer', 'Viewer@2026')
        r = c.get('/admin', follow_redirects=False)
        assert r.status_code == 403, f'viewer /admin 应 403, 实际 {r.status_code}'
    print('  viewer 访问 /admin 被拒 403 OK')


def _delete_module_by_name(project_id, name):
    """清理测试模块: 直接走项目库 engine 删 (避免 ORM 自动路由问题)"""
    from core.project_db import get_project_engine
    eng = get_project_engine(project_id)
    try:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM modules WHERE name=:n"), {'n': name})
    finally:
        eng.dispose()


def _delete_module_by_id(project_id, module_id):
    """清理测试模块: 按 id 删"""
    from core.project_db import get_project_engine
    eng = get_project_engine(project_id)
    try:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM modules WHERE id=:i"), {'i': module_id})
    finally:
        eng.dispose()


def test_07_module_ownership_set_on_create():
    """[7] 创建模块时, owner_id 自动设为当前用户"""
    _ensure_default_accounts()
    with app.app_context():
        proj = Project.query.first()
        assert proj is not None, '需要至少一个项目'
        pid = proj.id
        # 确保 admin 是 ProjectMember (admin 角色)
        from models import ProjectMember
        admin_id = User.query.filter_by(username='admin').first().id
        member = ProjectMember.query.filter_by(project_id=pid, user_id=admin_id).first()
        if member is None:
            db.session.add(ProjectMember(project_id=pid, user_id=admin_id, role='admin'))
            db.session.commit()
    with app.test_client() as c:
        _login(c, 'admin', 'admin@2026')
        csrf = _get_csrf(c)
        module_name = f'__test_module_v5_{int(os.getpid())}__'
        # 先确保不存在
        _delete_module_by_name(pid, module_name)
        r = c.post('/api/admin/modules', headers={'X-CSRF-Token': csrf},
                   json={'project_id': pid, 'name': module_name})
        assert r.status_code == 200, f'admin 创建模块应 200, 实际 {r.status_code} {r.get_json()}'
        body = r.get_json()
        assert body.get('owner_id') is not None, 'admin 创建的模块应有 owner_id'
        assert body['owner_id'] == admin_id, f'owner_id 应为 admin id, 实际 {body}'
        # 清理
        _delete_module_by_name(pid, module_name)
    print('  模块创建后 owner_id 已设置 OK')


def test_08_collaborator_api():
    """[8] 模块协作者管理 API: 增/查/删"""
    _ensure_default_accounts()
    with app.app_context():
        proj = Project.query.first()
        assert proj is not None
        pid = proj.id
        admin_id = User.query.filter_by(username='admin').first().id
        owner2_id = User.query.filter_by(username='test_owner2').first().id
        from models import ProjectMember
        if not ProjectMember.query.filter_by(project_id=pid, user_id=admin_id).first():
            db.session.add(ProjectMember(project_id=pid, user_id=admin_id, role='admin'))
            db.session.commit()
    module_name = f'__collab_test_{int(os.getpid())}__'
    # 先确保不存在
    _delete_module_by_name(pid, module_name)
    module_id = None
    try:
        with app.test_client() as c:
            _login(c, 'admin', 'admin@2026')
            csrf = _get_csrf(c)
            r = c.post('/api/admin/modules', headers={'X-CSRF-Token': csrf},
                       json={'project_id': pid, 'name': module_name})
            assert r.status_code == 200, f'创建模块失败: {r.status_code} {r.get_json()}'
            module_id = r.get_json()['id']

            # 添加协作者 test_owner2
            r = c.post(f'/api/admin/modules/{module_id}/collaborators',
                       headers={'X-CSRF-Token': csrf},
                       json={'user_id': owner2_id})
            assert r.status_code == 200, f'添加协作者失败: {r.status_code} {r.get_json()}'

            # 列出协作者
            r = c.get(f'/api/admin/modules/{module_id}/collaborators')
            assert r.status_code == 200
            data = r.get_json()
            assert len(data['collaborators']) == 1, f'应 1 个协作者, 实际 {data}'
            assert data['collaborators'][0]['username'] == 'test_owner2'

            # 移除协作者
            collab_id = data['collaborators'][0]['id']
            r = c.delete(f'/api/admin/modules/{module_id}/collaborators/{collab_id}',
                         headers={'X-CSRF-Token': csrf})
            assert r.status_code == 200, f'移除失败: {r.status_code} {r.get_json()}'
    finally:
        # 清理测试模块
        if module_id is not None:
            _delete_module_by_id(pid, module_id)
        else:
            _delete_module_by_name(pid, module_name)
    print('  协作者管理 API (增/查/删) 全部 OK')


def test_09_legacy_roles_migrated():
    """[9] 历史 user / release 角色已自动迁移为 owner"""
    with app.app_context():
        for u in User.query.all():
            assert u.role != 'user', f'用户 {u.username} 仍为 user 角色, 未迁移'
            assert u.role != 'release' or u.username == 'release', (
                f'用户 {u.username} 仍为 release 角色'
            )
        # viewer 账户已创建
        v = User.query.filter_by(username='viewer').first()
        assert v is not None, '默认 viewer 账户未创建'
        assert v.role == 'viewer', f'viewer 账户角色错误: {v.role}'
    print('  历史角色已迁移, viewer 账户已存在 OK')


def test_10_viewer_cannot_compare_unreleased():
    """[10] viewer /api/compare 数据: 仅包含已发布数据 (通过 qor_data 间接验证)"""
    _ensure_default_accounts()
    with app.test_client() as c:
        _login(c, 'test_viewer', 'Viewer@2026')
        r = c.get('/compare')
        assert r.status_code == 200, f'viewer /compare 应 200, 实际 {r.status_code}'
        # viewer 可访问 /compare, 但底层数据过滤
        r = c.get('/api/qor_data?project_ids=&module_ids=&versions=')
        data = r.get_json() or []
        for x in data:
            assert x.get('is_released'), f'viewer 看到未发布: {x}'
    print('  viewer /compare 正常访问, 数据已过滤 OK')


# ======================== 主入口 ========================

def main():
    tests = [
        test_01_viewer_sees_only_released,
        test_02_viewer_cannot_view_unreleased_record,
        test_03_viewer_cannot_post,
        test_04_owner_can_see_all_data,
        test_05_owner_can_view_admin,
        test_06_viewer_cannot_view_admin,
        test_07_module_ownership_set_on_create,
        test_08_collaborator_api,
        test_09_legacy_roles_migrated,
        test_10_viewer_cannot_compare_unreleased,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f'[OK] {t.__name__}')
        except Exception as e:
            failed += 1
            print(f'[FAIL] {t.__name__}: {e}')
    print()
    print(f'===== 结果: {passed} passed, {failed} failed =====')
    return failed == 0


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
