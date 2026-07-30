"""紧急重置任意用户的密码 (常驻工具)

用法:
  python reset_admin_password.py                     # 列出所有用户 (含 id / role / last_login)
  python reset_admin_password.py <username>          # 重置该用户密码为随机值并打印
  python reset_admin_password.py <username> <pw>     # 重置该用户密码为指定值
  python reset_admin_password.py <username> --show   # 仅显示用户当前信息, 不改密码

示例:
  python reset_admin_password.py admin
  python reset_admin_password.py admin Gxx576888

注意:
  - 必须能直接读写 qor_recorder.db, 即与 app 跑在同一台机器
  - 重置后 must_change_password=True 强制下次登录改密
  - 可用于 SQLite / MySQL / PostgreSQL (自动检测后端)
"""
import os
import sys
import secrets
import string
from datetime import datetime

# 让脚本能 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _gen_random_password(n=16):
    """生成 n 位强随机密码"""
    alpha = string.ascii_letters + string.digits
    # 保证至少 1 个字母 + 1 个数字
    body = ''.join(secrets.choice(alpha) for _ in range(n - 2))
    return secrets.choice(string.ascii_letters) + secrets.choice(string.digits) + body


def main():
    # 解析参数
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        return 0

    show_only = False
    if '--show' in args:
        show_only = True
        args.remove('--show')

    if not args:
        print('用法: python reset_admin_password.py [<username> [<new_password>]]')
        return 1

    username = args[0]
    new_password = args[1] if len(args) >= 2 else None

    # 加载 Flask app, 走 ORM (自动支持多种 DB 后端)
    from app import app
    from models import db, User

    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            print(f'[ERR] 用户 "{username}" 不存在')
            print()
            print('--- 现有用户 ---')
            print(f"{'id':>4}  {'username':<20}  {'role':<10}  {'must_change_pw':<14}  {'last_login'}")
            for u in User.query.order_by(User.id).all():
                last = u.last_login_at.strftime('%Y-%m-%d %H:%M') if getattr(u, 'last_login_at', None) else '-'
                mcp = '是' if u.must_change_password else '否'
                print(f"{u.id:>4}  {u.username:<20}  {u.role:<10}  {mcp:<14}  {last}")
            return 1

        if show_only:
            print(f'[INFO] 用户 {username} (id={user.id}, role={user.role}) 当前信息:')
            print(f'  must_change_password: {user.must_change_password}')
            print(f'  last_login_at       : {getattr(user, "last_login_at", None)}')
            return 0

        # 重置密码
        if new_password is None:
            new_password = _gen_random_password(16)
            generated = True
        else:
            generated = False

        # 弱密码检查: 与现有黑名单对比
        weak = {'12345678', 'password', 'password1', 'admin123',
                'qwerty123', '11111111', '00000000', new_password.lower()}
        if new_password.lower() in weak:
            print(f'[WARN] 密码命中黑名单, 仍然设置 (建议改用强密码)')

        user.set_password(new_password)
        user.must_change_password = True  # 强制下次登录改密
        user.password_changed_at = datetime.utcnow()
        db.session.commit()

        print('=' * 60)
        print(f'[OK] 用户 {username} 密码已重置')
        print(f'  新密码    : {new_password}  {"<-- 已生成" if generated else "<-- 来自命令行"}')
        print(f'  role      : {user.role}')
        print(f'  must_change_password: True (下次登录强制改密)')
        print('=' * 60)
        print(f'👉 请立即用 {username} / {new_password} 登录, 并修改为强密码')

    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
