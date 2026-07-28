"""主页面路由

负责页面级路由:
  - / (Dashboard)
  - /compare
  - /review
  - /admin
  - /qor_record/<id>
  - /dbadmin (数据库可视化)
"""
from flask import (
    Blueprint, abort, current_app, jsonify, redirect, render_template,
    request, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import text

from models import db

bp = Blueprint('main', __name__)


# =========================================================================
# 主页面 (通过 factory.add_url_rule 注册, 保持 url_for('dashboard') 兼容)
# =========================================================================

@login_required
def dashboard():
    """主 Dashboard 页面"""
    focus_record_id = request.args.get('focus_record_id', type=int)
    pre_project_id = request.args.get('project_id', type=int)
    pre_module_id = request.args.get('module_id', type=int)
    pre_version = request.args.get('version', '')
    pre_full_dir = request.args.get('full_dir', '')
    return render_template(
        'dashboard.html',
        user=current_user,
        focus_record_id=focus_record_id,
        pre_project_id=pre_project_id,
        pre_module_id=pre_module_id,
        pre_version=pre_version,
        pre_full_dir=pre_full_dir,
    )


@login_required
def compare():
    """数据对比页面"""
    return render_template('compare.html', user=current_user)


@bp.route('/review')
@login_required
def review():
    """Review 流程主页面"""
    if current_user.is_release:
        return render_template(
            'error.html',
            message='release 角色无 Review 权限',
            user=current_user,
        ), 403
    return render_template('review.html', user=current_user)


@login_required
def admin_page():
    """管理员 / Release 页面

    release 角色现在也可访问此页面 (v4.x 权限升级),
    但只能管理自己发布的记录 (见 admin.html 前端权限控制
    + admin_toggle_release / admin_batch_release 端点内校验)。
    """
    if not (current_user.is_admin or current_user.is_release):
        abort(403)
    return render_template('admin.html', user=current_user)


@bp.route('/qor_record/<int:record_id>')
@login_required
def qor_record_detail_page(record_id):
    """QoR 记录详情页 (release 角色现在可查看所有记录)"""
    from models import QorRecord, ProjectMember
    rec = QorRecord.query.get_or_404(record_id)
    if not current_user.is_admin and not current_user.is_release:
        member = ProjectMember.query.filter_by(
            project_id=rec.module.project_id, user_id=current_user.id,
        ).first()
        if not member:
            return 'forbidden', 403
    return render_template(
        'qor_record_detail.html',
        record_id=record_id,
        user=current_user,
    )


# =========================================================================
# 数据库可视化 (替代 Adminer)
# =========================================================================

@login_required
def db_admin(subpath=''):
    """数据库可视化面板 (仅管理员)"""
    if not current_user.is_admin:
        abort(403)
    if not current_app.config.get('ENABLE_DB_ADMIN'):
        return render_template('error.html', message='数据库可视化未启用。请设置环境变量 ENABLE_DB_ADMIN=1'), 403

    action = request.args.get('action', 'tables')
    data = {}

    try:
        uri = current_app.config['SQLALCHEMY_DATABASE_URI']
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
                    'pk': row[5] > 0,
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
                    'pk': row[4] == 'PRI',
                } for row in r]

        def _safe_table(table):
            """验证表名安全性"""
            return table and table.replace('_', '').isalnum()

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
                    {'lim': per_page, 'off': offset},
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
    data['db_type'] = 'sqlite' if current_app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite') else 'mysql'
    try:
        return render_template('dbadmin.html', data=data)
    except Exception as e:
        import traceback
        current_app.logger.error('[db_admin] 模板渲染失败: %s\n%s', e, traceback.format_exc())
        return f'<pre>模板渲染错误: {e}</pre><pre>{traceback.format_exc()}</pre>', 500
