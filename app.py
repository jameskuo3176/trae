"""QoR Recorder - Design Compiler 综合质量数据管理系统

主应用入口，包含所有路由和业务逻辑。

功能:
  1. QoR 数据拉取与项目/模块间对比
  2. ECharts 交互式图表（柱状图、折线图等）
  3. 对比结果导出（Excel / CSV）
  4. 用户自定义 Dashboard 配置
  5. 管理员数据管理权限
"""
import io
import json
import os
import re
import time
from datetime import datetime, timedelta
from functools import wraps

import pandas as pd
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify,
    send_file, flash, abort, Response, g, session
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from flask_migrate import Migrate
from sqlalchemy import event, text

from config import Config, BASE_DIR
from models import (
    db, User, Project, Module, QorRecord, UserDashboard, ViolationPath,
    ApiKey, ProjectMember, DataLock, AlertRule, AlertEvent,
    DataSnapshot, BackupRecord, DEFAULT_THEME, THEME_PRESETS, RunNote,
)
from qor_parser import parse_csv_file, parse_violation_csv, parse_notes_csv
from api_auth import (
    authenticate_request, api_auth_required, require_project_access,
    get_user_project_role, can_access_project, can_edit_project,
    can_manage_project, check_data_lock, filter_projects_by_permission,
    check_project_writable,
)
from alerts import check_alerts_for_new_record

from security import (
    init_csrf, csrf_protect, rate_limit, get_client_ip,
    is_default_admin_password_weak, generate_csrf_token,
)

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
migrate = Migrate(app, db)


# =========================================================================
# 轻量级列迁移: 为已有表补充新增列 (SQLite/MySQL 兼容, 无需 alembic)
# =========================================================================

def _ensure_columns():
    """检查并补充新增列 (用于已存在数据库的平滑升级)

    仅支持新增列 (ADD COLUMN), 不支持改类型/删列。
    新增列必须有默认值或可空, 以兼容旧行。
    """
    # 待补充的列: (表名, 列名, DDL 类型定义)
    new_columns = [
        # QorRecord: release 标记
        ('qor_records', 'is_released', "BOOLEAN DEFAULT 0"),
        ('qor_records', 'released_at', "DATETIME"),
        ('qor_records', 'released_by', "INTEGER"),
        # RunNote: full_dir 字段 (用于区分同 module+version 下不同 run 目录)
        ('run_notes', 'full_dir', "VARCHAR(1000)"),
    ]
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    is_sqlite = uri.startswith('sqlite')
    try:
        for table, col, ddl in new_columns:
            # 检查列是否已存在
            if is_sqlite:
                rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
                existing = {r[1] for r in rows}
            else:
                rows = db.session.execute(text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                ), {'t': table}).fetchall()
                existing = {r[0] for r in rows}
            if col in existing:
                continue
            try:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                db.session.commit()
                print(f"[DB] 已新增列: {table}.{col}")
            except Exception as e:
                db.session.rollback()
                print(f"[DB] 新增列失败 {table}.{col}: {e}")
    except Exception as e:
        print(f"[DB] _ensure_columns 异常: {e}")

    # 创建新表 (run_notes)
    try:
        from models import RunNote
        db.create_all()
    except Exception as e:
        print(f"[DB] create_all 异常: {e}")


# =========================================================================
# 数据库并发优化: SQLite WAL 模式 / MySQL 连接事件
# =========================================================================

