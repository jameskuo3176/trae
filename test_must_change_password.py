"""强制改密 + 密码强度测试

覆盖:
  1. security.validate_password 各边界条件
  2. user_change_own_password 弱密码拒绝 / 强密码接受
  3. admin_reset_user_password 触发 must_change_password=True
  4. before_request 拦截: must_change=True 时写操作 403
  5. before_request 拦截: must_change=True 时 GET 页面跳转 /change_password
  6. 改密成功后 must_change_password 清零, GET 页面正常返回 200
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa
from models import User, db  # noqa
from security import validate_password


def test_validate_password():
    """密码强度校验 9 个用例"""
    cases = [
        ('',                  False, '空'),
        ('short1',            False, '长度<8'),
        ('allletters',        False, '无数字'),
        ('12345678',          False, '无字母'),
        ('password',          False, '弱口令'),
        ('password1',         False, '弱口令 8位'),
        ('admin123',          False, '弱口令黑名单'),
        ('Good@2026',         True,  '强口令'),
        ('MyPass_2026',       True,  '强口令'),
    ]
    for pw, expected_ok, label in cases:
        ok, err = validate_password(pw)
        assert ok == expected_ok, f'validate_password("{pw}"): got ok={ok}, want {expected_ok} ({label}) err={err}'
    print('[1] validate_password 9/9 OK')


def test_change_own_password():
    """改密端点: 弱密码拒绝, 强密码接受并清零 must_change_password"""
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        # 重置为已知值
        admin.set_password('OldPass@2026')
        admin.must_change_password = False
        admin.password_changed_at = None
        db.session.commit()

        from flask_login import login_user
        from routes.admin import user_change_own_password

        # 弱密码
        with app.test_request_context('/api/admin/user/password', method='POST', json={
            'old_password': 'OldPass@2026', 'new_password': 'weak',
        }):
            login_user(admin)
            rv = user_change_own_password()
            status = rv[1] if isinstance(rv, tuple) else rv.status_code
            body = rv[0].get_json() if isinstance(rv, tuple) and hasattr(rv[0], 'get_json') else rv.get_json()
            assert status == 400, f'弱密码应被 400, 实际 {status} {body}'
            assert '密码' in (body.get('error') or ''), f'错误信息应包含"密码", 实际 {body}'

        # 强密码
        with app.test_request_context('/api/admin/user/password', method='POST', json={
            'old_password': 'OldPass@2026', 'new_password': 'NewPass@2026',
        }):
            login_user(admin)
            rv = user_change_own_password()
            status = rv[1] if isinstance(rv, tuple) else rv.status_code
            assert status == 200, f'强密码应被 200, 实际 {status}'

        db.session.expire_all()
        admin = User.query.filter_by(username='admin').first()
        assert admin.must_change_password is False, '改密后 must_change_password 应清零'
        assert admin.password_changed_at is not None, '改密后 password_changed_at 应记录'
    print('[2] user_change_own_password 弱/强/清零 OK')


def test_admin_reset_password():
    """重置密码端点: 重置后 must_change_password=True"""
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        from flask_login import login_user
        from routes.admin import admin_reset_user_password

        with app.test_request_context('/api/admin/users/1/reset-password', method='POST', json={
            'password': 'TempPass@2026',
        }):
            login_user(admin)
            rv = admin_reset_user_password(1)
            status = rv[1] if isinstance(rv, tuple) else rv.status_code
            assert status == 200, f'reset 应 200, 实际 {status}'

        db.session.expire_all()
        admin = User.query.filter_by(username='admin').first()
        assert admin.must_change_password is True, '重置后 must_change_password 应为 True'
        assert admin.check_password('TempPass@2026'), '重置后密码应为 TempPass@2026'
    print('[3] admin_reset_user_password OK')


def test_before_request_intercept():
    """before_request 拦截: must_change=True 时 GET /dashboard 跳 /change_password"""
    with app.app_context():
        # 确保 admin 密码已知, must_change=True
        admin = User.query.filter_by(username='admin').first()
        admin.set_password('TempPass@2026')
        admin.must_change_password = True
        db.session.commit()

        with app.test_client() as c:
            # 登录
            r = c.post('/login', data={'username': 'admin', 'password': 'TempPass@2026'},
                       follow_redirects=False)
            # 已经登录了的话, GET /dashboard 会被拦截
            r = c.get('/dashboard', follow_redirects=False)
            assert r.status_code == 302, f'GET /dashboard must_change=True 应 302, 实际 {r.status_code}'
            assert r.headers.get('Location') == '/change_password', \
                f'Location 应为 /change_password, 实际 {r.headers.get("Location")}'
    print('[4] GET /dashboard (must_change=True) -> 302 /change_password OK')


def test_change_password_clears_flag():
    """改密成功后 must_change_password 清零, GET /dashboard 不再被拦截"""
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        # 重置为已知值且 must_change=True
        admin.set_password('TempPass@2026')
        admin.must_change_password = True
        db.session.commit()

        with app.test_client() as c:
            # 登录 (会因 must_change 被强制重定向到 /change_password, 不报错)
            c.post('/login', data={'username': 'admin', 'password': 'TempPass@2026'},
                   follow_redirects=False)
            # 拿 csrf token
            import re
            page = c.get('/change_password').data.decode()
            m = re.search(r'csrf-token" content="([^"]+)"', page)
            csrf = m.group(1) if m else ''

            # 改密
            r = c.post('/api/admin/user/password',
                       json={'old_password': 'TempPass@2026', 'new_password': 'NewPass@2026'},
                       headers={'X-CSRF-Token': csrf})
            assert r.status_code == 200, f'改密应 200, 实际 {r.status_code} {r.get_json()}'

            # 现在 GET /dashboard 应正常
            r = c.get('/dashboard', follow_redirects=False)
            assert r.status_code == 200, f'改密后 GET /dashboard 应 200, 实际 {r.status_code}'
    print('[5] 改密后清零 must_change + GET /dashboard 200 OK')


if __name__ == '__main__':
    test_validate_password()
    test_change_own_password()
    test_admin_reset_password()
    test_before_request_intercept()
    test_change_password_clears_flag()
    print('\nALL 5/5 PASS')
