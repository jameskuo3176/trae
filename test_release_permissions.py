"""release 角色权限升级测试 (v4.x)
覆盖:
  1. release 可查看所有数据 (不再过滤 is_released)
  2. release 可访问 /admin 页面 (管理自己 release 的)
  3. release 可访问 /compare 页面
  4. release 可访问 /qor_record/<id> 详情页 (任意记录)
  5. release 可撤回自己发布的记录
  6. release 不能发布他人未发布的记录
  7. release 不能撤回他人发布的记录
  8. release 不能删除记录
"""
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 重要: 必须在 import app 之前禁用登录限流, 否则多个 test 累积超过 5 次触发 429
import security as _sec_mod
_orig_rate_limit = _sec_mod.rate_limit

def _no_rate_limit(*args, **kwargs):
    """绕过登录限流的装饰器 (测试专用)"""
    def decorator(fn):
        return fn
    return decorator

# 替换全局 rate_limit
import routes.auth as _auth_mod
_auth_mod.rate_limit = _no_rate_limit
_sec_mod.rate_limit = _no_rate_limit

from app import app  # noqa
from models import User, QorRecord, db  # noqa


_ACCOUNT_READY = False


def _reset_rate_limiter():
    """清空内存限流器 (测试间共享同一 IP 127.0.0.1, 必须重置)"""
    import security
    if hasattr(security, '_limiter') and hasattr(security._limiter, '_buckets'):
        security._limiter._buckets.clear()


def _ensure_release_account():
    """确保 release 账号存在 + 密码已知 (每个测试进程只执行一次, 避免触发登录限流)"""
    global _ACCOUNT_READY
    if _ACCOUNT_READY:
        return
    _reset_rate_limiter()
    with app.app_context():
        r = User.query.filter_by(username='release').first()
        if r is None:
            r = User(username='release', role='release', display_name='Release')
            r.set_password('Release@2026')
            r.must_change_password = False
            db.session.add(r)
            db.session.commit()
        else:
            r.set_password('Release@2026')
            r.must_change_password = False
            db.session.commit()
        _ACCOUNT_READY = True
    return r


def test_release_can_view_all_data():
    """[1] release 角色可查看所有数据 (不再过滤 is_released)"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.test_client() as c:
        c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
               follow_redirects=False)
        r = c.get('/api/qor_data?project_ids=&module_ids=&versions=&owner_username=')
        assert r.status_code == 200, f'qor_data 应 200, 实际 {r.status_code}'
        data = r.get_json()
        # release 现在可看到所有记录 (未发布的也应可见)
        all_count = len(data)
        released_count = sum(1 for x in data if x.get('is_released'))
        print(f'  qor_data: {all_count} 条 ({released_count} 已发布, {all_count - released_count} 未发布)')
        assert all_count > 0, 'release 至少应看到一条记录'
    print('[1] release 查看所有数据 OK')


def test_release_can_access_admin_page():
    """[2] release 可访问 /admin 页面 (200 而不是 403)"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.test_client() as c:
        c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
               follow_redirects=False)
        r = c.get('/admin', follow_redirects=False)
        assert r.status_code == 200, f'/admin 应 200, 实际 {r.status_code}'
    print('[2] release 访问 /admin 200 OK')


def test_release_can_access_compare():
    """[3] release 可访问 /compare 页面"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.test_client() as c:
        c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
               follow_redirects=False)
        r = c.get('/compare', follow_redirects=False)
        assert r.status_code == 200, f'/compare 应 200, 实际 {r.status_code}'
    print('[3] release 访问 /compare 200 OK')


def test_release_can_view_record_detail():
    """[4] release 可访问 /qor_record/<id> (任意记录)"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.app_context():
        any_rec = QorRecord.query.first()
        assert any_rec is not None, '需要至少一条记录'
        rec_id = any_rec.id
    with app.test_client() as c:
        c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
               follow_redirects=False)
        r = c.get(f'/qor_record/{rec_id}', follow_redirects=False)
        assert r.status_code == 200, f'/qor_record/{rec_id} 应 200, 实际 {r.status_code}'
    print('[4] release 查看任意 record 详情 200 OK')