def _init_db_concurrency():
    """根据数据库类型初始化并发优化配置"""
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if uri.startswith('sqlite'):
        # SQLite: 启用 WAL 模式
        # WAL 允许并发读不阻塞写、写不阻塞读, 显著缓解 "database is locked" 问题
        @event.listens_for(db.engine, 'connect')
        def _set_sqlite_pragma(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')  # 平衡安全性与性能
            cursor.execute('PRAGMA busy_timeout=30000')  # 30 秒写入等待
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()
        app.logger.info('[DB] SQLite WAL 模式已启用 (并发读不阻塞写)')
    elif uri.startswith('mysql'):
        # MySQL: 设置字符集与隔离级别
        @event.listens_for(db.engine, 'connect')
        def _set_mysql_charset(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET NAMES utf8mb4")
            # 使用 READ COMMITTED 隔离级别, 平衡一致性与并发
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cursor.close()
        app.logger.info('[DB] MySQL 连接池已配置 (pool_size=%d, max_overflow=%d)',
                        app.config['SQLALCHEMY_ENGINE_OPTIONS'].get('pool_size', 5),
                        app.config['SQLALCHEMY_ENGINE_OPTIONS'].get('max_overflow', 10))


def with_db_retry(max_retries=3, base_delay=0.1):
    """数据库写入重试装饰器

    应对 SQLite "database is locked" 和 MySQL "Deadlock found" 等并发冲突。
    指数退避: base_delay * 2^attempt
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    err_str = str(e).lower()
                    # 只对并发冲突类错误重试
                    is_retryable = (
                        'database is locked' in err_str or
                        'deadlock found' in err_str or
                        'lock timeout' in err_str or
                        'could not serialize' in err_str
                    )
                    if not is_retryable or attempt == max_retries - 1:
                        raise
                    last_err = e
                    delay = base_delay * (2 ** attempt)
                    app.logger.warning('[DB] 写入冲突, 第 %d 次重试 (%.2fs): %s',
                                       attempt + 1, delay, err_str)
                    time.sleep(delay)
                    db.session.rollback()
            raise last_err
        return wrapper
    return decorator


# 延迟初始化 (在 app_context 内执行)
with app.app_context():
    _init_db_concurrency()


# =========================================================================
# 安全: SECRET_KEY 启动检查 / CSRF 保护初始化
# =========================================================================

def _check_secret_key():
    """检查 SECRET_KEY 是否仍是默认值 (生产环境拒绝启动)"""
    sk = app.config.get('SECRET_KEY', '')
    default = app.config.get('_DEFAULT_SECRET_KEY', '')
    enforce = app.config.get('ENFORCE_SECRET_KEY', True)
    is_default = (sk == default) or not sk
    if not is_default:
        return
    # DEBUG 模式下允许默认密钥 (本地开发)
    if app.config.get('DEBUG'):
        print('[SECURITY] 警告: SECRET_KEY 仍是默认值, 仅允许 DEBUG 模式使用!')
        return
    if not enforce:
        print('[SECURITY] 警告: SECRET_KEY 仍是默认值 (ENFORCE_SECRET_KEY=0 已关闭强制检查)')
        return
    raise RuntimeError(
        '\n' + '=' * 60 + '\n'
        '[SECURITY] 致命错误: SECRET_KEY 仍是出厂默认值, 拒绝启动!\n'
        '  请设置环境变量 SECRET_KEY 为随机字符串, 例如:\n'
        '    # Linux/Mac\n'
        '    export SECRET_KEY="$(python -c "import secrets; print(secrets.token_hex(32))")"\n'
        '    # Windows PowerShell\n'
        '    $env:SECRET_KEY = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | % {[char]$_})\n'
        '  或在 .env 文件中写入:\n'
        '    SECRET_KEY=<your-random-key>\n'
        '  本地调试可临时关闭:\n'
        '    export ENFORCE_SECRET_KEY=0\n'
        '=' * 60
    )


_check_secret_key()
init_csrf(app)


@app.before_request
def _security_before_request():
    """安全中间件: CSRF 校验 + release 角色只读拦截

    Rate Limiting 通过 @rate_limit 装饰器按端点配置。
    """
    # release 角色: 禁止所有写操作 (POST/PUT/DELETE/PATCH)
    # 仅放行用户级自助功能 (不涉及项目/数据写入):
    #   - change_own_password: 修改自己密码
    #   - save_dashboard_config: 保存自己的 Dashboard 配置
    #   - delete_dashboard_config: 删除自己的 Dashboard 配置
    #   - save_user_theme: 保存自己的主题
    if (current_user.is_authenticated
            and current_user.is_release
            and request.method in ('POST', 'PUT', 'DELETE', 'PATCH')):
        allowed_write_endpoints = {
            'change_own_password',
            'save_dashboard_config',
            'delete_dashboard_config',
            'save_user_theme',
        }
        if request.endpoint not in allowed_write_endpoints:
            app.logger.warning(
                '[AUTH] release 角色尝试写操作被拒: endpoint=%s path=%s ip=%s',
                request.endpoint, request.path, get_client_ip()
            )
            return jsonify({'error': 'release 账号为只读权限, 不允许此操作'}), 403
    return csrf_protect()


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# =========================================================================
# 数据库可视化 (Adminer)
# =========================================================================

# Adminer 单文件 (PHP), 但本系统是 Python, 故采用轻量替代方案:
# 内置一个只读的数据库浏览 API + 模板, 支持:
#   - 查看所有表
#   - 查看表结构
#   - 查看表数据 (分页)
#   - 执行只读 SELECT 查询
# 仅管理员可访问

@app.route('/dbadmin')
@app.route('/dbadmin/<path:subpath>')
@login_required
def db_admin(subpath=''):
    """数据库可视化面板 (仅管理员)"""
    if not current_user.is_admin:
        abort(403)
    if not app.config.get('ENABLE_DB_ADMIN'):
        return render_template('error.html', message='数据库可视化未启用。请设置环境变量 ENABLE_DB_ADMIN=1'), 403

    action = request.args.get('action', 'tables')
    data = {}

    try:
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        is_sqlite = uri.startswith('sqlite')

        def _get_tables():
            """获取所有表名 (兼容 SQLite/MySQL)"""
            if is_sqlite:
                r = db.session.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ))
            else:
                r = db.session.execute(text(
                    "SELECT table_name AS name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() ORDER BY table_name"
                ))
            return [row[0] for row in r]

        def _get_columns(table):
            """获取表结构 (兼容 SQLite/MySQL)"""
            if is_sqlite:
                r = db.session.execute(text(f"PRAGMA table_info({table})"))
                return [{
                    'name': row[1], 'type': row[2], 'notnull': row[3],
                    'default': row[4] if row[4] is not None else '',
                    'pk': row[5] > 0
                } for row in r]
            else:
                r = db.session.execute(text(
                    f"SELECT column_name, data_type, is_nullable, column_default, column_key "
                    f"FROM information_schema.columns WHERE table_schema = DATABASE() "
                    f"AND table_name = '{table}' ORDER BY ordinal_position"
                ))
                return [{
                    'name': row[0], 'type': row[1], 'notnull': row[2] == 'NO',
                    'default': row[3] if row[3] is not None else '',
                    'pk': row[4] == 'PRI'
                } for row in r]

        def _safe_table(table):
            """验证表名安全性"""
            return table and table.replace('_', '').isalnum()

        # 总是获取表列表 (左侧栏需要)
        data['tables'] = _get_tables()

        if action == 'tables':
            data['current_table'] = None

        elif action == 'schema':
            table = request.args.get('table', '')
            data['current_table'] = table
            if not _safe_table(table):
                data['error'] = '无效的表名'
            else:
                data['columns'] = _get_columns(table)
                cnt = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                data['row_count'] = cnt

        elif action == 'browse':
            table = request.args.get('table', '')
            page = max(1, int(request.args.get('page', 1)))
            per_page = 50
            offset = (page - 1) * per_page
            data['current_table'] = table
            if not _safe_table(table):
                data['error'] = '无效的表名'
            else:
                result = db.session.execute(
                    text(f"SELECT * FROM {table} LIMIT :lim OFFSET :off"),
                    {'lim': per_page, 'off': offset}
                )
                rows = result.fetchall()
                data['columns'] = list(result.keys()) if rows else []
                data['rows'] = [list(r) for r in rows]
                cnt = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                data['total'] = cnt
                data['page'] = page
                data['per_page'] = per_page
                data['total_pages'] = (cnt + per_page - 1) // per_page

        elif action == 'query':
            sql = request.args.get('sql', '').strip()
            data['sql'] = sql
            if not sql.lower().startswith('select'):
                data['error'] = '只允许执行 SELECT 查询'
            else:
                try:
                    result = db.session.execute(text(sql))
                    rows = result.fetchall()
                    data['columns'] = list(result.keys()) if rows else []
                    data['rows'] = [list(r) for r in rows[:200]]
                    data['truncated'] = len(rows) > 200
                except Exception as e:
                    data['error'] = str(e)
    except Exception as e:
        data['error'] = str(e)
    finally:
        db.session.close()

    data['action'] = action
    data['db_type'] = 'sqlite' if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite') else 'mysql'
    try:
        return render_template('dbadmin.html', data=data)
    except Exception as e:
        import traceback
        app.logger.error('[db_admin] 模板渲染失败: %s\n%s', e, traceback.format_exc())
        return f'<pre>模板渲染错误: {e}</pre><pre>{traceback.format_exc()}</pre>', 500


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# =========================================================================
# 认证路由
# =========================================================================

@app.route('/login', methods=['GET', 'POST'])
@rate_limit(5, 60)  # 每 IP 每分钟最多 5 次登录尝试 (防暴力破解)
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # 防 session fixation: 登录前清空 session, 重新建立
            session.clear()
            login_user(user)
            # 主动生成新的 CSRF token (供后续 POST 请求使用)
            generate_csrf_token()
            next_url = request.args.get('next')
            return redirect(next_url or url_for('dashboard'))
        app.logger.warning('[AUTH] 登录失败: username=%s ip=%s', username, get_client_ip())
        flash('用户名或密码错误', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# =========================================================================
# 页面路由
# =========================================================================

@app.route('/')
@login_required
def dashboard():
    """主 Dashboard 页面"""
    return render_template('dashboard.html', user=current_user)


@app.route('/compare')
@login_required
def compare():
    """数据对比页面"""
    return render_template('compare.html', user=current_user)


@app.route('/admin')
@login_required
def admin_page():
    """管理员页面"""
    if not current_user.is_admin:
        abort(403)
    return render_template('admin.html', user=current_user)


# =========================================================================
# 数据 API - 项目与模块
# =========================================================================

@app.route('/api/projects')
@login_required
def api_get_projects():
    """获取项目列表"""
    projects = Project.query.order_by(Project.name).all()
    result = []
    for p in projects:
        modules = p.modules.order_by(Module.name).all()
        # release 角色: 隐藏无已发布记录的模块, 且只统计 released 记录数
        if current_user.is_release:
            modules = [m for m in modules
                       if m.records.filter(QorRecord.is_released.is_(True)).count() > 0]
            if not modules:
                continue
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'status': p.status,
            'is_writable': p.is_writable,
            'locked_at': p.locked_at.isoformat() if p.locked_at else None,
            'locked_by_name': p.locker.username if p.locker else None,
            'lock_reason': p.lock_reason,
            'module_count': len(modules),
            'modules': [{
                'id': m.id, 'name': m.name,
                'record_count': m.records.filter(QorRecord.is_released.is_(True)).count()
                                 if current_user.is_release else m.records.count(),
            } for m in modules],
        })
    return jsonify(result)


@app.route('/api/modules/<int:project_id>')
@login_required
def api_get_modules(project_id):
    """获取指定项目的模块列表"""
    project = Project.query.get_or_404(project_id)
    modules = project.modules.order_by(Module.name).all()
    if current_user.is_release:
        modules = [m for m in modules
                   if m.records.filter(QorRecord.is_released.is_(True)).count() > 0]
    return jsonify([{
        'id': m.id,
        'name': m.name,
        'record_count': m.records.filter(QorRecord.is_released.is_(True)).count()
                         if current_user.is_release else m.records.count(),
    } for m in modules])


# =========================================================================
# 数据 API - QoR 数据查询
# =========================================================================

@app.route('/api/qor_data')
@login_required
def api_get_qor_data():
    """查询 QoR 数据

    查询参数:
      project_ids: 逗号分隔的项目 ID
      module_ids: 逗号分隔的模块 ID
      metric: 指标名称（如 area_total, wns_setup 等）
      versions: 版本过滤
    """
    project_ids = request.args.get('project_ids', '')
    module_ids = request.args.get('module_ids', '')
    versions = request.args.get('versions', '')

    query = QorRecord.query.join(Module).join(Project)

    # release 角色: 只能看 is_released=True 的记录
    if current_user.is_release:
        query = query.filter(QorRecord.is_released.is_(True))

    if module_ids:
        mod_id_list = [int(x) for x in module_ids.split(',') if x.strip().isdigit()]
        if mod_id_list:
            query = query.filter(QorRecord.module_id.in_(mod_id_list))
    elif project_ids:
        proj_id_list = [int(x) for x in project_ids.split(',') if x.strip().isdigit()]
        if proj_id_list:
            query = query.filter(Module.project_id.in_(proj_id_list))

    if versions:
        ver_list = [v.strip() for v in versions.split(',') if v.strip()]
        if ver_list:
            query = query.filter(QorRecord.version.in_(ver_list))

    # 按模块、tag 排序，便于图表展示；不限制条数（100+ 模块 × 30-50 版本可能数千条）
    records = query.order_by(QorRecord.recorded_at.desc()).limit(5000).all()
    return jsonify([r.to_dict() for r in records])


@app.route('/api/metrics')
@login_required
def api_get_metrics():
    """返回所有可用的指标列表"""
    metrics = [
        {'key': 'area_total', 'label': '总面积 (um2)', 'group': '面积', 'unit': 'um2'},
        {'key': 'area_combinational', 'label': '组合逻辑面积', 'group': '面积', 'unit': 'um2'},
        {'key': 'area_sequential', 'label': '时序逻辑面积', 'group': '面积', 'unit': 'um2'},
        {'key': 'area_black_box', 'label': '黑盒面积', 'group': '面积', 'unit': 'um2'},
        {'key': 'area_macro', 'label': '宏单元面积', 'group': '面积', 'unit': 'um2'},
        {'key': 'wns_setup', 'label': 'Setup WNS', 'group': '时序', 'unit': 'ns'},
        {'key': 'tns_setup', 'label': 'Setup TNS', 'group': '时序', 'unit': 'ns'},
        {'key': 'nvp_setup', 'label': 'Setup 违例路径数', 'group': '时序', 'unit': ''},
        {'key': 'wns_hold', 'label': 'Hold WNS', 'group': '时序', 'unit': 'ns'},
        {'key': 'tns_hold', 'label': 'Hold TNS', 'group': '时序', 'unit': 'ns'},
        {'key': 'nvp_hold', 'label': 'Hold 违例路径数', 'group': '时序', 'unit': ''},
        {'key': 'power_internal', 'label': '内部功耗', 'group': '功耗', 'unit': 'mW'},
        {'key': 'power_switching', 'label': '翻转功耗', 'group': '功耗', 'unit': 'mW'},
        {'key': 'power_leakage', 'label': '漏电功耗', 'group': '功耗', 'unit': 'mW'},
        {'key': 'power_total', 'label': '总功耗', 'group': '功耗', 'unit': 'mW'},
        {'key': 'cell_count', 'label': '单元数量', 'group': '统计', 'unit': ''},
        {'key': 'instance_count', 'label': '实例数量', 'group': '统计', 'unit': ''},
        {'key': 'net_count', 'label': '网络数量', 'group': '统计', 'unit': ''},
        {'key': 'sequential_cell_count', 'label': '时序单元数', 'group': '统计', 'unit': ''},
        {'key': 'target_frequency', 'label': '目标频率 (MHz)', 'group': '频率', 'unit': 'MHz'},
        {'key': 'achieved_frequency', 'label': '达成频率 (MHz)', 'group': '频率', 'unit': 'MHz'},
    ]
    return jsonify(metrics)


@app.route('/api/versions')
@login_required
def api_get_versions():
    """获取版本(Tag)列表

    查询参数:
      project_ids: 逗号分隔的项目 ID（可选，用于按项目过滤）
      module_ids: 逗号分隔的模块 ID（可选，优先于 project_ids）
    """
    project_ids = request.args.get('project_ids', '')
    module_ids = request.args.get('module_ids', '')

    query = db.session.query(QorRecord.version).join(Module).join(Project)
    if current_user.is_release:
        query = query.filter(QorRecord.is_released.is_(True))
    if module_ids:
        mod_id_list = [int(x) for x in module_ids.split(',') if x.strip().isdigit()]
        if mod_id_list:
            query = query.filter(QorRecord.module_id.in_(mod_id_list))
    elif project_ids:
        proj_id_list = [int(x) for x in project_ids.split(',') if x.strip().isdigit()]
        if proj_id_list:
            query = query.filter(Module.project_id.in_(proj_id_list))

    versions = query.distinct().order_by(QorRecord.version).all()
    return jsonify([v[0] for v in versions if v[0]])


# =========================================================================
# 数据 API - Release 标记管理 (仅 admin)
# =========================================================================

@app.route('/api/admin/qor/<int:record_id>/release', methods=['POST'])
@login_required
def admin_toggle_release(record_id):
    """切换 QoR 记录的 release 状态

    请求体 (可选):
      released: bool - 显式指定目标状态, 默认切换
    返回: {id, is_released, released_at}
    """
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    rec = QorRecord.query.get_or_404(record_id)
    data = request.get_json(silent=True) or {}
    if 'released' in data:
        target = bool(data['released'])
    else:
        target = not bool(rec.is_released)
    if target:
        rec.is_released = True
        rec.released_at = datetime.utcnow()
        rec.released_by = current_user.id
    else:
        rec.is_released = False
        rec.released_at = None
        rec.released_by = None
    db.session.commit()
    return jsonify({
        'id': rec.id,
        'is_released': bool(rec.is_released),
        'released_at': rec.released_at.isoformat() if rec.released_at else None,
    })


@app.route('/api/admin/qor/batch_release', methods=['POST'])
@login_required
def admin_batch_release():
    """批量切换 release 状态

    请求体:
      record_ids: [int] - 记录 ID 列表
      released: bool - 目标状态 (True=发布, False=撤回)
    返回: {updated: n, skipped: [...]}
    """
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}
    ids = data.get('record_ids', [])
    target = bool(data.get('released', True))
    if not isinstance(ids, list) or not ids:
        return jsonify({'error': 'record_ids 必须为非空数组'}), 400
    recs = QorRecord.query.filter(QorRecord.id.in_(ids)).all()
    now = datetime.utcnow()
    for r in recs:
        if target:
            r.is_released = True
            r.released_at = now
            r.released_by = current_user.id
        else:
            r.is_released = False
            r.released_at = None
            r.released_by = None
    db.session.commit()
    return jsonify({'updated': len(recs), 'target': target})


# =========================================================================
# 数据 API - 对比分析
# =========================================================================

@app.route('/api/run_notes')
@login_required
def api_get_run_notes():
    """获取 Run 备注数据

    查询参数:
      record_id: QorRecord ID (可选，优先使用)
      module_id: 单个模块 ID (可选)
      version: 版本号 (可选，与 module_id 组合使用)
      full_dir: Run 目录路径 (可选，与 module_id + version 组合使用，精确匹配)
      project_id: 项目 ID (可选，用于拉取该项目下所有已发布记录的备注)
    """
    record_id = request.args.get('record_id', '')
    module_id = request.args.get('module_id', '')
    version = request.args.get('version', '')
    full_dir = request.args.get('full_dir', '').strip()
    project_id = request.args.get('project_id', '')

    query = RunNote.query.join(QorRecord).join(Module).join(Project)

    # release 角色: 只能看已发布记录的备注
    if current_user.is_release:
        query = query.filter(QorRecord.is_released.is_(True))

    if record_id and record_id.isdigit():
        query = query.filter(RunNote.qor_record_id == int(record_id))
    elif module_id and module_id.isdigit():
        query = query.filter(QorRecord.module_id == int(module_id))
        if version:
            query = query.filter(QorRecord.version == version)
    elif project_id and project_id.isdigit():
        query = query.filter(Module.project_id == int(project_id))

    # full_dir 精确过滤 (为空时不过滤, 返回该 module+version 下全部备注)
    if full_dir:
        query = query.filter(RunNote.full_dir == full_dir)

    notes = query.order_by(RunNote.qor_record_id, RunNote.seq).all()
    return jsonify([n.to_dict() for n in notes])


@app.route('/api/violations')
@login_required
def api_get_violations():
    """获取违例路径数据

    查询参数:
      record_id: QorRecord ID (可选，优先使用)
      module_id: 单个模块 ID (可选，用于单 run 单 CSV 模式)
      module_ids: 逗号分隔的模块 ID (可选，兼容旧版)
      version: 单个版本 (可选，用于单 run 模式)
      versions: 逗号分隔的版本 (可选)
      timing_group: 过滤 timing group (可选)
      source_file: 过滤源 CSV 文件 (可选)
      limit: 返回条数限制 (默认 500，最大 2000)
      sort_by: 排序字段 (默认 slack)
      sort_order: asc / desc (默认 asc, slack 从小到大=最差优先)
      bus_grouping: 1/0 是否启用 bus 合并 (默认 1)
    """
    record_id = request.args.get('record_id', '')
    module_id = request.args.get('module_id', '')
    module_ids = request.args.get('module_ids', '')
    version = request.args.get('version', '')
    versions = request.args.get('versions', '')
    timing_group = request.args.get('timing_group', '')
    source_file = request.args.get('source_file', '')
    limit = min(int(request.args.get('limit', 500)), 2000)
    sort_by = request.args.get('sort_by', 'slack')
    sort_order = request.args.get('sort_order', 'asc')
    bus_grouping = request.args.get('bus_grouping', '1') == '1'

    query = ViolationPath.query.join(QorRecord).join(Module)

    if record_id:
        rid_list = [int(x) for x in record_id.split(',') if x.strip().isdigit()]
        if rid_list:
            query = query.filter(ViolationPath.qor_record_id.in_(rid_list))
    else:
        # 模块过滤: 优先 module_id (单选), 其次 module_ids (多选)
        if module_id and module_id.strip().isdigit():
            query = query.filter(QorRecord.module_id == int(module_id))
        elif module_ids:
            mod_id_list = [int(x) for x in module_ids.split(',') if x.strip().isdigit()]
            if mod_id_list:
                query = query.filter(QorRecord.module_id.in_(mod_id_list))
        # 版本过滤: 优先 version (单选), 其次 versions (多选)
        if version:
            query = query.filter(QorRecord.version == version)
        elif versions:
            ver_list = [v.strip() for v in versions.split(',') if v.strip()]
            if ver_list:
                query = query.filter(QorRecord.version.in_(ver_list))

    if timing_group:
        query = query.filter(ViolationPath.timing_group == timing_group)

    if source_file:
        query = query.filter(ViolationPath.source_file == source_file)

    # 排序
    sort_column = getattr(ViolationPath, sort_by, ViolationPath.slack)
    if sort_order == 'desc':
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    total = query.count()

    # Bus 合并时先取更多数据以保证分组后仍有足够条数
    if bus_grouping:
        fetch_limit = min(total, max(limit * 20, 2000))
    else:
        fetch_limit = limit

    paths = query.limit(fetch_limit).all()
    path_dicts = [p.to_dict() for p in paths]

    # Bus 合并: ENDPOINT 只有末尾 _number_ 不同的视为一组，只保留第一条
    if bus_grouping and path_dicts:
        path_dicts = _group_bus_endpoints(path_dicts)
        # 合并后再截断到 limit
        path_dicts = path_dicts[:limit]

    return jsonify({
        'paths': path_dicts,
        'total': total,
        'returned': len(path_dicts),
        'limit': limit,
        'bus_grouping': bus_grouping,
    })


def _group_bus_endpoints(paths):
    """将 ENDPOINT 只有末尾 _number_ 不同的路径合并为一条

    示例: data_out_0_/D, data_out_1_/D, data_out_2_/D -> 保留 data_out_0_/D, vio_number=3
    """
    import re
    grouped = []  # [{path, vio_number, bus_key}]
    bus_map = {}  # bus_key -> index in grouped

    # 匹配末尾的 _数字_ 或 _数字/ 模式
    bus_pattern = re.compile(r'^(.+?)_(\d+)(_\w*)?$')

    for p in paths:
        ep = p.get('endpoint') or ''
        # 尝试提取 bus 前缀
        # 常见格式: name_0_/D, name_12_/D, name_0_reg/D
        m = re.match(r'^(.+?)(?:_)(\d+)(?=[/_]|$)(.*)$', ep)
        if m:
            prefix = m.group(1)
            suffix = m.group(3)  # /D 等后缀
            bus_key = f"{prefix}__BUS__{suffix}"
        else:
            bus_key = ep  # 无法分组，独立

        if bus_key in bus_map:
            idx = bus_map[bus_key]
            grouped[idx]['vio_number'] += 1
        else:
            bus_map[bus_key] = len(grouped)
            new_p = dict(p)
            new_p['vio_number'] = 1
            grouped.append(new_p)

    return grouped


@app.route('/api/violations/source_files')
@login_required
def api_get_violation_source_files():
    """获取违例路径的源 CSV 文件列表（按模块+版本+timing_group 过滤）

    返回格式: [{"name": "xxx.csv", "count": 123}, ...]
    自动过滤 count=0 的项, 按 count 倒序排列
    """
    module_id = request.args.get('module_id', '')
    version = request.args.get('version', '')
    timing_group = request.args.get('timing_group', '')

    query = db.session.query(
        ViolationPath.source_file,
        db.func.count(ViolationPath.id)
    ).join(QorRecord)
    if module_id and module_id.strip().isdigit():
        query = query.filter(QorRecord.module_id == int(module_id))
    if version:
        query = query.filter(QorRecord.version == version)
    if timing_group:
        query = query.filter(ViolationPath.timing_group == timing_group)

    query = query.group_by(ViolationPath.source_file)
    rows = query.all()
    # 过滤空名 + 按条数倒序
    result = [{'name': f, 'count': c} for f, c in rows if f]
    result.sort(key=lambda x: -x['count'])
    return jsonify(result)


@app.route('/api/violations/diff')
@login_required
def api_violations_diff():
    """对比同一模块不同 run 的相同 timing group 违例差异

    查询参数:
      module_id: 模块 ID
      timing_group: timing group 名称
      version_a: 版本 A
      version_b: 版本 B
      bus_grouping: 1/0
    """
    module_id = request.args.get('module_id', '')
    timing_group = request.args.get('timing_group', '')
    version_a = request.args.get('version_a', '')
    version_b = request.args.get('version_b', '')
    bus_grouping = request.args.get('bus_grouping', '1') == '1'

    if not module_id or not version_a or not version_b:
        return jsonify({'error': '请提供 module_id, version_a, version_b'}), 400

    mod = Module.query.get(int(module_id))
    if not mod:
        return jsonify({'error': '模块不存在'}), 404

    rec_a = QorRecord.query.filter_by(module_id=mod.id, version=version_a).first()
    rec_b = QorRecord.query.filter_by(module_id=mod.id, version=version_b).first()

    result = {
        'module_name': mod.name,
        'version_a': version_a,
        'version_b': version_b,
        'timing_group': timing_group,
        'record_a_exists': rec_a is not None,
        'record_b_exists': rec_b is not None,
        'summary': {},
        'paths': [],
    }

    if not rec_a and not rec_b:
        return jsonify(result)

    # 查询两版本的违例路径
    q_a = ViolationPath.query.filter_by(qor_record_id=rec_a.id) if rec_a else None
    q_b = ViolationPath.query.filter_by(qor_record_id=rec_b.id) if rec_b else None

    if timing_group:
        if q_a: q_a = q_a.filter(ViolationPath.timing_group == timing_group)
        if q_b: q_b = q_b.filter(ViolationPath.timing_group == timing_group)

    paths_a = q_a.order_by(ViolationPath.slack.asc()).all() if q_a else []
    paths_b = q_b.order_by(ViolationPath.slack.asc()).all() if q_b else []

    # 汇总统计
    def summarize(paths, label):
        if not paths:
            return {'label': label, 'count': 0, 'worst_slack': None, 'avg_slack': None}
        slacks = [p.slack for p in paths if p.slack is not None]
        return {
            'label': label,
            'count': len(paths),
            'worst_slack': round(min(slacks), 3) if slacks else None,
            'avg_slack': round(sum(slacks) / len(slacks), 3) if slacks else None,
        }

    result['summary']['version_a'] = summarize(paths_a, version_a)
    result['summary']['version_b'] = summarize(paths_b, version_b)

    # 按端点匹配，计算 slack 变化
    dict_a = {}
    for p in paths_a:
        key = (p.startpoint or '', p.endpoint or '')
        dict_a[key] = p

    dict_b = {}
    for p in paths_b:
        key = (p.startpoint or '', p.endpoint or '')
        dict_b[key] = p

    all_keys = set(dict_a.keys()) | set(dict_b.keys())

    diff_paths = []
    for key in all_keys:
        pa = dict_a.get(key)
        pb = dict_b.get(key)
        slack_a = pa.slack if pa and pa.slack is not None else None
        slack_b = pb.slack if pb and pb.slack is not None else None

        delta = None
        if slack_a is not None and slack_b is not None:
            delta = round(slack_b - slack_a, 3)  # 正数=变好(slack增大), 负数=变差

        status = 'both'
        if pa and not pb:
            status = 'removed'  # B 版本中已修复
        elif pb and not pa:
            status = 'new'  # B 版本中新增

        diff_paths.append({
            'startpoint': key[0],
            'endpoint': key[1],
            'timing_group': (pa or pb).timing_group,
            'slack_a': round(slack_a, 3) if slack_a is not None else None,
            'slack_b': round(slack_b, 3) if slack_b is not None else None,
            'delta': delta,
            'status': status,
            'depth_a': pa.depth if pa else None,
            'depth_b': pb.depth if pb else None,
            'cell_delay_a': round(pa.cell_delay, 1) if pa and pa.cell_delay is not None else None,
            'cell_delay_b': round(pb.cell_delay, 1) if pb and pb.cell_delay is not None else None,
            'net_delay_a': round(pa.net_delay, 1) if pa and pa.net_delay is not None else None,
            'net_delay_b': round(pb.net_delay, 1) if pb and pb.net_delay is not None else None,
        })

    # 按 delta 排序: 变差最多的在前
    diff_paths.sort(key=lambda x: (x['delta'] if x['delta'] is not None else -999))

    if bus_grouping:
        diff_paths = _group_bus_diff(diff_paths)

    result['paths'] = diff_paths
    result['summary']['improved'] = sum(1 for p in diff_paths if p.get('delta') is not None and p['delta'] > 0)
    result['summary']['worsened'] = sum(1 for p in diff_paths if p.get('delta') is not None and p['delta'] < 0)
    result['summary']['fixed'] = sum(1 for p in diff_paths if p.get('status') == 'removed')
    result['summary']['new'] = sum(1 for p in diff_paths if p.get('status') == 'new')

    return jsonify(result)


def _group_bus_diff(paths):
    """diff 结果的 bus 合并"""
    import re
    grouped = []
    bus_map = {}

    for p in paths:
        ep = p.get('endpoint') or ''
        m = re.match(r'^(.+?)(?:_)(\d+)(?=[/_]|$)(.*)$', ep)
        if m:
            prefix = m.group(1)
            suffix = m.group(3)
            bus_key = f"{prefix}__BUS__{suffix}"
        else:
            bus_key = ep

        if bus_key in bus_map:
            idx = bus_map[bus_key]
            grouped[idx]['vio_number'] += 1
        else:
            bus_map[bus_key] = len(grouped)
            new_p = dict(p)
            new_p['vio_number'] = 1
            grouped.append(new_p)

    return grouped


@app.route('/api/violations/timing_groups')
@login_required
def api_get_timing_groups():
    """获取所有 timing group 列表（可选按模块/版本过滤）

    返回格式: [{"name": "SRAMCLK", "count": 123}, ...]
    自动过滤 count=0 的项, 按 count 倒序排列, 方便前端只显示非空 group
    """
    module_ids = request.args.get('module_ids', '')
    versions = request.args.get('versions', '')

    query = db.session.query(
        ViolationPath.timing_group,
        db.func.count(ViolationPath.id)
    ).join(QorRecord).join(Module)
    if module_ids:
        mod_id_list = [int(x) for x in module_ids.split(',') if x.strip().isdigit()]
        if mod_id_list:
            query = query.filter(QorRecord.module_id.in_(mod_id_list))
    if versions:
        ver_list = [v.strip() for v in versions.split(',') if v.strip()]
        if ver_list:
            query = query.filter(QorRecord.version.in_(ver_list))

    query = query.group_by(ViolationPath.timing_group)
    rows = query.all()
    # 过滤空名 + 按条数倒序
    result = [{'name': g, 'count': c} for g, c in rows if g]
    result.sort(key=lambda x: -x['count'])
    return jsonify(result)


@app.route('/api/violations/summary')
@login_required
def api_get_violation_summary():
    """获取违例路径按 module/version 聚合的统计

    返回格式:
    {
      "modules": [
        {"module_id": 1, "module_name": "cpu_top", "count": 123},
        ...
      ],
      "versions_by_module": {
        "1": [  // key = module_id
          {"version": "v1", "count": 50},
          {"version": "v2", "count": 73},
          ...
        ],
        ...
      }
    }

    用途:
      - 前端用 modules 列表过滤掉 count=0 的 module
      - 选中 module 后用 versions_by_module[modId] 过滤掉空版本
    """
    # 按 module 聚合
    mod_query = db.session.query(
        Module.id,
        Module.name,
        db.func.count(ViolationPath.id)
    ).join(QorRecord, QorRecord.module_id == Module.id) \
     .join(ViolationPath, ViolationPath.qor_record_id == QorRecord.id) \
     .group_by(Module.id, Module.name)
    mod_rows = mod_query.all()
    modules = [{'module_id': mid, 'module_name': mname, 'count': cnt}
               for mid, mname, cnt in mod_rows]
    modules.sort(key=lambda x: -x['count'])

    # 按 (module_id, version) 聚合
    ver_query = db.session.query(
        QorRecord.module_id,
        QorRecord.version,
        db.func.count(ViolationPath.id)
    ).join(ViolationPath, ViolationPath.qor_record_id == QorRecord.id) \
     .group_by(QorRecord.module_id, QorRecord.version)
    ver_rows = ver_query.all()
    versions_by_module = {}
    for mid, ver, cnt in ver_rows:
        versions_by_module.setdefault(str(mid), []).append({'version': ver, 'count': cnt})
    # 每个模块下版本按 count 倒序
    for k in versions_by_module:
        versions_by_module[k].sort(key=lambda x: -x['count'])

    return jsonify({
        'modules': modules,
        'versions_by_module': versions_by_module
    })


@app.route('/api/compare')
@login_required
def api_compare():
    """对比分析数据

    查询参数:
      module_ids: 逗号分隔的模块 ID
      metrics: 逗号分隔的指标名称
      versions: 版本过滤
    """
    module_ids = request.args.get('module_ids', '')
    metrics = request.args.get('metrics', 'area_total,wns_setup,power_total')
    versions = request.args.get('versions', '')

    if not module_ids:
        return jsonify({'error': '请选择至少一个模块'}), 400

    mod_id_list = [int(x) for x in module_ids.split(',') if x.strip().isdigit()]
    metric_list = [m.strip() for m in metrics.split(',') if m.strip()]

    query = QorRecord.query.filter(QorRecord.module_id.in_(mod_id_list))
    if versions:
        ver_list = [v.strip() for v in versions.split(',') if v.strip()]
        if ver_list:
            query = query.filter(QorRecord.version.in_(ver_list))

    records = query.order_by(QorRecord.module_id, QorRecord.recorded_at).all()

    # 组织数据: 按模块分组
    result = {
        'metrics': metric_list,
        'series': [],
        'categories': [],
    }

    module_names = {}
    all_versions = set()

    for r in records:
        mod_name = r.module.name if r.module else f'模块{r.module_id}'
        proj_name = r.module.project.name if r.module and r.module.project else ''
        label = f'{proj_name}/{mod_name}' if proj_name else mod_name

        module_names[r.module_id] = label
        all_versions.add(r.version or 'v1')

    result['categories'] = sorted(all_versions)

    for metric in metric_list:
        series_data = []
        for mod_id in mod_id_list:
            mod_records = [r for r in records if r.module_id == mod_id]
            data_points = []
            for ver in result['categories']:
                val = None
                for r in mod_records:
                    if (r.version or 'v1') == ver:
                        val = getattr(r, metric, None)
                        break
                data_points.append(val)
            series_data.append({
                'name': module_names.get(mod_id, f'模块{mod_id}'),
                'data': data_points,
            })
        result['series'].append({
            'metric': metric,
            'categories': result['categories'],
            'series': series_data,
        })

    return jsonify(result)


# =========================================================================
# 导出功能
# =========================================================================

@app.route('/export')
@login_required
def export_data():
    """导出对比结果

    查询参数:
      module_ids: 逗号分隔的模块 ID
      metrics: 逗号分隔的指标名称
      versions: 版本过滤
      format: 导出格式 (excel / csv)
    """
    module_ids = request.args.get('module_ids', '')
    metrics = request.args.get('metrics', 'area_total,wns_setup,power_total')
    versions = request.args.get('versions', '')
    fmt = request.args.get('format', 'excel')

    if not module_ids:
        return jsonify({'error': '请选择至少一个模块'}), 400

    mod_id_list = [int(x) for x in module_ids.split(',') if x.strip().isdigit()]
    metric_list = [m.strip() for m in metrics.split(',') if m.strip()]

    query = QorRecord.query.filter(QorRecord.module_id.in_(mod_id_list))
    if versions:
        ver_list = [v.strip() for v in versions.split(',') if v.strip()]
        if ver_list:
            query = query.filter(QorRecord.version.in_(ver_list))

    records = query.order_by(QorRecord.module_id, QorRecord.recorded_at).all()

    # 构建 DataFrame
    rows = []
    for r in records:
        row = {
            '项目': r.module.project.name if r.module and r.module.project else '',
            '模块': r.module.name if r.module else '',
            '版本': r.version,
            '记录时间': r.recorded_at.strftime('%Y-%m-%d %H:%M:%S') if r.recorded_at else '',
        }
        for metric in metric_list:
            row[metric] = getattr(r, metric, None)
        rows.append(row)

    df = pd.DataFrame(rows)

    output = io.BytesIO()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if fmt == 'csv':
        csv_data = df.to_csv(index=False)
        output.write(csv_data.encode('utf-8-sig'))
        output.seek(0)
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'qor_export_{timestamp}.csv'
        )
    else:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='QoR对比', index=False)
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'qor_export_{timestamp}.xlsx'
        )


# =========================================================================
# 用户 Dashboard 配置
# =========================================================================

@app.route('/api/dashboard/save', methods=['POST'])
@login_required
@with_db_retry()
def save_dashboard_config():
    """保存用户 Dashboard 配置"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '无效的数据'}), 400

    name = data.get('name', '').strip()
    config = data.get('config')
    is_default = data.get('is_default', False)

    if not name:
        return jsonify({'error': '请输入配置名称'}), 400
    if config is None:
        return jsonify({'error': '缺少配置内容'}), 400

    dash_id = data.get('id')

    if dash_id:
        # 更新现有配置
        dash = UserDashboard.query.filter_by(id=dash_id, user_id=current_user.id).first()
        if not dash:
            return jsonify({'error': '配置不存在'}), 404
        dash.name = name
        dash.config = json.dumps(config, ensure_ascii=False)
        dash.is_default = is_default
    else:
        # 新建配置
        dash = UserDashboard(
            user_id=current_user.id,
            name=name,
            config=json.dumps(config, ensure_ascii=False),
            is_default=is_default,
        )
        db.session.add(dash)

    if is_default:
        # 取消其他默认配置
        UserDashboard.query.filter(
            UserDashboard.user_id == current_user.id,
            UserDashboard.id != dash.id if dash_id else UserDashboard.id.isnot(None)
        ).update({'is_default': False})

    db.session.commit()
    return jsonify({'id': dash.id, 'name': dash.name, 'is_default': dash.is_default})


@app.route('/api/dashboard/list')
@login_required
def list_dashboard_configs():
    """获取当前用户的 Dashboard 配置列表"""
    configs = current_user.dashboards.order_by(UserDashboard.updated_at.desc()).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'is_default': c.is_default,
        'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M') if c.updated_at else '',
    } for c in configs])


