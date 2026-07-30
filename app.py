"""QoR Recorder - Design Compiler 综合质量数据管理系统

应用入口, 使用应用工厂模式初始化 Flask 应用并注册蓝图。

模块结构:
  - core/        核心逻辑 (工厂、数据库配置、安全检查、错误处理)
  - routes/      路由蓝图 (auth, main, review, qor, violations, dashboard, admin, api_v1)
  - services/    业务服务 (数据导入、备份等)
  - models.py    ORM 模型
  - config.py    配置加载
  - security.py  CSRF / 限流 / IP 获取
  - api_auth.py  API Key 认证
  - alerts.py    告警检查
  - qor_parser.py CSV 解析
"""
import os

from config import Config, BASE_DIR
from core.factory import create_app
from models import db, User, Project
from security import is_default_admin_password_weak


# 创建应用实例
app = create_app()


# =========================================================================
# 启动入口
# =========================================================================

def backup_database(db_path, backup_dir='backups', max_backups=10):
    """启动时自动备份 DB 文件, 保留最近 max_backups 份"""
    from services.backup_service import perform_backup
    with app.app_context():
        result = perform_backup(backup_type='auto', user=None)
        if result.get('ok'):
            print(f"[BACKUP] 已备份 DB -> {result['file_path']} ({result['file_size']//1024}KB)")
        else:
            print(f"[BACKUP] 备份失败(不影响启动): {result.get('error')}")


def init_default_data():
    """初始化默认管理员与示例数据"""
    with app.app_context():
        # 紧急重置 admin 密码: 启动时若设置了 EMERGENCY_RESET_ADMIN_PASSWORD=1,
        # 自动生成 16 位强随机密码, 打印到终端, 并标记 must_change_password=True
        # (正常情况下不要使用; 仅用于遗忘 admin 密码时的应急恢复)
        if os.environ.get('EMERGENCY_RESET_ADMIN_PASSWORD') == '1':
            import secrets
            import string
            from datetime import datetime as _dt
            admin = User.query.filter_by(username='admin').first()
            if admin is None:
                admin = User(username='admin', role='admin', display_name='管理员')
                admin.must_change_password = True
                db.session.add(admin)
            alpha = string.ascii_letters + string.digits
            new_pw = ''.join(secrets.choice(alpha) for _ in range(16))
            admin.set_password(new_pw)
            admin.must_change_password = True
            admin.password_changed_at = _dt.utcnow()
            db.session.commit()
            print('=' * 60)
            print('[EMERGENCY] admin 密码已强制重置 (EMERGENCY_RESET_ADMIN_PASSWORD=1)')
            print(f'[EMERGENCY] 新密码: {new_pw}')
            print('[EMERGENCY] 请立即用此密码登录并修改为强密码, 然后取消该环境变量')
            print('=' * 60)
        # 只创建主库表 (__bind_key__ != 'project' 的模型)
        # 项目库表在 create_project_db() 中按需创建
        from models import _collect_master_models
        master_tables = [m.__table__ for m in _collect_master_models()]
        if master_tables:
            db.metadata.create_all(db.engine, tables=master_tables)

        # 初始化默认管理员 (首次登录必须改密)
        if User.query.filter_by(username='admin').first() is None:
            admin = User(username='admin', role='admin', display_name='管理员')
            admin.set_password('admin@2026')
            admin.must_change_password = True
            db.session.add(admin)
        if User.query.filter_by(username='user').first() is None:
            user = User(username='user', role='user', display_name='普通用户')
            user.set_password('user@2026')
            user.must_change_password = True
            db.session.add(user)
        if User.query.filter_by(username='release').first() is None:
            rel = User(username='release', role='release', display_name='Release 客户')
            rel.set_password('release@2026')
            rel.must_change_password = True
            db.session.add(rel)
            print('[INIT] 已创建默认 release 账号: release / release@2026 (仅可查看已发布数据)')
        db.session.commit()

        # 安全检查
        if is_default_admin_password_weak():
            print('=' * 60)
            print('[SECURITY] 警告: admin 账户仍使用出厂默认密码!')
            print('  当前默认: admin@2026 (或历史版本 admin123)')
            print('  请立即登录修改为强密码')
            print('=' * 60)

        # 强制改密兜底: 若任何默认账号仍使用出厂默认密码, 强制标记必须改密
        # (用户通过 user_change_own_password 改密后, 标志会被清零,
        #  不会再次被设回 True)
        _DEFAULT_PASSWORDS = {
            'admin': ['admin@2026', 'admin123'],
            'user':  ['user@2026', 'user123'],
            'release': ['release@2026', 'release123'],
        }
        for uname, default_pws in _DEFAULT_PASSWORDS.items():
            u = User.query.filter_by(username=uname).first()
            if u and any(u.check_password(p) for p in default_pws):
                if not u.must_change_password:
                    u.must_change_password = True
                    print(f'[SECURITY] {uname} 仍使用出厂默认密码, 已标记 must_change_password=True')
        db.session.commit()

        # 按项目分库: 为所有现有项目确保 DB 文件存在
        # (已迁移的项目跳过; 新创建项目已由 admin_create_project 处理)
        try:
            from core.project_db import create_project_db, project_db_path
            for proj in Project.query.filter(Project.status != 'hidden').all():
                if not proj.db_path:
                    proj.db_path = project_db_path(proj.id)
                if not os.path.exists(proj.db_path):
                    create_project_db(proj.id)
            db.session.commit()
        except Exception as e:
            print(f'[INIT] 项目 DB 初始化跳过: {e}')


if __name__ == '__main__':
    db_type = app.config.get('DB_TYPE', 'sqlite')
    sql_uri = app.config['SQLALCHEMY_DATABASE_URI']

    print('=' * 60)
    print(f'[DB] 后端类型: {db_type.upper()}')
    if db_type == 'mongodb':
        print(f'[DB] MongoDB:   {app.config["MONGODB_URI"]}  db={app.config["MONGODB_DB"]}')
        print(f'[DB] Fallback:  {sql_uri}  (只读回退)')
    else:
        # 隐藏密码
        safe_uri = sql_uri
        if '@' in safe_uri:
            safe_uri = safe_uri.split('@', 1)[0] + '@***'
        print(f'[DB] URI:       {safe_uri}')

    # 启动前备份 DB (仅 SQLite)
    if db_type == 'sqlite':
        db_path = os.path.join(BASE_DIR, 'qor_recorder.db')
        backup_database(db_path)
    else:
        print(f'[BACKUP] {db_type} 后端, 跳过本地文件备份 (请确保后端已配置备份策略)')

    # 初始化默认数据
    init_default_data()

    host = app.config.get('HOST', '0.0.0.0')
    port = app.config.get('PORT', 5000)
    debug = app.config.get('DEBUG', False)

    print('=' * 60)
    print('QoR Recorder 系统启动中...')
    print('默认管理员: admin / admin@2026  (首次登录请立即修改)')
    print('默认用户:   user / user@2026')
    print(f'监听地址:   {host}:{port}  (debug={debug})')
    print(f'安全:       SECRET_KEY={"默认值(仅DEBUG)" if app.config.get("SECRET_KEY")==app.config.get("_DEFAULT_SECRET_KEY") else "已配置"}'
          f'  Cookie Secure={app.config.get("SESSION_COOKIE_SECURE")}')
    if host in ('0.0.0.0', '::'):
        print(f'访问地址:   http://localhost:{port}  (或 http://<本机IP>:{port})')
    else:
        print(f'访问地址:   http://{host}:{port}')
    print('=' * 60)

    app.run(host=host, port=port, debug=debug)