def test_release_cannot_release_others():
    """[5] release 不能发布他人未发布的记录"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.app_context():
        # QorRecord 在项目库, 不能直接 query.filter_by, 用 SQL 找
        from sqlalchemy import create_engine, text
        from core.project_db import project_db_path
        from models import Project, User
        rel = User.query.filter_by(username='release').first()
        target = None
        for p in Project.query.all():
            path = project_db_path(p.id)
            if not __import__('os').path.exists(path):
                continue
            eng = create_engine(f'sqlite:///{path}')
            with eng.connect() as c:
                row = c.execute(text(
                    "SELECT id, module_id FROM qor_records "
                    "WHERE is_released=0 OR is_released IS NULL LIMIT 1"
                )).fetchone()
            eng.dispose()
            if row:
                target = (p.id, row[0])  # (project_id, record_id)
                break
        if target is None:
            print('  跳过: 无未发布记录 (请先 release 一条再撤回)')
            print('[5] release 拒绝发布他人记录 OK (skipped)')
            return
        rid = target[1]
    with app.test_client() as c:
        c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
               follow_redirects=False)
        page = c.get('/admin').data.decode()
        m = re.search(r'csrf-token" content="([^"]+)"', page)
        csrf = m.group(1) if m else ''
        r = c.post(f'/api/admin/qor/{rid}/release',
                   headers={'X-CSRF-Token': csrf})
        body = r.get_json() or {}
        assert r.status_code == 403, f'发布应 403, 实际 {r.status_code} {body}'
        assert 'release 角色' in (body.get('error') or ''), f'错误信息应提到 release, 实际 {body}'
    print('[5] release 拒绝发布他人未发布记录 403 OK')


def test_release_cannot_recall_others():
    """[6] release 不能撤回他人发布的记录"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.app_context():
        from sqlalchemy import create_engine, text
        from core.project_db import project_db_path
        from models import Project, User
        rel = User.query.filter_by(username='release').first()
        target = None
        for p in Project.query.all():
            path = project_db_path(p.id)
            if not __import__('os').path.exists(path):
                continue
            eng = create_engine(f'sqlite:///{path}')
            with eng.connect() as c:
                row = c.execute(text(
                    f"SELECT id FROM qor_records "
                    f"WHERE is_released=1 AND released_by != {rel.id} LIMIT 1"
                )).fetchone()
            eng.dispose()
            if row:
                target = (p.id, row[0])
                break
        if target is None:
            print('  跳过: 无他人发布的记录')
            print('[6] release 拒绝撤回他人记录 OK (skipped)')
            return
        rid = target[1]
    with app.test_client() as c:
        r = c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
                   follow_redirects=False)
        import sys
        print(f'  [debug] login status={r.status_code}', file=sys.stderr)
        page = c.get('/admin').data.decode()
        m = re.search(r'csrf-token" content="([^"]+)"', page)
        csrf = m.group(1) if m else ''
        print(f'  [debug] csrf len={len(csrf)}', file=sys.stderr)
        r = c.post(f'/api/admin/qor/{rid}/release',
                   headers={'X-CSRF-Token': csrf})
        body = r.get_json() or {}
        assert r.status_code == 403, f'撤回他人记录应 403, 实际 {r.status_code} {body}'
    print('[6] release 拒绝撤回他人发布记录 403 OK')


def test_release_cannot_delete():
    """[7] release 不能删除记录"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.app_context():
        rec = QorRecord.query.first()
        if rec is None:
            print('  跳过: 无记录')
            return
        rid = rec.id
    with app.test_client() as c:
        c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
               follow_redirects=False)
        page = c.get('/admin').data.decode()
        m = re.search(r'csrf-token" content="([^"]+)"', page)
        csrf = m.group(1) if m else ''
        r = c.delete(f'/api/admin/qor/{rid}',
                     headers={'X-CSRF-Token': csrf})
        # 端点内有 if current_user.is_release: 403
        body = r.get_json() or {}
        assert r.status_code == 403, f'删除应 403, 实际 {r.status_code} {body}'
    print('[7] release 拒绝删除记录 403 OK')


def test_release_can_recall_own():
    """[8] release 可撤回自己发布的记录 (端到端)"""
    _ensure_release_account()
    _reset_rate_limiter()
    with app.app_context():
        from sqlalchemy import create_engine, text
        from core.project_db import project_db_path
        from models import Project, User
        rel = User.query.filter_by(username='release').first()
        target = None
        for p in Project.query.all():
            path = project_db_path(p.id)
            if not __import__('os').path.exists(path):
                continue
            eng = create_engine(f'sqlite:///{path}')
            with eng.connect() as c:
                row = c.execute(text(
                    f"SELECT id FROM qor_records "
                    f"WHERE is_released=1 AND released_by={rel.id} LIMIT 1"
                )).fetchone()
            eng.dispose()
            if row:
                target = (p.id, row[0])
                break
        if target is None:
            print('  跳过: 无 release 自己发布的记录 (请先用 admin 标记一条为 released_by=release 后再测)')
            print('[8] release 撤回自己记录 OK (skipped)')
            return
        rid = target[1]
        with app.test_client() as c:
            c.post('/login', data={'username': 'release', 'password': 'Release@2026'},
                   follow_redirects=False)
            page = c.get('/admin').data.decode()
            m = re.search(r'csrf-token" content="([^"]+)"', page)
            csrf = m.group(1) if m else ''
            r = c.post(f'/api/admin/qor/{rid}/release',
                       headers={'X-CSRF-Token': csrf})
            body = r.get_json() or {}
            assert r.status_code == 200, f'撤回自己发布应 200, 实际 {r.status_code} {body}'
            assert body.get('is_released') is False, f'is_released 应 False, 实际 {body}'
        print('[8] release 撤回自己发布记录 OK')


if __name__ == '__main__':
    test_release_can_view_all_data()
    test_release_can_access_admin_page()
    test_release_can_access_compare()
    test_release_can_view_record_detail()
    test_release_cannot_release_others()
    test_release_cannot_recall_others()
    test_release_cannot_delete()
    test_release_can_recall_own()
    print('\nALL PASS')