@app.route('/api/dashboard/<int:dash_id>')
@login_required
def get_dashboard_config(dash_id):
    """获取指定 Dashboard 配置详情"""
    dash = UserDashboard.query.filter_by(id=dash_id, user_id=current_user.id).first_or_404()
    return jsonify({
        'id': dash.id,
        'name': dash.name,
        'is_default': dash.is_default,
        'config': json.loads(dash.config),
    })


@app.route('/api/dashboard/<int:dash_id>', methods=['DELETE'])
@login_required
def delete_dashboard_config(dash_id):
    """删除 Dashboard 配置"""
    dash = UserDashboard.query.filter_by(id=dash_id, user_id=current_user.id).first_or_404()
    db.session.delete(dash)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# 用户主题
# =========================================================================

# 允许在主题 JSON 中保存的字段及其类型校验
_THEME_FIELDS = {
    'name': str,
    'primary': str,
    'primary_gradient_end': str,
    'background': str,
    'surface': str,
    'surface_hover': str,
    'text': str,
    'text_secondary': str,
    'border': str,
    'navbar_text': str,
    'navbar_text_active': str,
}

# 颜色字段 (粗略校验: #hex / rgb()/rgba()/hsl())
_COLOR_RE = re.compile(r'^(#[0-9a-fA-F]{3,8}|rgb\(.+\)|rgba\(.+\)|hsl\(.+\)|hsla\(.+\))$')


def _validate_theme(data):
    """校验并清洗主题数据, 返回 (theme_dict, error_message)"""
    if not isinstance(data, dict):
        return None, '主题数据必须为对象'
    cleaned = {}
    for key, expected_type in _THEME_FIELDS.items():
        if key not in data:
            continue
        val = data[key]
        if not isinstance(val, expected_type):
            return None, f'字段 {key} 类型错误'
        if key != 'name':
            # 颜色字段校验
            if not _COLOR_RE.match(val.strip()):
                return None, f'字段 {key} 不是合法颜色值: {val}'
        cleaned[key] = val.strip() if isinstance(val, str) else val
    # name 字段若为空, 用 'custom'
    if not cleaned.get('name'):
        cleaned['name'] = 'custom'
    return cleaned, None


@app.route('/api/user/theme')
@login_required
def get_user_theme():
    """获取当前用户的主题"""
    return jsonify({
        'theme': current_user.get_theme(),
        'presets': THEME_PRESETS,
        'default': DEFAULT_THEME,
    })


@app.route('/api/user/theme', methods=['POST'])
@login_required
@with_db_retry()
def save_user_theme():
    """保存当前用户的自定义主题

    请求体:
      - {preset: 'classic'}: 应用预设主题
      - {theme: {...}}: 保存自定义主题 (字段经校验)
      - {reset: true}: 重置为默认主题
    """
    data = request.get_json() or {}

    # 重置
    if data.get('reset'):
        current_user.theme = None
        db.session.commit()
        return jsonify({'ok': True, 'theme': current_user.get_theme()})

    # 应用预设
    preset_name = data.get('preset')
    if preset_name:
        if preset_name not in THEME_PRESETS:
            return jsonify({'error': f'未知预设: {preset_name}'}), 400
        current_user.set_theme(dict(THEME_PRESETS[preset_name]))
        db.session.commit()
        return jsonify({'ok': True, 'theme': current_user.get_theme()})

    # 自定义主题
    theme_data = data.get('theme')
    if theme_data is None:
        return jsonify({'error': '缺少 theme 字段或 preset/reset 参数'}), 400

    cleaned, err = _validate_theme(theme_data)
    if err:
        return jsonify({'error': err}), 400

    current_user.set_theme(cleaned)
    db.session.commit()
    return jsonify({'ok': True, 'theme': current_user.get_theme()})


# =========================================================================
# 管理员 API - 数据管理
# =========================================================================

@app.route('/api/admin/projects', methods=['POST'])
@login_required
@with_db_retry()
def admin_create_project():
    """创建项目"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '项目名称不能为空'}), 400
    if Project.query.filter_by(name=name).first():
        return jsonify({'error': '项目已存在'}), 400
    p = Project(name=name, description=data.get('description', ''))
    db.session.add(p)
    db.session.commit()
    return jsonify({'id': p.id, 'name': p.name})


@app.route('/api/admin/projects/<int:project_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_project(project_id):
    """删除项目"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    p = Project.query.get_or_404(project_id)
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# 项目状态管理 - 锁定 / 解锁 / 归档
# =========================================================================

@app.route('/api/admin/projects/<int:project_id>/lock', methods=['POST'])
@login_required
@with_db_retry()
def admin_lock_project(project_id):
    """锁定项目, 禁止所有数据写入

    Body:
      reason: 锁定原因 (可选)
      status: 目标状态, 默认 'locked', 可指定 'archived'
    """
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    p = Project.query.get_or_404(project_id)
    if p.status == 'archived':
        return jsonify({'error': '项目已归档, 请先解除归档'}), 400

    data = request.get_json() or request.form or {}
    target_status = data.get('status', 'locked')
    if target_status not in ('locked', 'archived'):
        return jsonify({'error': '无效的目标状态, 必须是 locked 或 archived'}), 400

    p.status = target_status
    p.locked_at = datetime.utcnow()
    p.locked_by = current_user.id
    p.lock_reason = data.get('reason', '')
    db.session.commit()
    return jsonify(p.to_dict())


