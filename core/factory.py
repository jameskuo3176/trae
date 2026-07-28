"""应用工厂

封装 Flask 应用创建过程, 便于测试和多实例部署。
"""
import os

from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate

from config import Config, BASE_DIR
from models import db, User

from .db import init_db_concurrency, ensure_columns
from .db_routing import setup_binds, register_project_context
from .security import init_security, register_security_before_request
from .errors import register_error_handlers


def create_app(config_class=Config):
    """应用工厂函数

    Returns:
        Flask: 配置完成的 Flask 应用实例
    """
    # 启动前检查 DB 配置 (DB_TYPE=sql 缺 DATABASE_URL 时给出明确错误)
    sql_uri = getattr(config_class, 'SQLALCHEMY_DATABASE_URI', None)
    if not sql_uri:
        db_type = getattr(config_class, 'DB_TYPE', '?')
        print('=' * 60)
        print(f'[BOOT] 数据库配置错误 (DB_TYPE={db_type})')
        if db_type == 'sql':
            print('  DB_TYPE=sql 时必须设置 DATABASE_URL 环境变量')
            print('  示例 (MySQL):       DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/qor_recorder?charset=utf8mb4')
            print('  示例 (PostgreSQL):  DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/qor_recorder')
        print('=' * 60)
        raise SystemExit(1)

    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, 'templates'),
        static_folder=os.path.join(BASE_DIR, 'static'),
    )
    app.config.from_object(config_class)

    # 初始化数据库
    db.init_app(app)
    migrate = Migrate(app, db)

    # 初始化登录管理
    # 注意: /login 路由通过 _register_legacy_endpoints 以 endpoint='login' 注册,
    #       不在 'auth' 蓝图下, 所以 login_view 必须是 'login' 而非 'auth.login'
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = '请先登录'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # 初始化安全模块
    init_security(app)
    register_security_before_request(app)

    # 初始化数据库并发配置 (在 app_context 内)
    with app.app_context():
        init_db_concurrency(app)
        ensure_columns(app)

    # 配置按项目分库路由 (必须在 db.init_app 之后)
    # - setup_binds: ORM 层根据 __bind_key__ 动态选 engine
    # - register_project_context: before_request 从 URL 自动提取 project_id
    setup_binds(app)
    register_project_context(app)

    # 注册错误处理器
    register_error_handlers(app)

    # 注册所有蓝图
    _register_blueprints(app)

    # 确保上传目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    return app


def _register_blueprints(app):
    """注册所有蓝图

    集中管理路由注册, 便于维护。

    关键: 显式指定 endpoint 以保持向后兼容 (避免修改模板中的 url_for)。
    """
    from routes.auth import bp as auth_bp
    from routes.main import bp as main_bp
    from routes.review import bp as review_bp
    from routes.qor import bp as qor_bp
    from routes.violations import bp as violations_bp
    from routes.dashboard import bp as dashboard_bp
    from routes.admin import bp as admin_bp
    from routes.api_v1 import bp as api_v1_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(review_bp, url_prefix='/api/reviews')
    app.register_blueprint(qor_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(api_v1_bp, url_prefix='/api/v1')

    # 注册旧版端点别名, 保持模板中 url_for('dashboard') 等调用兼容
    _register_legacy_endpoints(app)


def _register_legacy_endpoints(app):
    """为已迁移到蓝图的视图注册旧版端点别名, 保持 url_for 兼容

    例如 url_for('dashboard') 仍可工作 (等价于 main.dashboard)。
    """
    from routes.main import dashboard, compare, admin_page, db_admin
    from routes.auth import login, logout

    # 将函数注册到 app 级别, 使用旧版端点名
    app.add_url_rule('/', endpoint='dashboard', view_func=dashboard)
    app.add_url_rule('/dashboard', endpoint='dashboard', view_func=dashboard, methods=['GET'])
    app.add_url_rule('/compare', endpoint='compare', view_func=compare)
    app.add_url_rule('/admin', endpoint='admin_page', view_func=admin_page)
    app.add_url_rule('/dbadmin', endpoint='db_admin', view_func=db_admin, defaults={'subpath': ''})
    app.add_url_rule('/dbadmin/<path:subpath>', endpoint='db_admin', view_func=db_admin)
    app.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    app.add_url_rule('/logout', endpoint='logout', view_func=logout)