@app.route('/api/admin/projects/<int:project_id>/unlock', methods=['POST'])
@login_required
@with_db_retry()
def admin_unlock_project(project_id):
    """解除项目锁定, 恢复为 active"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    p = Project.query.get_or_404(project_id)
    if p.status == 'active':
        return jsonify({'error': '项目未锁定'}), 400

    p.status = 'active'
    p.locked_at = None
    p.locked_by = None
    p.lock_reason = None
    db.session.commit()
    return jsonify(p.to_dict())


# =========================================================================
# 数据快照与回滚
# =========================================================================

@app.route('/api/admin/projects/<int:project_id>/snapshots', methods=['POST'])
@login_required
@with_db_retry()
def admin_create_snapshot(project_id):
    """创建项目数据快照 (关键节点)

    Body:
      name: 快照名称 (必填)
      description: 说明 (可选)
      snapshot_type: milestone / tapeout / pre_release / custom (默认 milestone)
    """
    # 项目级权限: admin / owner / editor 可创建快照
    if not can_edit_project(current_user, project_id):
        return jsonify({'error': '无权限创建此项目的快照 (需要 editor 及以上角色)'}), 403
    p = Project.query.get_or_404(project_id)
    data = request.get_json() or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '快照名称不能为空'}), 400

    # 收集该项目的所有记录 (与 to_dict 字段一致)
    records = QorRecord.query.join(Module).filter(Module.project_id == project_id).all()
    snapshot_data = [r.to_dict() for r in records]
    data_json = json.dumps(snapshot_data, ensure_ascii=False, default=str)

    snap = DataSnapshot(
        project_id=project_id,
        name=name,
        description=data.get('description', ''),
        snapshot_type=data.get('snapshot_type', 'milestone'),
        data=data_json,
        record_count=len(snapshot_data),
        checksum=DataSnapshot.compute_checksum(data_json),
        created_by=current_user.id,
    )
    db.session.add(snap)
    db.session.commit()
    return jsonify(snap.to_dict())


@app.route('/api/admin/projects/<int:project_id>/snapshots')
@login_required
def admin_list_snapshots(project_id):
    """列出项目的所有快照"""
    # 项目级权限: viewer 以上可查看
    if not can_access_project(current_user, project_id):
        return jsonify({'error': '无权限查看此项目的快照'}), 403
    Project.query.get_or_404(project_id)
    snaps = DataSnapshot.query.filter_by(project_id=project_id).order_by(DataSnapshot.created_at.desc()).all()
    return jsonify([s.to_dict() for s in snaps])


@app.route('/api/admin/snapshots/<int:snap_id>')
@login_required
def admin_get_snapshot(snap_id):
    """获取快照详情 (含完整数据)"""
    snap = DataSnapshot.query.get_or_404(snap_id)
    # 项目级权限: viewer 以上可查看
    if not can_access_project(current_user, snap.project_id):
        return jsonify({'error': '无权限查看此快照'}), 403
    if not snap.verify_integrity():
        return jsonify({'error': '快照数据校验失败, 可能已被篡改', 'verified': False}), 500
    return jsonify(snap.to_dict(include_data=True))


@app.route('/api/admin/snapshots/<int:snap_id>/verify', methods=['POST'])
@login_required
def admin_verify_snapshot(snap_id):
    """校验快照完整性"""
    snap = DataSnapshot.query.get_or_404(snap_id)
    ok = snap.verify_integrity()
    return jsonify({'id': snap_id, 'verified': ok, 'checksum': snap.prefix_checksum})


@app.route('/api/admin/snapshots/<int:snap_id>/rollback', methods=['POST'])
@login_required
@with_db_retry()
def admin_rollback_snapshot(snap_id):
    """回滚项目到指定快照状态 (危险操作)

    流程:
      1. 自动创建当前状态的快照 (pre_rollback) 以便撤销
      2. 删除当前所有 QorRecord (该项目下)
      3. 恢复快照中的数据
    """
    snap = DataSnapshot.query.get(snap_id)
    if snap is None:
        # 不存在时返回 404 (无权用户也返回 404, 避免泄露存在性)
        if current_user.is_admin:
            return jsonify({'error': '快照不存在'}), 404
        return jsonify({'error': '快照不存在'}), 404
    # 项目级权限: admin / owner 才能回滚 (危险操作)
    if not can_manage_project(current_user, snap.project_id):
        return jsonify({'error': '无权限回滚此项目 (需要 owner 及以上角色)'}), 403
    if not snap.verify_integrity():
        return jsonify({'error': '快照数据校验失败, 拒绝回滚'}), 500

    # 项目必须可写
    writable, err = check_project_writable(snap.project_id)
    if not writable:
        return jsonify({'error': f'项目当前不可写: {err}'}), 403

    try:
        snapshot_data = json.loads(snap.data)
    except (json.JSONDecodeError, TypeError):
        return jsonify({'error': '快照数据解析失败'}), 500

    project = Project.query.get_or_404(snap.project_id)

    # 1. 创建 pre_rollback 快照
    current_records = QorRecord.query.join(Module).filter(Module.project_id == snap.project_id).all()
    current_data = [r.to_dict() for r in current_records]
    current_json = json.dumps(current_data, ensure_ascii=False, default=str)
    pre_snap = DataSnapshot(
        project_id=snap.project_id,
        name=f'[Auto] Before rollback to "{snap.name}"',
        description=f'自动创建于回滚操作, 由 {current_user.username} 触发',
        snapshot_type='custom',
        data=current_json,
        record_count=len(current_data),
        checksum=DataSnapshot.compute_checksum(current_json),
        created_by=current_user.id,
    )
    db.session.add(pre_snap)

    # 2. 记录 module_id 映射 (按名称) 用于恢复
    module_map = {m.name: m.id for m in project.modules.all()}

    # 3. 删除现有记录
    for r in current_records:
        db.session.delete(r)
    db.session.flush()

    # 4. 恢复快照数据
    restored = 0
    skipped = 0
    for item in snapshot_data:
        module_name = item.get('module_name')
        if not module_name or module_name not in module_map:
            skipped += 1
            continue
        rec = QorRecord(
            module_id=module_map[module_name],
            version=item.get('version', 'v1'),
            area_total=item.get('area_total'),
            area_combinational=item.get('area_combinational'),
            area_sequential=item.get('area_sequential'),
            area_black_box=item.get('area_black_box'),
            area_macro=item.get('area_macro'),
            wns_setup=item.get('wns_setup'),
            tns_setup=item.get('tns_setup'),
            nvp_setup=item.get('nvp_setup'),
            wns_hold=item.get('wns_hold'),
            tns_hold=item.get('tns_hold'),
            nvp_hold=item.get('nvp_hold'),
            power_internal=item.get('power_internal'),
            power_switching=item.get('power_switching'),
            power_leakage=item.get('power_leakage'),
            power_total=item.get('power_total'),
            cell_count=item.get('cell_count'),
            instance_count=item.get('instance_count'),
            net_count=item.get('net_count'),
            sequential_cell_count=item.get('sequential_cell_count'),
            target_frequency=item.get('target_frequency'),
            achieved_frequency=item.get('achieved_frequency'),
            mbb_ratio=item.get('mbb_ratio'),
            clock_gating_ratio=item.get('clock_gating_ratio'),
            utilization=item.get('utilization'),
            congestion=item.get('congestion'),
            congestion_h=item.get('congestion_h'),
            congestion_v=item.get('congestion_v'),
            congestion_b=item.get('congestion_b'),
            source_file=item.get('source_file'),
        )
        _sync_congestion(rec)
        if item.get('extra_fields') and isinstance(item['extra_fields'], dict):
            rec.extra_fields = json.dumps(item['extra_fields'], ensure_ascii=False)
        db.session.add(rec)
        restored += 1

    db.session.commit()
    return jsonify({
        'ok': True,
        'rolled_back_to': snap.to_dict(),
        'pre_rollback_snapshot': pre_snap.to_dict(),
        'restored_count': restored,
        'skipped_count': skipped,
    })


@app.route('/api/admin/snapshots/<int:snap_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_snapshot(snap_id):
    """删除快照"""
    snap = DataSnapshot.query.get_or_404(snap_id)
    # 项目级权限: admin / owner / editor 可删除快照
    if not can_edit_project(current_user, snap.project_id):
        return jsonify({'error': '无权限删除此项目的快照 (需要 editor 及以上角色)'}), 403
    db.session.delete(snap)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# 备份管理
# =========================================================================

@app.route('/api/admin/backups')
@login_required
def admin_list_backups():
    """列出所有备份记录"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    records = BackupRecord.query.order_by(BackupRecord.created_at.desc()).limit(100).all()
    return jsonify([r.to_dict() for r in records])


@app.route('/api/admin/backups', methods=['POST'])
@login_required
@with_db_retry()
def admin_create_backup():
    """手动触发数据库备份"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    result = perform_backup(backup_type='manual', user=current_user)
    if result['ok']:
        return jsonify(result)
    return jsonify(result), 500


@app.route('/api/admin/backups/verify', methods=['POST'])
@login_required
def admin_verify_all_backups():
    """校验所有备份文件的完整性"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    results = verify_all_backups()
    return jsonify(results)


def perform_backup(backup_type='auto', user=None):
    """执行数据库备份

    Args:
        backup_type: auto / manual / pre_migration
        user: 触发用户 (手动备份时)

    Returns:
        {ok, backup_id, file_path, ...} 或 {ok: False, error}
    """
    import hashlib
    if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        return {'ok': False, 'error': 'MySQL 模式不支持文件备份, 请使用数据库系统自带的备份方案'}

    db_path = os.path.join(BASE_DIR, 'qor_recorder.db')
    backup_dir = os.path.join(BASE_DIR, 'backups')
    try:
        if not os.path.exists(db_path):
            return {'ok': False, 'error': 'DB 文件不存在'}

        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'qor_recorder_{ts}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        import shutil
        shutil.copy2(db_path, backup_path)

        # 计算文件校验和
        h = hashlib.sha256()
        with open(backup_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        checksum = h.hexdigest()
        file_size = os.path.getsize(backup_path)

        # 记录当时的记录数
        record_count = QorRecord.query.count()

        record = BackupRecord(
            backup_type=backup_type,
            file_path=backup_path,
            file_size=file_size,
            checksum=checksum,
            record_count=record_count,
            status='ok',
            message=f'由 {user.username if user else "system"} 触发' if user else '系统自动',
        )
        db.session.add(record)
        db.session.commit()

        return {
            'ok': True,
            'backup_id': record.id,
            'file_path': backup_path,
            'file_size': file_size,
            'checksum': checksum[:12],
        }
    except Exception as e:
        # 记录失败状态
        try:
            fail_record = BackupRecord(
                backup_type=backup_type,
                file_path=backup_path if 'backup_path' in dir() else '',
                file_size=0,
                status='failed',
                message=str(e),
            )
            db.session.add(fail_record)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return {'ok': False, 'error': str(e)}


def verify_all_backups():
    """校验所有 ok 状态的备份文件"""
    import hashlib
    results = {'total': 0, 'ok': 0, 'missing': 0, 'corrupted': 0, 'details': []}
    records = BackupRecord.query.filter_by(status='ok').all()
    for rec in records:
        results['total'] += 1
        if not rec.checksum or not rec.file_path:
            continue
        if not os.path.exists(rec.file_path):
            results['missing'] += 1
            results['details'].append({'id': rec.id, 'status': 'missing', 'path': rec.file_path})
            continue
        h = hashlib.sha256()
        try:
            with open(rec.file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            actual = h.hexdigest()
            if actual == rec.checksum:
                results['ok'] += 1
                results['details'].append({'id': rec.id, 'status': 'ok'})
            else:
                results['corrupted'] += 1
                results['details'].append({'id': rec.id, 'status': 'corrupted'})
        except Exception as e:
            results['details'].append({'id': rec.id, 'status': 'error', 'error': str(e)})
    return results


@app.route('/api/admin/modules', methods=['POST'])
@login_required
@with_db_retry()
def admin_create_module():
    """创建模块"""
    # 项目级权限: admin / owner / editor 可创建模块
    data = request.get_json() or request.form
    project_id = data.get('project_id')
    name = data.get('name', '').strip()
    if not project_id or not name:
        return jsonify({'error': '项目ID和模块名称不能为空'}), 400
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return jsonify({'error': '无效的 project_id'}), 400
    if not can_edit_project(current_user, pid):
        return jsonify({'error': '无权限在此项目创建模块 (需要 editor 及以上角色)'}), 403
    Project.query.get_or_404(project_id)
    if Module.query.filter_by(project_id=project_id, name=name).first():
        return jsonify({'error': '模块已存在'}), 400
    m = Module(project_id=project_id, name=name, description=data.get('description', ''))
    db.session.add(m)
    db.session.commit()
    return jsonify({'id': m.id, 'name': m.name})


@app.route('/api/admin/modules/<int:module_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_module(module_id):
    """删除模块"""
    m = Module.query.get_or_404(module_id)
    # 项目级权限: admin / owner 才能删模块 (结构变更)
    if m.project:
        if not can_manage_project(current_user, m.project.id):
            return jsonify({'error': '无权限删除模块 (需要 owner 及以上角色)'}), 403
        writable, err = check_project_writable(m.project.id)
        if not writable:
            return jsonify({'error': err}), 403
    else:
        if not current_user.is_admin:
            return jsonify({'error': '无权限'}), 403
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})


def _sync_congestion(rec):
    """同步拥塞指数字段, 保持向后兼容

    规则:
      - 若 congestion_b 有值但 congestion 为空, 则 congestion = congestion_b
      - 若 congestion 有值但 congestion_b 为空, 则 congestion_b = congestion
      - 二者都为空时不动
    这样旧客户端读 congestion / 新客户端读 congestion_b 都能拿到值。
    """
    if rec.congestion_b is not None and rec.congestion is None:
        rec.congestion = rec.congestion_b
    elif rec.congestion is not None and rec.congestion_b is None:
        rec.congestion_b = rec.congestion


def _save_records_to_db(records, project, module_id, version, source_filename, mark_released=False):
    """将解析后的记录保存到数据库（内部辅助函数）

    保护措施:
      - 数值范围校验: 过滤异常大值、负数（对不该为负的字段）
      - 字符串截断: 防止超长字符串破坏 DB / JSON
      - 去重 upsert: 同 (module_id, version) 已存在则更新而非新增
      - 单行异常不影响整体

    mark_released=True 时, 新建/更新的记录会被标记为已发布 (对 release 账号可见)
    """
    saved_count = 0
    skipped_count = 0
    updated_count = 0
    module_cache = {}  # 模块名缓存，避免重复查询

    # 字符串字段最大长度（防止超长字符串污染 DB / 破坏 JSON 序列化）
    MAX_STR_LEN = 500

    # 数值字段的合理范围 (field, min_val, max_val)
    # 超出范围的值视为脏数据，置为 None
    NUMERIC_RANGES = {
        'area_total': (0, 1e9), 'area_combinational': (0, 1e9),
        'area_sequential': (0, 1e9), 'area_black_box': (0, 1e9), 'area_macro': (0, 1e9),
        'wns_setup': (-1e6, 1e6), 'tns_setup': (-1e9, 1e9),
        'wns_hold': (-1e6, 1e6), 'tns_hold': (-1e9, 1e9),
        'power_internal': (0, 1e6), 'power_switching': (0, 1e6),
        'power_leakage': (0, 1e6), 'power_total': (0, 1e6),
        'target_frequency': (0, 1e6), 'achieved_frequency': (0, 1e6),
        'nvp_setup': (0, 1e9), 'nvp_hold': (0, 1e9),
        'cell_count': (0, 1e9), 'instance_count': (0, 1e9),
        'net_count': (0, 1e9), 'sequential_cell_count': (0, 1e9),
        # 物理实现指标 (0-1 之间的小数 或 0-100 的百分比, 都接受)
        'mbb_ratio': (0, 100), 'clock_gating_ratio': (0, 100),
        'utilization': (0, 100),
        'congestion': (0, 100), 'congestion_h': (0, 100),
        'congestion_v': (0, 100), 'congestion_b': (0, 100),
    }

    FLOAT_FIELDS_SET = set(NUMERIC_RANGES.keys())

    def sanitize_value(field, val):
        """校验并清理单个数值字段"""
        if val is None:
            return None
        try:
            v = float(val)
        except (ValueError, TypeError, OverflowError):
            return None
        # NaN / Infinity
        if v != v or v in (float('inf'), float('-inf')):
            return None
        if field in NUMERIC_RANGES:
            lo, hi = NUMERIC_RANGES[field]
            if v < lo or v > hi:
                return None  # 超出合理范围，视为脏数据
        # 整数字段转 int
        if field in ('nvp_setup', 'nvp_hold', 'cell_count', 'instance_count',
                     'net_count', 'sequential_cell_count'):
            return int(v)
        return v

    def sanitize_str(val):
        """截断超长字符串"""
        if val is None:
            return None
        s = str(val).strip()
        if len(s) > MAX_STR_LEN:
            return s[:MAX_STR_LEN]
        return s if s else None

    for record in records:
        try:
            mod_name = sanitize_str(record.get('module_name'))
            if not mod_name:
                if module_id:
                    mod = Module.query.get(module_id)
                    if not mod:
                        skipped_count += 1
                        continue
                else:
                    skipped_count += 1
                    continue
            else:
                if module_id:
                    mod = Module.query.get(module_id)
                else:
                    if mod_name in module_cache:
                        mod = module_cache[mod_name]
                    else:
                        mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                        if not mod:
                            mod = Module(project_id=project.id, name=mod_name)
                            db.session.add(mod)
                            db.session.flush()
                        module_cache[mod_name] = mod

            rec_version = sanitize_str(record.get('version')) or sanitize_str(version) or 'v1'

            # 去重: 查找已有记录 (module_id, version)
            existing = QorRecord.query.filter_by(
                module_id=mod.id, version=rec_version
            ).first()

            if existing:
                # 更新已有记录（保留 id, recorded_at）
                for f in FLOAT_FIELDS_SET:
                    if f in record:
                        cleaned = sanitize_value(f, record[f])
                        if cleaned is not None:
                            setattr(existing, f, cleaned)
                # 拥塞指数向后兼容: 若 congestion 与 congestion_b 任一为空, 用对方兜底
                _sync_congestion(existing)
                # 合并 extra_fields（保留原有，更新同名字段）
                new_extra = record.get('extra_fields')
                if new_extra:
                    import json as _json
                    cur = existing.extra_fields
                    if isinstance(cur, str):
                        try:
                            cur = _json.loads(cur)
                            if isinstance(cur, str):
                                cur = _json.loads(cur)
                        except (ValueError, TypeError):
                            cur = {}
                    elif cur is None:
                        cur = {}
                    if isinstance(new_extra, str):
                        try:
                            new_extra = _json.loads(new_extra)
                        except (ValueError, TypeError):
                            new_extra = {}
                    if isinstance(new_extra, dict):
                        cur.update(new_extra)
                    existing.extra_fields = cur
                existing.source_file = sanitize_str(source_filename) or existing.source_file
                if mark_released:
                    existing.is_released = True
                    if not existing.released_at:
                        existing.released_at = datetime.utcnow()
                    if not existing.released_by and current_user.is_authenticated:
                        existing.released_by = current_user.id
                updated_count += 1
            else:
                # 新建记录
                qor = QorRecord(
                    module_id=mod.id,
                    version=rec_version,
                    source_file=sanitize_str(source_filename),
                )
                for f in FLOAT_FIELDS_SET:
                    if f in record:
                        cleaned = sanitize_value(f, record[f])
                        if cleaned is not None:
                            setattr(qor, f, cleaned)
                _sync_congestion(qor)
                qor.extra_fields = record.get('extra_fields')
                if mark_released:
                    qor.is_released = True
                    qor.released_at = datetime.utcnow()
                    if current_user.is_authenticated:
                        qor.released_by = current_user.id
                db.session.add(qor)
                saved_count += 1
        except Exception:
            # 单行异常不影响整体
            skipped_count += 1
            continue

    return saved_count, skipped_count, updated_count


def _merge_power_to_db(records, project, module_id, version, source_filename, mark_released=False):
    """将功耗数据合并到已有 QorRecord（内部辅助函数）

    匹配策略: (module_id, version) 组合，若指定 module_id 则全用该模块，
    否则按 record['module_name'] 查找模块。
    若匹配到已有记录，仅更新功耗字段；若无匹配，则新建带功耗数据的记录。

    mark_released=True 时, 新建/更新的记录会被标记为已发布。
    """
    merged_count = 0
    created_count = 0
    module_cache = {}

    power_fields = [
        'power_internal', 'power_switching', 'power_leakage', 'power_total',
        'target_frequency', 'achieved_frequency',
    ]

    for record in records:
        mod_name = record.get('module_name')
        if module_id:
            mod = Module.query.get(module_id)
        elif mod_name:
            if mod_name in module_cache:
                mod = module_cache[mod_name]
            else:
                mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                if not mod:
                    # 功耗CSV 引用了一个不存在的模块，跳过
                    continue
                module_cache[mod_name] = mod
        else:
            continue

        if not mod:
            continue

        rec_version = record.get('version') or version or 'v1'

        # 查找已有记录
        existing = QorRecord.query.filter_by(module_id=mod.id, version=rec_version).first()

        if existing:
            # 仅更新功耗字段（不覆盖已有的非功耗字段）
            updated_any = False
            for f in power_fields:
                if f in record and record[f] is not None:
                    setattr(existing, f, record[f])
                    updated_any = True

            # 合并 extra_fields（保留原有字段，覆盖/新增 power 相关）
            if record.get('extra_fields'):
                cur_extra = existing.extra_fields or {}
                if isinstance(cur_extra, str):
                    import json as _json
                    try:
                        cur_extra = _json.loads(cur_extra)
                    except Exception:
                        cur_extra = {}
                cur_extra.update(record['extra_fields'])
                existing.extra_fields = cur_extra
                updated_any = True

            if updated_any:
                if mark_released:
                    existing.is_released = True
                    if not existing.released_at:
                        existing.released_at = datetime.utcnow()
                    if not existing.released_by and current_user.is_authenticated:
                        existing.released_by = current_user.id
                merged_count += 1
        else:
            # 无匹配记录，新建（仅含功耗数据，其他字段为空）
            qor = QorRecord(
                module_id=mod.id,
                version=rec_version,
                source_file=source_filename,
            )
            for f in power_fields:
                if f in record and record[f] is not None:
                    setattr(qor, f, record[f])
            qor.extra_fields = record.get('extra_fields')
            if mark_released:
                qor.is_released = True
                qor.released_at = datetime.utcnow()
                if current_user.is_authenticated:
                    qor.released_by = current_user.id
            db.session.add(qor)
            created_count += 1

    return merged_count, created_count


def _save_violations_to_db(records, project, module_id, version, source_filename, timing_group=None):
    """将违例路径数据保存到数据库

    匹配策略: 按 (module_id, version) 查找已有 QorRecord，将违例路径关联到该记录。
    若 QorRecord 不存在，则跳过（违例路径必须关联到已有的 QoR 记录）。
    """
    saved_count = 0
    skipped_count = 0
    module_cache = {}

    MAX_STR_LEN = 500

    def sanitize_str(val):
        if val is None:
            return None
        s = str(val).strip()
        return s[:MAX_STR_LEN] if len(s) > MAX_STR_LEN else (s if s else None)

    for record in records:
        try:
            mod_name = sanitize_str(record.get('module_name'))
            if module_id:
                mod = Module.query.get(module_id)
            elif mod_name:
                if mod_name in module_cache:
                    mod = module_cache[mod_name]
                else:
                    mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                    module_cache[mod_name] = mod
            else:
                mod = None

            if not mod:
                skipped_count += 1
                continue

            rec_version = sanitize_str(record.get('version')) or sanitize_str(version) or 'v1'

            # 查找关联的 QorRecord
            qor_rec = QorRecord.query.filter_by(module_id=mod.id, version=rec_version).first()
            if not qor_rec:
                # 没有关联的 QoR 记录，跳过
                skipped_count += 1
                continue

            tg = sanitize_str(record.get('timing_group')) or sanitize_str(timing_group) or 'default'

            vp = ViolationPath(
                qor_record_id=qor_rec.id,
                timing_group=tg,
                startpoint=sanitize_str(record.get('startpoint')),
                endpoint=sanitize_str(record.get('endpoint')),
                slack=record.get('slack'),
                depth=record.get('depth'),
                pure_depth=record.get('pure_depth'),
                cell_delay=record.get('cell_delay'),
                net_delay=record.get('net_delay'),
                et_slack=record.get('et_slack'),
                st_slack=record.get('st_slack'),
                st_fanin=record.get('st_fanin'),
                st_fanout=record.get('st_fanout'),
                et_fanin=record.get('et_fanin'),
                et_fanout=record.get('et_fanout'),
                source_file=sanitize_str(source_filename),
            )
            db.session.add(vp)
            saved_count += 1
        except Exception:
            skipped_count += 1
            continue

    return saved_count, skipped_count


def _save_notes_to_db(records, project, module_id, version, source_filename, full_dir=None):
    """将 Run 备注保存到数据库

    匹配策略:
      按 (module_id, version) 查找已有 QorRecord, 若 full_dir 不为空则进一步按
      QorRecord.extra_fields.full_dir 匹配 (用于多目录同版本场景), 找不到则回退到
      该 module+version 的第一条 QorRecord。

    覆盖策略 (再次上传时覆盖旧数据):
      按 (qor_record_id, full_dir) 删除旧备注后写入新备注。这样同一目录重复 make
      不会累积, 而其他目录的备注不受影响。

    full_dir 来源优先级: CSV 行内 > 函数参数 full_dir (通常来自上传表单)。
    """
    saved_count = 0
    skipped_count = 0
    module_cache = {}
    # 记录已清空的 (qor_record_id, full_dir) 对, 避免重复删除
    cleared_keys = set()

    MAX_STR_LEN = 2000

    def sanitize_str(val, max_len=500):
        if val is None:
            return None
        s = str(val).strip()
        return s[:max_len] if len(s) > max_len else (s if s else None)

    def get_qor_full_dir(qor_rec):
        """从 QorRecord.extra_fields JSON 中提取 full_dir (容错多种键名/大小写)"""
        if not qor_rec or not qor_rec.extra_fields:
            return None
        import json as _json
        try:
            extra = _json.loads(qor_rec.extra_fields)
            if isinstance(extra, str):
                extra = _json.loads(extra)
        except (ValueError, TypeError):
            return None
        if not isinstance(extra, dict):
            return None
        # 尝试常见键名 (大小写不敏感)
        for k in ('full_dir', 'Fulldir', 'fulldir', 'FULL_DIR', 'fullDir',
                  'dir', 'directory', 'path', 'run_dir'):
            for ek, ev in extra.items():
                if str(ek).strip().lower() == k.lower():
                    return str(ev).strip() if ev else None
        return None

    for record in records:
        try:
            mod_name = sanitize_str(record.get('module_name'))
            if module_id:
                mod = Module.query.get(module_id)
            elif mod_name:
                if mod_name in module_cache:
                    mod = module_cache[mod_name]
                else:
                    mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                    module_cache[mod_name] = mod
            else:
                mod = None

            if not mod:
                skipped_count += 1
                continue

            rec_version = sanitize_str(record.get('version')) or sanitize_str(version) or 'v1'

            # 行内 full_dir 优先, 其次表单 full_dir
            row_full_dir = sanitize_str(record.get('full_dir'), max_len=1000) or sanitize_str(full_dir, max_len=1000)

            # 查找关联的 QorRecord: 先按 (module_id, version) 取全部候选
            candidates = QorRecord.query.filter_by(module_id=mod.id, version=rec_version).all()
            if not candidates:
                skipped_count += 1
                continue

            qor_rec = None
            if row_full_dir:
                # 在候选里按 extra_fields.full_dir 匹配
                for cand in candidates:
                    if (get_qor_full_dir(cand) or '') == row_full_dir:
                        qor_rec = cand
                        break
                # 找不到精确匹配, 回退到第一条 (兼容 QoR 上传时 full_dir 列名不一致的情况)
                if qor_rec is None:
                    qor_rec = candidates[0]
            else:
                qor_rec = candidates[0]

            # 覆盖逻辑: 按 (qor_record_id, full_dir) 清空旧备注
            # row_full_dir 可能为 None, 此时按 qor_record_id + full_dir IS NULL 清空
            clear_key = (qor_rec.id, row_full_dir)
            if clear_key not in cleared_keys:
                if row_full_dir:
                    RunNote.query.filter_by(
                        qor_record_id=qor_rec.id, full_dir=row_full_dir
                    ).delete()
                else:
                    # full_dir 为空: 清空该记录下所有 full_dir 为空的备注
                    RunNote.query.filter_by(
                        qor_record_id=qor_rec.id, full_dir=None
                    ).delete()
                cleared_keys.add(clear_key)

            item = sanitize_str(record.get('item'), MAX_STR_LEN) or ''
            desc = sanitize_str(record.get('description'), MAX_STR_LEN) or ''

            if not item and not desc:
                skipped_count += 1
                continue

            note = RunNote(
                qor_record_id=qor_rec.id,
                item=item,
                description=desc,
                seq=saved_count,
                source_file=sanitize_str(source_filename),
                full_dir=row_full_dir,
            )
            db.session.add(note)
            saved_count += 1
        except Exception:
            skipped_count += 1
            continue

    return saved_count, skipped_count


@app.route('/api/admin/upload', methods=['POST'])
@login_required
@with_db_retry()
def admin_upload_csv():
    """上传 QoR CSV 文件（支持多文件）

    表单字段:
      file / files: CSV 文件（支持单个或多个）
      project_id: 项目 ID
      module_id: 模块 ID (可选，不传则从 CSV 中读取或自动创建)
      version: 版本号 (可选)
    """
    # 项目级权限: admin / owner / editor 可上传
    project_id = request.form.get('project_id')
    if not project_id:
        return jsonify({'error': '请选择项目'}), 400
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return jsonify({'error': '无效的 project_id'}), 400
    if not can_edit_project(current_user, pid):
        return jsonify({'error': '无权限上传此项目数据 (需要 editor 及以上角色)'}), 403

    # 收集所有上传的文件 (支持 file 和 files[] 两种字段名)
    files = []
    if 'file' in request.files:
        files.append(request.files['file'])
    if 'files' in request.files:
        files.extend(request.files.getlist('files'))

    files = [f for f in files if f and f.filename and f.filename.lower().endswith('.csv')]

    # 前端可选传入 file_paths (webkitdirectory 模式下保留相对路径, 用于 dirname 提取)
    file_paths = request.form.getlist('file_paths') if 'file_paths' in request.form else []
    # 若未传 file_paths, 用 file.filename 兜底
    file_paths = file_paths if len(file_paths) == len(files) else [f.filename for f in files]

    if not files:
        return jsonify({'error': '请选择至少一个 CSV 文件'}), 400

    module_id = request.form.get('module_id')
    version = request.form.get('version', '').strip()

    # 模块名来源: csv(默认,从CSV列读取) / filename(从文件名提取) / dirname(从父目录名提取)
    # 批量目录上传场景下, 每个 CSV 对应一个模块, 文件内通常没有 module_name 列
    module_name_source = request.form.get('module_name_source', 'csv').strip()
    # 文件名后缀去除规则 (用于 filename 模式), 逗号分隔, 大小写不敏感
    filename_suffixes = request.form.get('filename_suffixes', '_qor,qor,_qor_report').strip()

    project = Project.query.get_or_404(project_id)
    # 检查项目是否可写入 (锁定/归档项目禁止上传)
    writable, err = check_project_writable(int(project_id))
    if not writable:
        return jsonify({'error': err}), 403

    data_type = request.form.get('data_type', 'qor')  # qor / power

    # 上传时是否直接标记为已发布 (对 release 账号可见)
    mark_released = request.form.get('mark_released') in ('1', 'true', 'on', 'yes')

    # Run 备注专用: full_dir 用于区分同 module+version 下的不同 run 目录
    upload_full_dir = request.form.get('full_dir', '').strip() if data_type == 'notes' else ''

    # 预处理: 文件名 -> 模块名 提取函数
    _suffix_tokens = tuple(s.strip().lower() for s in filename_suffixes.split(',') if s.strip())

    def _extract_module_from_filename(fname):
        """从文件名提取模块名: 去掉路径、扩展名、常见后缀(_qor 等)"""
        import os as _os
        base = _os.path.basename(fname or '')
        # 去扩展名
        name, _ext = _os.path.splitext(base)
        name_lower = name.lower()
        # 去掉配置的后缀 token (可能多次, 如 module_a_qor_qor -> module_a)
        changed = True
        while changed:
            changed = False
            for tok in _suffix_tokens:
                if name_lower.endswith(tok) and len(name_lower) > len(tok):
                    name = name[: -len(tok)]
                    name_lower = name.lower()
                    changed = True
        return name.strip() or None

    def _extract_module_from_dirname(fname):
        """从文件的父目录名提取模块名 (webkitdirectory 上传时 file.filename 带相对路径)"""
        import os as _os
        # file.filename 在 webkitdirectory 模式下形如 "module_dir/module_a/module_a_qor.csv"
        parent = _os.path.basename(_os.path.dirname(fname or ''))
        return parent.strip() or None

    total_saved = 0
    total_skipped = 0
    total_merged = 0
    total_updated = 0
    file_results = []

    for file_idx, file in enumerate(files):
        file_content = file.read()
        # webkitdirectory 模式下 file.filename 会被截断, 用 file_paths 保留的相对路径
        file_path = file_paths[file_idx] if file_idx < len(file_paths) else file.filename

        try:
            if data_type == 'violation':
                # 违例路径 CSV
                result = parse_violation_csv(file_content, filename=file.filename)
            elif data_type == 'notes':
                # Run 备注 CSV (2~3 列: item, description[, full_dir])
                result = parse_notes_csv(file_content, filename=file.filename, default_full_dir=upload_full_dir)
            else:
                # 批量上传: 按 module_name_source 提取每个文件的默认模块名
                # csv 模式下也提取作为回退 (CSV 无 module_name 列时自动使用)
                file_default_module = None
                if not module_id:
                    if module_name_source == 'filename':
                        file_default_module = _extract_module_from_filename(file_path)
                    elif module_name_source == 'dirname':
                        file_default_module = _extract_module_from_dirname(file_path)
                        if not file_default_module:
                            file_default_module = _extract_module_from_filename(file_path)
                    else:
                        # csv 模式: 提取作为回退 (dirname 优先, filename 兜底)
                        file_default_module = _extract_module_from_dirname(file_path) or \
                                              _extract_module_from_filename(file_path)
                result = parse_csv_file(
                    file_content,
                    default_project=project.name,
                    default_module=file_default_module,
                    default_version=version if version else None,
                )
            records = result['records']
            stats = result['stats']
        except Exception as e:
            file_results.append({
                'filename': file.filename,
                'ok': False,
                'error': f'CSV 解析失败: {str(e)}',
            })
            continue

        if not records:
            file_results.append({
                'filename': file.filename,
                'ok': False,
                'error': '文件中没有有效数据',
                'stats': stats,
            })
            continue

        # 每个文件独立事务: 单文件失败不影响其他已成功文件
        try:
            triggered_alerts = []
            if data_type == 'power':
                merged, created = _merge_power_to_db(records, project, module_id, version, file.filename, mark_released=mark_released)
                db.session.commit()  # 立即提交本文件
                # 触发告警检查 (对受影响的模块/版本)
                affected_mods = set()
                for r in records:
                    mn = r.get('module_name')
                    if mn:
                        m = Module.query.filter_by(project_id=project.id, name=mn).first()
                        if m:
                            affected_mods.add(m.id)
                    elif module_id:
                        affected_mods.add(int(module_id))
                for mid in affected_mods:
                    qors = QorRecord.query.filter_by(module_id=mid).all()
                    for q in qors:
                        if q.version == (version or r.get('version') or 'v1'):
                            evts = check_alerts_for_new_record(q)
                            triggered_alerts.extend(evts)
                total_merged += merged
                total_saved += created
                file_results.append({
                    'filename': file.filename,
                    'ok': True,
                    'saved': created,
                    'merged': merged,
                    'stats': stats,
                    'alerts_triggered': len(triggered_alerts),
                })
            elif data_type == 'violation':
                # 违例路径数据
                saved, skipped = _save_violations_to_db(records, project, module_id, version, file.filename, stats.get('timing_group'))
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
                file_results.append({
                    'filename': file.filename,
                    'ok': True,
                    'saved': saved,
                    'skipped': skipped,
                    'stats': stats,
                })
            elif data_type == 'notes':
                # Run 备注: 按 (qor_record_id, full_dir) 覆盖旧备注, 再写入
                saved, skipped = _save_notes_to_db(records, project, module_id, version, file.filename, full_dir=upload_full_dir or None)
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
                file_results.append({
                    'filename': file.filename,
                    'ok': True,
                    'saved': saved,
                    'skipped': skipped,
                    'stats': stats,
                })
            else:
                saved, skipped, updated = _save_records_to_db(records, project, module_id, version, file.filename, mark_released=mark_released)
                db.session.commit()  # 立即提交本文件
                # 触发告警检查: 查找本次新增/更新的记录
                affected_mods = set()
                for r in records:
                    mn = r.get('module_name')
                    if mn:
                        m = Module.query.filter_by(project_id=project.id, name=mn).first()
                        if m:
                            affected_mods.add(m.id)
                    elif module_id:
                        affected_mods.add(int(module_id))
                for mid in affected_mods:
                    rec_version = version or 'v1'
                    qor = QorRecord.query.filter_by(module_id=mid, version=rec_version).first()
                    if qor:
                        evts = check_alerts_for_new_record(qor)
                        triggered_alerts.extend(evts)
                total_saved += saved
                total_skipped += skipped
                total_updated += updated
                file_results.append({
                    'filename': file.filename,
                    'ok': True,
                    'saved': saved,
                    'updated': updated,
                    'skipped': skipped,
                    'stats': stats,
                    'alerts_triggered': len(triggered_alerts),
                })
        except Exception as e:
            db.session.rollback()  # 仅回滚当前文件
            file_results.append({
                'filename': file.filename,
                'ok': False,
                'error': f'数据库保存失败: {str(e)}',
            })

    if data_type == 'power':
        msg = f'功耗数据合并完成: 合并 {total_merged} 条，新建 {total_saved} 条'
    else:
        msg = f'成功导入 {total_saved} 条记录'
        if total_updated:
            msg += f'，更新 {total_updated} 条'
        if total_skipped:
            msg += f'，跳过 {total_skipped} 条'

    return jsonify({
        'ok': True,
        'saved_count': total_saved,
        'skipped_count': total_skipped,
        'merged_count': total_merged,
        'updated_count': total_updated,
        'data_type': data_type,
        'file_count': len(files),
        'file_results': file_results,
        'message': msg,
    })


@app.route('/api/admin/upload_block_qor', methods=['POST'])
@login_required
@with_db_retry()
def admin_upload_block_qor():
    """上传 block_qor.csv 补充 FlopCount / FlopCount_incr 到已有 QoR 记录

    不新建记录，仅通过 Fulldir 匹配已存在的 QorRecord.extra_fields.full_dir:
      - 命中唯一记录: 更新 extra_fields 加入 FlopCount / FlopCount_incr
      - 命中多条: 跳过, 计入 conflict
      - 命中 0 条: 跳过, 计入 missed

    表单字段:
      file / files: block_qor.csv (支持多文件 / 整目录上传)
      project_id: 项目 ID (权限校验用; 留空则跨项目全局匹配)
      file_paths: webkitdirectory 模式下前端额外传的相对路径数组
    """
    project_id = request.form.get('project_id')
    pid = None
    if project_id:
        try:
            pid = int(project_id)
        except (ValueError, TypeError):
            return jsonify({'error': '无效的 project_id'}), 400
        if not can_edit_project(current_user, pid):
            return jsonify({'error': '无权限补充此项目数据 (需要 editor 及以上角色)'}), 403

    files = []
    if 'file' in request.files:
        files.append(request.files['file'])
    if 'files' in request.files:
        files.extend(request.files.getlist('files'))
    files = [f for f in files if f and f.filename and f.filename.lower().endswith('.csv')]

    if not files:
        return jsonify({'error': '未选择 CSV 文件'}), 400

    file_paths = request.form.getlist('file_paths') if 'file_paths' in request.form else []
    file_paths = file_paths if len(file_paths) == len(files) else [f.filename for f in files]

    # block_qor.csv header 别名映射 (大小写/空格/下划线不敏感)
    # 仅关心 Fulldir (匹配键) + FlopCount + FlopCount_incr
    BLOCK_HEADER_ALIASES = {
        'fulldir': 'full_dir',
        'fuldir': 'full_dir',
        'full_dir': 'full_dir',
        'fullpath': 'full_dir',
        'full_path': 'full_dir',
        'dir': 'full_dir',
        'flopcount': 'flop_count',
        'flop_count': 'flop_count',
        'flops': 'flop_count',
        'ff_count': 'flop_count',
        'flopcount_incr': 'flop_count_incr',
        'flop_count_incr': 'flop_count_incr',
        'flops_incr': 'flop_count_incr',
    }

    def _normalize_header(h):
        if not h:
            return ''
        return h.strip().lower().replace(' ', '_').replace('-', '_')

    def _parse_int_safe(v):
        if v is None:
            return None
        s = str(v).strip()
        if not s or s in ('-', 'n/a', 'na', 'none', 'null'):
            return None
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None

    # 构建全表 full_dir -> [QorRecord] 索引 (一次查询, 后续内存匹配)
    # pid 为空时跨项目扫描
    import json as _json
    query = QorRecord.query.join(Module).join(Project)
    if pid:
        query = query.filter(Project.id == pid)
    all_records = query.all()

    full_dir_index = {}  # full_dir (lower) -> [QorRecord]
    for rec in all_records:
        try:
            extra = _json.loads(rec.extra_fields) if rec.extra_fields else {}
            if isinstance(extra, str):
                extra = _json.loads(extra)
        except (ValueError, TypeError):
            extra = {}
        fd = extra.get('full_dir') if isinstance(extra, dict) else None
        if fd:
            full_dir_index.setdefault(str(fd).strip().lower(), []).append(rec)

    file_results = []
    total_updated = 0
    total_missed = 0
    total_conflict = 0

    for file_idx, file in enumerate(files):
        file_content = file.read()
        try:
            text = file_content.decode('utf-8-sig', errors='replace')
        except Exception:
            text = file_content.decode('latin-1', errors='replace')

        import csv as _csv
        import io as _io
        try:
            reader = _csv.reader(_io.StringIO(text))
            rows = list(reader)
        except Exception as e:
            file_results.append({
                'filename': file.filename,
                'ok': False,
                'error': f'CSV 解析失败: {str(e)}',
            })
            continue

        if not rows:
            file_results.append({
                'filename': file.filename,
                'ok': False,
                'error': '空文件',
            })
            continue

        # 解析 header, 大小写不敏感 + 别名
        headers = [_normalize_header(h) for h in rows[0]]
        col_map = {}  # 标准字段名 -> col_idx
        for idx, h in enumerate(headers):
            std = BLOCK_HEADER_ALIASES.get(h)
            if std and std not in col_map:
                col_map[std] = idx

        if 'full_dir' not in col_map:
            file_results.append({
                'filename': file.filename,
                'ok': False,
                'error': 'CSV 缺少 Fulldir 列 (匹配键)',
            })
            continue

        fd_idx = col_map['full_dir']
        flop_idx = col_map.get('flop_count')
        flop_incr_idx = col_map.get('flop_count_incr')

        file_updated = 0
        file_missed = 0
        file_conflict = 0
        skipped_no_flop = 0
        missed_samples = []
        conflict_samples = []

        for row in rows[1:]:
            if not row or all(not c.strip() for c in row if c):
                continue
            if fd_idx >= len(row):
                continue
            fd_value = (row[fd_idx] or '').strip()
            if not fd_value or fd_value.lower() in ('-', 'n/a', 'none'):
                continue

            # 提取 FlopCount / FlopCount_incr (至少有一个非空才更新)
            flop_val = _parse_int_safe(row[flop_idx]) if flop_idx is not None and flop_idx < len(row) else None
            flop_incr_val = _parse_int_safe(row[flop_incr_idx]) if flop_incr_idx is not None and flop_incr_idx < len(row) else None
            if flop_val is None and flop_incr_val is None:
                skipped_no_flop += 1
                continue

            # 通过 full_dir 匹配 (大小写不敏感)
            matches = full_dir_index.get(fd_value.lower(), [])
            if len(matches) == 0:
                file_missed += 1
                if len(missed_samples) < 3:
                    missed_samples.append(fd_value)
                continue
            if len(matches) > 1:
                file_conflict += 1
                if len(conflict_samples) < 3:
                    conflict_samples.append(fd_value)
                continue

            # 唯一匹配: 更新 extra_fields
            rec = matches[0]
            try:
                extra = _json.loads(rec.extra_fields) if rec.extra_fields else {}
                if isinstance(extra, str):
                    extra = _json.loads(extra)
                if not isinstance(extra, dict):
                    extra = {}
            except (ValueError, TypeError):
                extra = {}

            # 用 block_qor.csv 原始 header 名作为 key (保留大小写信息)
            # 但用户习惯小写, 统一用 FlopCount / FlopCount_incr
            changed = False
            if flop_val is not None and extra.get('FlopCount') != flop_val:
                extra['FlopCount'] = flop_val
                changed = True
            if flop_incr_val is not None and extra.get('FlopCount_incr') != flop_incr_val:
                extra['FlopCount_incr'] = flop_incr_val
                changed = True

            if changed:
                rec.extra_fields = _json.dumps(extra, ensure_ascii=False)
                db.session.add(rec)
                file_updated += 1

        db.session.commit()

        file_results.append({
            'filename': file.filename,
            'ok': True,
            'updated': file_updated,
            'missed': file_missed,
            'conflict': file_conflict,
            'skipped_no_flop': skipped_no_flop,
            'missed_samples': missed_samples,
            'conflict_samples': conflict_samples,
            'total_rows': len(rows) - 1,
        })
        total_updated += file_updated
        total_missed += file_missed
        total_conflict += file_conflict

    msg = f'补充完成: 更新 {total_updated} 条'
    if total_missed:
        msg += f'，未匹配 {total_missed} 条'
    if total_conflict:
        msg += f'，冲突 {total_conflict} 条'

    return jsonify({
        'ok': True,
        'updated_count': total_updated,
        'missed_count': total_missed,
        'conflict_count': total_conflict,
        'file_count': len(files),
        'file_results': file_results,
        'message': msg,
    })


@app.route('/api/admin/upload_csv_preview', methods=['POST'])
@login_required
def admin_upload_csv_preview():
    """CSV 预览 (dry-run): 仅解析不写入 DB，返回校验报告

    用于上传前确认数据质量，避免脏数据污染 DB。
    """
    # 项目级权限: admin / owner / editor 可预览
    project_id = request.form.get('project_id')
    if not project_id:
        return jsonify({'error': '请选择项目'}), 400
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return jsonify({'error': '无效的 project_id'}), 400
    if not can_edit_project(current_user, pid):
        return jsonify({'error': '无权限预览此项目数据 (需要 editor 及以上角色)'}), 403

    files = request.files.getlist('files')
    files = [f for f in files if f and f.filename and f.filename.lower().endswith('.csv')]

    if not files:
        return jsonify({'error': '请选择至少一个 CSV 文件'}), 400

    # 前端可选传入 file_paths (webkitdirectory 模式下保留相对路径)
    file_paths = request.form.getlist('file_paths') if 'file_paths' in request.form else []
    file_paths = file_paths if len(file_paths) == len(files) else [f.filename for f in files]

    version = request.form.get('version', '').strip()

    # 与 admin_upload_csv 保持一致的模块名提取逻辑
    module_id = request.form.get('module_id')
    module_name_source = request.form.get('module_name_source', 'csv').strip()
    filename_suffixes = request.form.get('filename_suffixes', '_qor,qor,_qor_report').strip()
    _suffix_tokens = tuple(s.strip().lower() for s in filename_suffixes.split(',') if s.strip())

    def _extract_module_from_filename(fname):
        import os as _os
        base = _os.path.basename(fname or '')
        name, _ext = _os.path.splitext(base)
        name_lower = name.lower()
        changed = True
        while changed:
            changed = False
            for tok in _suffix_tokens:
                if name_lower.endswith(tok) and len(name_lower) > len(tok):
                    name = name[: -len(tok)]
                    name_lower = name.lower()
                    changed = True
        return name.strip() or None

    def _extract_module_from_dirname(fname):
        import os as _os
        parent = _os.path.basename(_os.path.dirname(fname or ''))
        return parent.strip() or None

    project = Project.query.get_or_404(project_id)

    file_reports = []
    for file_idx, file in enumerate(files):
        file_content = file.read()
        file_path = file_paths[file_idx] if file_idx < len(file_paths) else file.filename
        try:
            # 批量上传: 按 module_name_source 提取每个文件的默认模块名
            # csv 模式下也提取作为回退 (CSV 无 module_name 列时自动使用)
            file_default_module = None
            if not module_id:
                if module_name_source == 'filename':
                    file_default_module = _extract_module_from_filename(file_path)
                elif module_name_source == 'dirname':
                    file_default_module = _extract_module_from_dirname(file_path)
                    if not file_default_module:
                        file_default_module = _extract_module_from_filename(file_path)
                else:
                    # csv 模式: 提取作为回退 (dirname 优先, filename 兜底)
                    file_default_module = _extract_module_from_dirname(file_path) or \
                                          _extract_module_from_filename(file_path)
            result = parse_csv_file(
                file_content,
                default_project=project.name,
                default_module=file_default_module,
                default_version=version if version else None,
            )
            records = result['records']
            stats = result['stats']

            # 模拟校验但不写库，仅统计会新增/更新/跳过的数量
            new_count = 0
            update_count = 0
            skip_count = 0
            warnings = []
            sample_records = []

            for rec in records[:3]:  # 预览前 3 条
                sample_records.append({
                    'module_name': rec.get('module_name'),
                    'version': rec.get('version') or version,
                    'area_total': rec.get('area_total'),
                    'wns_setup': rec.get('wns_setup'),
                    'cell_count': rec.get('cell_count'),
                })

            mod_cache = {}
            for rec in records:
                mod_name = (rec.get('module_name') or '').strip()
                if not mod_name:
                    skip_count += 1
                    continue
                rec_version = (rec.get('version') or version or 'v1').strip()
                if mod_name not in mod_cache:
                    mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                    mod_cache[mod_name] = mod.id if mod else None
                mod_id = mod_cache[mod_name]
                if mod_id:
                    existing = QorRecord.query.filter_by(module_id=mod_id, version=rec_version).first()
                    if existing:
                        update_count += 1
                    else:
                        new_count += 1
                else:
                    new_count += 1  # 模块不存在将自动创建

                # 检查异常值
                for f in ['area_total', 'wns_setup', 'tns_setup', 'cell_count']:
                    v = rec.get(f)
                    if v is not None:
                        try:
                            fv = float(v)
                            if fv != fv or fv in (float('inf'), float('-inf')):
                                warnings.append(f"{mod_name}/{rec_version}: {f} 值异常 ({v})")
                            elif f.startswith('area') and fv < 0:
                                warnings.append(f"{mod_name}/{rec_version}: {f} 为负数 ({v})")
                            elif f == 'area_total' and fv > 1e9:
                                warnings.append(f"{mod_name}/{rec_version}: {f} 异常大 ({v})")
                        except (ValueError, TypeError):
                            warnings.append(f"{mod_name}/{rec_version}: {f} 无法解析 ({v})")

            file_reports.append({
                'filename': file.filename,
                'ok': True,
                'total_rows': stats.get('total_rows', 0),
                'parsed': len(records),
                'would_create': new_count,
                'would_update': update_count,
                'would_skip': skip_count,
                'warnings': warnings[:20],  # 最多显示 20 条
                'warning_count': len(warnings),
                'sample': sample_records,
            })
        except Exception as e:
            file_reports.append({
                'filename': file.filename,
                'ok': False,
                'error': f'解析失败: {str(e)}',
            })

    return jsonify({
        'ok': True,
        'dry_run': True,
        'file_reports': file_reports,
        'message': '预览完成，数据未写入数据库',
    })


@app.route('/api/admin/modules/batch', methods=['POST'])
@login_required
def admin_batch_create_modules():
    """批量创建模块

    支持两种方式:
      1. 文本列表: 在文本框中粘贴模块名，每行一个
      2. CSV 文件: 上传包含 module_name 列的 CSV

    请求 JSON:
      project_id: 项目 ID
      module_names: 模块名列表 (字符串数组)
    或表单:
      project_id, module_list (换行分隔的模块名文本)
    """
    if request.is_json:
        data = request.get_json()
        project_id = data.get('project_id')
        module_names = data.get('module_names', [])
    else:
        project_id = request.form.get('project_id')
        module_list_text = request.form.get('module_list', '')
        # 按换行或逗号分隔
        module_names = [n.strip() for n in module_list_text.replace(',', '\n').split('\n') if n.strip()]

    if not project_id:
        return jsonify({'error': '请选择项目'}), 400
    if not module_names:
        return jsonify({'error': '模块名称列表不能为空'}), 400

    # 项目级权限: admin / owner / editor 可批量创建模块
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return jsonify({'error': '无效的 project_id'}), 400
    if not can_edit_project(current_user, pid):
        return jsonify({'error': '无权限在此项目批量创建模块 (需要 editor 及以上角色)'}), 403

    Project.query.get_or_404(project_id)

    created = []
    skipped = []
    for name in module_names:
        name = name.strip()
        if not name:
            continue
        if Module.query.filter_by(project_id=project_id, name=name).first():
            skipped.append(name)
        else:
            m = Module(project_id=project_id, name=name)
            db.session.add(m)
            created.append(name)

    db.session.commit()

    return jsonify({
        'ok': True,
        'created_count': len(created),
        'skipped_count': len(skipped),
        'created': created,
        'skipped': skipped,
        'message': f'创建 {len(created)} 个模块' + (f'，跳过 {len(skipped)} 个已存在' if skipped else ''),
    })


@app.route('/api/admin/records/<int:record_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_record(record_id):
    """删除单条 QoR 记录"""
    r = QorRecord.query.get_or_404(record_id)
    # 项目级权限: admin / owner / editor 可删除记录
    if r.module and r.module.project:
        if not can_edit_project(current_user, r.module.project.id):
            return jsonify({'error': '无权限删除此项目的记录 (需要 editor 及以上角色)'}), 403
        writable, err = check_project_writable(r.module.project.id)
        if not writable:
            return jsonify({'error': err}), 403
    else:
        if not current_user.is_admin:
            return jsonify({'error': '无权限'}), 403
    db.session.delete(r)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/admin/users')
@login_required
def admin_list_users():
    """获取用户列表"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    users = User.query.order_by(User.created_at).all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'role': u.role,
        'display_name': u.display_name,
        'created_at': u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else '',
    } for u in users])


@app.route('/api/admin/users', methods=['POST'])
@login_required
def admin_create_user():
    """创建用户"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'user')
    display_name = data.get('display_name', '')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400
    if role not in ('admin', 'user', 'release'):
        return jsonify({'error': '无效的角色'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '用户名已存在'}), 400

    user = User(username=username, role=role, display_name=display_name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({'id': user.id, 'username': user.username, 'role': user.role})


@app.route('/api/admin/users/batch', methods=['POST'])
@login_required
def admin_batch_create_users():
    """批量创建用户

    请求体:
      - usernames: 用户名列表 (字符串数组或换行分隔的字符串)
      - password: 默认密码 (可选, 默认 '123456')
      - role: 角色 (可选, 默认 'user')
    返回: {created: [...], skipped: [{username, reason}], total: n}
    """
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}

    # 解析用户名列表
    raw = data.get('usernames', [])
    if isinstance(raw, str):
        usernames = [u.strip() for u in re.split(r'[\n,;\s]+', raw) if u.strip()]
    else:
        usernames = [str(u).strip() for u in raw if str(u).strip()]

    if not usernames:
        return jsonify({'error': '用户名列表不能为空'}), 400

    password = data.get('password') or '123456'
    role = data.get('role', 'user')
    if role not in ('admin', 'user', 'release'):
        return jsonify({'error': '无效的角色'}), 400

    created = []
    skipped = []

    # 一次性查所有已存在的用户名, 避免逐条查询
    existing = set(u.username for u in User.query.filter(
        User.username.in_(usernames)
    ).all())

    for uname in usernames:
        if uname in existing:
            skipped.append({'username': uname, 'reason': '用户名已存在'})
            continue
        user = User(username=uname, role=role)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.flush()
            created.append({'id': user.id, 'username': uname})
            existing.add(uname)  # 防止列表内重复
        except Exception as e:
            db.session.rollback()
            skipped.append({'username': uname, 'reason': str(e)})

    db.session.commit()
    return jsonify({
        'created': created,
        'skipped': skipped,
        'total': len(usernames),
        'default_password': password,
    })


@app.route('/api/admin/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
def admin_reset_user_password(user_id):
    """管理员重置指定用户的密码

    请求体:
      - password: 新密码 (可选, 不传则重置为 '123456')
    """
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    data = request.get_json(silent=True) or {}
    new_password = data.get('password') or 'Reset@123'

    user.set_password(new_password)
    db.session.commit()
    return jsonify({'ok': True, 'username': user.username, 'reset_to': new_password})


@app.route('/api/user/password', methods=['POST'])
@login_required
def user_change_own_password():
    """用户修改自己的密码

    请求体:
      - old_password: 旧密码
      - new_password: 新密码 (至少 4 位)
    """
    data = request.get_json() or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return jsonify({'error': '旧密码和新密码不能为空'}), 400
    if not current_user.check_password(old_password):
        return jsonify({'error': '旧密码错误'}), 400
    if old_password == new_password:
        return jsonify({'error': '新密码不能与旧密码相同'}), 400

    current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# API v1 - 纯 REST API (供 React/Vue 前端及自动化集成消费)
#
# 认证方式 (二选一):
#   1. X-API-Key 请求头 (或 Authorization: Bearer qor_xxx)
#   2. 浏览器 session (兼容现有 Jinja2 UI)
#
# 响应格式: 统一 JSON
#   成功: {"ok": true, ...data} 或直接数组/对象
#   失败: {"error": "message"}, HTTP 状态码 4xx/5xx
# =========================================================================

@app.route('/api/v1/auth/login', methods=['POST'])
def api_v1_login():
    """API 登录 - 返回 API Key (供前端存储后用于后续请求)

    请求体: {"username": "...", "password": "..."}
    返回: {"api_key": "qor_xxx", "user": {...}}
    """
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'error': '用户名或密码错误'}), 401

    # 创建临时 API Key (有效期 7 天)
    plaintext = ApiKey.generate_key()
    api_key = ApiKey(
        user_id=user.id,
        key_hash=ApiKey.hash_key(plaintext),
        prefix=plaintext[:12],
        name=f'login-token-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}',
        scopes='read,upload',
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.session.add(api_key)
    db.session.commit()

    return jsonify({
        'api_key': plaintext,
        'api_key_id': api_key.id,
        'user': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name,
        },
    })


@app.route('/api/v1/auth/me')
@api_auth_required()
def api_v1_me():
    """获取当前认证用户信息"""
    user = g.auth_user
    return jsonify({
        'id': user.id,
        'username': user.username,
        'role': user.role,
        'display_name': user.display_name,
        'auth_method': g.auth_method,
    })


@app.route('/api/v1/projects')
@api_auth_required()
def api_v1_list_projects():
    """获取当前用户可访问的项目列表"""
    user = g.auth_user
    projects = filter_projects_by_permission(user).order_by(Project.created_at).all()
    result = []
    for p in projects:
        role = get_user_project_role(user, p.id)
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'my_role': role,
            'module_count': p.modules.count(),
        })
    return jsonify(result)


@app.route('/api/v1/projects', methods=['POST'])
@api_auth_required(required_scope='upload')
def api_v1_create_project():
    """创建新项目 (创建者自动成为 owner)"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '项目名不能为空'}), 400

    project = Project(name=name, description=data.get('description', ''))
    db.session.add(project)
    db.session.flush()
    # 创建者成为 owner
    member = ProjectMember(project_id=project.id, user_id=user.id, role='owner')
    db.session.add(member)
    db.session.commit()
    return jsonify({
        'id': project.id, 'name': project.name,
        'description': project.description, 'my_role': 'owner',
    }), 201


@app.route('/api/v1/projects/<int:project_id>')
@api_auth_required()
def api_v1_get_project(project_id):
    """获取项目详情"""
    user = g.auth_user
    if not can_access_project(user, project_id):
        return jsonify({'error': '无权限访问此项目'}), 403
    p = Project.query.get_or_404(project_id)
    return jsonify({
        'id': p.id, 'name': p.name, 'description': p.description,
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'my_role': get_user_project_role(user, p.id),
        'modules': [{
            'id': m.id, 'name': m.name, 'description': m.description,
            'record_count': m.qor_records.count(),
        } for m in p.modules.order_by(Module.name)],
    })


# --- 项目成员管理 ---

@app.route('/api/v1/projects/<int:project_id>/members')
@api_auth_required()
def api_v1_list_members(project_id):
    """获取项目成员列表"""
    user = g.auth_user
    if not can_access_project(user, project_id):
        return jsonify({'error': '无权限'}), 403
    members = ProjectMember.query.filter_by(project_id=project_id).all()
    return jsonify([m.to_dict() for m in members])


@app.route('/api/v1/projects/<int:project_id>/members', methods=['POST'])
@api_auth_required()
def api_v1_add_member(project_id):
    """添加项目成员 (需要 manage 权限)"""
    user = g.auth_user
    if not can_manage_project(user, project_id):
        return jsonify({'error': '需要项目管理权限'}), 403
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    role = data.get('role', 'viewer')
    if role not in ('owner', 'editor', 'viewer'):
        return jsonify({'error': '无效角色'}), 400
    target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({'error': '用户不存在'}), 404
    existing = ProjectMember.query.filter_by(project_id=project_id, user_id=target.id).first()
    if existing:
        existing.role = role
        db.session.commit()
        return jsonify(existing.to_dict())
    m = ProjectMember(project_id=project_id, user_id=target.id, role=role)
    db.session.add(m)
    db.session.commit()
    return jsonify(m.to_dict()), 201


@app.route('/api/v1/projects/<int:project_id>/members/<int:member_id>', methods=['DELETE'])
@api_auth_required()
def api_v1_remove_member(project_id, member_id):
    """移除项目成员"""
    user = g.auth_user
    if not can_manage_project(user, project_id):
        return jsonify({'error': '需要项目管理权限'}), 403
    m = ProjectMember.query.filter_by(id=member_id, project_id=project_id).first_or_404()
    if m.role == 'owner':
        owners = ProjectMember.query.filter_by(project_id=project_id, role='owner').count()
        if owners <= 1:
            return jsonify({'error': '不能移除最后一个 owner'}), 400
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})


# --- 数据锁 ---

@app.route('/api/v1/locks')
@api_auth_required()
def api_v1_list_locks():
    """获取当前活跃的数据锁"""
    resource_type = request.args.get('resource_type')
    resource_id = request.args.get('resource_id', type=int)
    q = DataLock.query
    if resource_type:
        q = q.filter_by(resource_type=resource_type)
    if resource_id:
        q = q.filter_by(resource_id=resource_id)
    locks = q.order_by(DataLock.locked_at.desc()).all()
    return jsonify([l.to_dict() for l in locks if not l.is_expired])


@app.route('/api/v1/locks', methods=['POST'])
@api_auth_required()
def api_v1_create_lock():
    """加锁资源"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    resource_type = data.get('resource_type', '').strip()
    try:
        resource_id = int(data.get('resource_id'))
    except (TypeError, ValueError):
        resource_id = None
    reason = data.get('reason', '')
    duration_minutes = data.get('duration_minutes', 30)

    if resource_type not in ('project', 'module', 'record'):
        return jsonify({'error': '无效 resource_type'}), 400
    if not resource_id:
        return jsonify({'error': '缺少 resource_id'}), 400

    # 权限检查: project 锁需要 manage, module/record 锁需要 edit
    if resource_type == 'project':
        if not can_manage_project(user, resource_id):
            return jsonify({'error': '无权限锁定此项目'}), 403
    elif resource_type == 'module':
        mod = Module.query.get(resource_id)
        if not mod or not can_edit_project(user, mod.project_id):
            return jsonify({'error': '无权限锁定此模块'}), 403
    else:  # record
        rec = QorRecord.query.get(resource_id)
        if not rec:
            return jsonify({'error': '记录不存在'}), 404
        mod = rec.module
        if not can_edit_project(user, mod.project_id):
            return jsonify({'error': '无权限锁定此记录'}), 403

    # 检查是否已被他人锁定
    locked_by_other, existing = check_data_lock(resource_type, resource_id, user)
    if locked_by_other:
        return jsonify({
            'error': f'资源已被 {existing.user.username} 锁定',
            'lock': existing.to_dict(),
        }), 409

    # 如果已有锁 (自己锁的或过期), 先删除
    if existing:
        db.session.delete(existing)
        db.session.flush()

    lock = DataLock(
        resource_type=resource_type,
        resource_id=resource_id,
        locked_by=user.id,
        expires_at=datetime.utcnow() + timedelta(minutes=duration_minutes),
        reason=reason,
    )
    db.session.add(lock)
    db.session.commit()
    return jsonify(lock.to_dict()), 201


@app.route('/api/v1/locks/<int:lock_id>', methods=['DELETE'])
@api_auth_required()
def api_v1_release_lock(lock_id):
    """释放锁"""
    user = g.auth_user
    lock = DataLock.query.get_or_404(lock_id)
    if lock.locked_by != user.id and not user.is_admin:
        return jsonify({'error': '只能释放自己持有的锁'}), 403
    db.session.delete(lock)
    db.session.commit()
    return jsonify({'ok': True})


# --- API Key 管理 ---

@app.route('/api/v1/apikeys')
@api_auth_required()
def api_v1_list_apikeys():
    """列出当前用户的 API Keys"""
    user = g.auth_user
    keys = ApiKey.query.filter_by(user_id=user.id).order_by(ApiKey.created_at.desc()).all()
    return jsonify([k.to_dict() for k in keys])


@app.route('/api/v1/apikeys', methods=['POST'])
@api_auth_required()
def api_v1_create_apikey():
    """创建新 API Key (明文仅返回一次)"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    scopes = data.get('scopes', 'read')
    days = data.get('expires_in_days')

    if not name:
        return jsonify({'error': '请填写 API Key 名称'}), 400
    for s in scopes.split(','):
        if s.strip() not in ('read', 'upload', 'admin'):
            return jsonify({'error': f'无效 scope: {s}'}), 400

    plaintext = ApiKey.generate_key()
    api_key = ApiKey(
        user_id=user.id,
        key_hash=ApiKey.hash_key(plaintext),
        prefix=plaintext[:12],
        name=name,
        scopes=scopes,
        expires_at=datetime.utcnow() + timedelta(days=days) if days else None,
    )
    db.session.add(api_key)
    db.session.commit()
    return jsonify({
        'id': api_key.id,
        'key': plaintext,  # 明文仅此一次
        'name': api_key.name,
        'prefix': api_key.prefix,
        'scopes': api_key.scopes,
        'expires_at': api_key.expires_at.isoformat() if api_key.expires_at else None,
    }), 201


@app.route('/api/v1/apikeys/<int:key_id>', methods=['DELETE'])
@api_auth_required()
def api_v1_revoke_apikey(key_id):
    """吊销 API Key"""
    user = g.auth_user
    k = ApiKey.query.filter_by(id=key_id, user_id=user.id).first_or_404()
    k.revoked = True
    db.session.commit()
    return jsonify({'ok': True})


# --- 自动化上传 (DC 流程) ---

@app.route('/api/v1/upload', methods=['POST'])
@api_auth_required(required_scope='upload')
@with_db_retry()
def api_v1_upload():
    """自动化数据上传端点 (支持 API Key 认证)

    供 DC 流程脚本调用, 使用 curl 上传 CSV:
      curl -X POST https://host/api/v1/upload \\
        -H "X-API-Key: qor_xxx" \\
        -F "project_id=1" \\
        -F "version=v1.0" \\
        -F "data_type=qor" \\
        -F "files=@qor_report.csv"

    表单字段:
      project_id: 项目 ID
      module_id: 模块 ID (可选)
      version: 版本号 (可选)
      data_type: qor / power / violation (默认 qor)
      files: 一个或多个 CSV 文件
    """
    user = g.auth_user

    project_id = request.form.get('project_id')
    module_id = request.form.get('module_id')
    version = request.form.get('version', '').strip()
    data_type = request.form.get('data_type', 'qor')

    # 上传时是否直接标记为已发布
    mark_released = request.form.get('mark_released') in ('1', 'true', 'on', 'yes')

    # Run 备注专用: full_dir 用于区分同 module+version 下的不同 run 目录 (Makefile 多目录场景)
    upload_full_dir = request.form.get('full_dir', '').strip() if data_type == 'notes' else ''

    if not project_id:
        return jsonify({'error': '缺少 project_id'}), 400
    if not can_edit_project(user, int(project_id)):
        return jsonify({'error': '无权限上传到此项目'}), 403

    # 检查项目是否被锁定/归档
    writable, err = check_project_writable(int(project_id))
    if not writable:
        return jsonify({'error': err}), 403

    # 检查模块/项目是否被他人锁定
    if module_id:
        locked_by_other, lock = check_data_lock('module', int(module_id), user)
        if locked_by_other:
            return jsonify({'error': f'模块被 {lock.user.username} 锁定', 'lock': lock.to_dict()}), 409
    else:
        locked_by_other, lock = check_data_lock('project', int(project_id), user)
        if locked_by_other:
            return jsonify({'error': f'项目被 {lock.user.username} 锁定', 'lock': lock.to_dict()}), 409

    project = Project.query.get_or_404(project_id)

    files = request.files.getlist('files')
    if not files:
        if 'file' in request.files:
            files = [request.files['file']]
    files = [f for f in files if f and f.filename and f.filename.lower().endswith('.csv')]
    if not files:
        return jsonify({'error': '请上传至少一个 CSV 文件'}), 400

    total_saved = total_skipped = total_updated = total_merged = 0
    file_results = []
    triggered_alerts = []

    for f in files:
        content = f.read()
        try:
            if data_type == 'violation':
                result = parse_violation_csv(content, filename=f.filename)
            elif data_type == 'notes':
                result = parse_notes_csv(content, filename=f.filename, default_full_dir=upload_full_dir)
            else:
                result = parse_csv_file(content, default_project=project.name,
                                        default_module=None,
                                        default_version=version or None)
            records = result['records']
            stats = result['stats']
        except Exception as e:
            file_results.append({'filename': f.filename, 'ok': False, 'error': str(e)})
            continue

        if not records:
            file_results.append({'filename': f.filename, 'ok': False, 'error': '无有效数据'})
            continue

        try:
            if data_type == 'power':
                merged, created = _merge_power_to_db(records, project, module_id, version, f.filename, mark_released=mark_released)
                db.session.commit()
                total_merged += merged
                total_saved += created
            elif data_type == 'violation':
                saved, skipped = _save_violations_to_db(records, project, module_id, version, f.filename, stats.get('timing_group'))
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
            elif data_type == 'notes':
                saved, skipped = _save_notes_to_db(records, project, module_id, version, f.filename, full_dir=upload_full_dir or None)
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
            else:
                saved, skipped, updated = _save_records_to_db(records, project, module_id, version, f.filename, mark_released=mark_released)
                db.session.commit()
                # 告警检查
                affected_mods = set()
                for r in records:
                    mn = r.get('module_name')
                    if mn:
                        m = Module.query.filter_by(project_id=project.id, name=mn).first()
                        if m:
                            affected_mods.add(m.id)
                    elif module_id:
                        affected_mods.add(int(module_id))
                for mid in affected_mods:
                    rec_version = version or 'v1'
                    qor = QorRecord.query.filter_by(module_id=mid, version=rec_version).first()
                    if qor:
                        triggered_alerts.extend(check_alerts_for_new_record(qor))
                total_saved += saved
                total_skipped += skipped
                total_updated += updated
            file_results.append({
                'filename': f.filename, 'ok': True,
                'saved': saved if data_type != 'power' else created,
                'stats': stats,
            })
        except Exception as e:
            db.session.rollback()
            file_results.append({'filename': f.filename, 'ok': False, 'error': str(e)})

    return jsonify({
        'ok': True,
        'saved_count': total_saved,
        'skipped_count': total_skipped,
        'updated_count': total_updated,
        'merged_count': total_merged,
        'alerts_triggered': len(triggered_alerts),
        'file_count': len(files),
        'file_results': file_results,
        'uploaded_by': user.username,
    })


# --- 告警规则与事件 ---

@app.route('/api/v1/alerts/rules')
@api_auth_required()
def api_v1_list_alert_rules():
    """获取告警规则列表"""
    user = g.auth_user
    project_id = request.args.get('project_id', type=int)
    if project_id and not can_access_project(user, project_id):
        return jsonify({'error': '无权限'}), 403
    q = AlertRule.query
    if project_id:
        q = q.filter_by(project_id=project_id)
    # 非管理员只能看自己项目的规则
    if not user.is_admin:
        accessible = db.session.query(ProjectMember.project_id).filter_by(user_id=user.id).subquery()
        q = q.filter(AlertRule.project_id.in_(accessible))
    rules = q.order_by(AlertRule.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rules])


@app.route('/api/v1/alerts/rules', methods=['POST'])
@api_auth_required()
def api_v1_create_alert_rule():
    """创建告警规则"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    try:
        project_id = int(data.get('project_id'))
    except (TypeError, ValueError):
        project_id = None
    if not project_id:
        return jsonify({'error': '缺少 project_id'}), 400
    if not can_manage_project(user, project_id):
        return jsonify({'error': '需要项目管理权限'}), 403
    if data.get('direction') not in ('worsen', 'improve', 'threshold'):
        return jsonify({'error': '无效 direction'}), 400

    rule = AlertRule(
        project_id=project_id,
        module_id=data.get('module_id'),
        metric=data.get('metric', 'wns_setup'),
        direction=data.get('direction', 'worsen'),
        threshold=data.get('threshold'),
        window_size=data.get('window_size', 1),
        sensitivity=data.get('sensitivity', 0.2),
        enabled=data.get('enabled', True),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify(rule.to_dict()), 201


@app.route('/api/v1/alerts/rules/<int:rule_id>', methods=['PUT', 'DELETE'])
@api_auth_required()
def api_v1_modify_alert_rule(rule_id):
    """更新或删除告警规则"""
    user = g.auth_user
    rule = AlertRule.query.get_or_404(rule_id)
    if not can_manage_project(user, rule.project_id):
        return jsonify({'error': '无权限'}), 403
    if request.method == 'DELETE':
        db.session.delete(rule)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json(silent=True) or {}
    for field in ('metric', 'direction', 'threshold', 'window_size', 'sensitivity', 'enabled', 'module_id'):
        if field in data:
            setattr(rule, field, data[field])
    db.session.commit()
    return jsonify(rule.to_dict())


@app.route('/api/v1/alerts/events')
@api_auth_required()
def api_v1_list_alert_events():
    """获取告警事件列表"""
    user = g.auth_user
    project_id = request.args.get('project_id', type=int)
    acknowledged = request.args.get('acknowledged')
    limit = min(request.args.get('limit', 100, type=int), 500)

    q = AlertEvent.query.join(AlertRule)
    if project_id:
        if not can_access_project(user, project_id):
            return jsonify({'error': '无权限'}), 403
        q = q.filter(AlertRule.project_id == project_id)
    elif not user.is_admin:
        accessible = db.session.query(ProjectMember.project_id).filter_by(user_id=user.id).subquery()
        q = q.filter(AlertRule.project_id.in_(accessible))

    if acknowledged == 'true':
        q = q.filter(AlertEvent.acknowledged_by.isnot(None))
    elif acknowledged == 'false':
        q = q.filter(AlertEvent.acknowledged_by.is_(None))

    events = q.order_by(AlertEvent.triggered_at.desc()).limit(limit).all()
    return jsonify([e.to_dict() for e in events])


@app.route('/api/v1/alerts/events/<int:event_id>/acknowledge', methods=['POST'])
@api_auth_required()
def api_v1_acknowledge_event(event_id):
    """确认告警事件"""
    user = g.auth_user
    ev = AlertEvent.query.get_or_404(event_id)
    rule = ev.rule
    if not can_access_project(user, rule.project_id):
        return jsonify({'error': '无权限'}), 403
    ev.acknowledged_by = user.id
    ev.acknowledged_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ev.to_dict())


# =========================================================================
# 错误处理
# =========================================================================

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='无权限访问'), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='页面不存在'), 404


@app.errorhandler(429)
def rate_limited(e):
    """Rate Limit 超限"""
    retry_after = request.headers.get('Retry-After', '60')
    msg = f'请求过于频繁, 请 {retry_after} 秒后重试'
    # API 请求返回 JSON
    if request.path.startswith('/api/') or request.is_json:
        resp = jsonify({'error': msg, 'retry_after': int(retry_after)})
        resp.headers['Retry-After'] = str(retry_after)
        return resp, 429
    return render_template('error.html', code=429, message=msg), 429


@app.errorhandler(400)
def bad_request(e):
    """CSRF 校验失败等 400 错误"""
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({'error': str(e.description) if hasattr(e, 'description') else '请求错误'}), 400
    return render_template('error.html', code=400, message='请求错误'), 400


# =========================================================================
# 启动
# =========================================================================

def backup_database(db_path, backup_dir='backups', max_backups=10):
    """启动时自动备份 DB 文件，保留最近 max_backups 份

    保护策略:
      - 每次启动备份一份带时间戳的副本
      - 超过 max_backups 份时自动清理最旧的 (同时更新 DB 记录)
      - 备份失败不影响启动
      - 记录元信息到 BackupRecord 表 (含校验和, 支持后续完整性校验)
    """
    import shutil
    from datetime import datetime
    try:
        if not os.path.exists(db_path):
            return
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'qor_recorder_{ts}.db')
        shutil.copy2(db_path, backup_path)

        # 计算文件 sha256 校验和
        import hashlib
        h = hashlib.sha256()
        with open(backup_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        checksum = h.hexdigest()
        file_size = os.path.getsize(backup_path)

        # 记录到 BackupRecord (app_context 内部, 失败不抛)
        try:
            with app.app_context():
                record_count = QorRecord.query.count() if 'QorRecord' in dir() else 0
                rec = BackupRecord(
                    backup_type='auto',
                    file_path=backup_path,
                    file_size=file_size,
                    checksum=checksum,
                    record_count=record_count,
                    status='ok',
                    message='系统启动自动备份',
                )
                db.session.add(rec)
                db.session.commit()
        except Exception as e:
            print(f'[BACKUP] 写入备份记录失败(不影响启动): {e}')

        # 清理超出 max_backups 份的旧备份
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith('qor_recorder_') and f.endswith('.db')],
            reverse=True
        )
        for old in backups[max_backups:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass
        print(f'[BACKUP] 已备份 DB -> {backup_path} ({file_size//1024}KB)')
    except Exception as e:
        print(f'[BACKUP] 备份失败(不影响启动): {e}')


if __name__ == '__main__':
    # 启动前备份 DB (仅 SQLite, MySQL 由 DBA 负责备份)
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        backup_database(os.path.join(BASE_DIR, 'qor_recorder.db'))
    else:
        print('[DB] 使用 MySQL 后端, 跳过文件备份 (请确保 MySQL 已配置备份策略)')

    with app.app_context():
        db.create_all()
        # 轻量级列迁移: 为已有表补充新增列 (SQLite/MySQL 兼容)
        _ensure_columns()

        # 初始化默认管理员
        # 注意: admin@2026 符合密码策略 (8+ 位, 含字母+数字), 首次登录后请立即修改
        if User.query.filter_by(username='admin').first() is None:
            admin = User(username='admin', role='admin', display_name='管理员')
            admin.set_password('admin@2026')
            db.session.add(admin)
        if User.query.filter_by(username='user').first() is None:
            user = User(username='user', role='user', display_name='普通用户')
            user.set_password('user@2026')
            db.session.add(user)
        # 初始化默认 release 账号 (对外只读, 仅看已发布的 QoR 数据)
        if User.query.filter_by(username='release').first() is None:
            rel = User(username='release', role='release', display_name='Release 客户')
            rel.set_password('release@2026')
            db.session.add(rel)
            print('[INIT] 已创建默认 release 账号: release / release@2026 (仅可查看已发布数据)')
        db.session.commit()

        # 安全检查: admin 是否仍使用默认密码
        if is_default_admin_password_weak():
            # 注: 默认密码 admin@2026 符合密码策略但仍属弱口令 (公开可知)
            print('=' * 60)
            print('[SECURITY] 警告: admin 账户仍使用出厂默认密码!')
            print('  当前默认: admin@2026 (或历史版本 admin123)')
            print('  请立即登录修改为强密码')
            print('=' * 60)

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
