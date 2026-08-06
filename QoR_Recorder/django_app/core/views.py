"""页面级视图

负责页面级路由:
  - / (Dashboard)
  - /compare
  - /review
  - /admin
  - /qor_record/<id>
  - /dbadmin (数据库可视化)
  - /login /logout
  - /change_password
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db import connections
from django.http import HttpResponseForbidden, Http404
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt

from django_app.core.decorators import login_required
from django_app.core.db_routing import (
    _find_qor_record_project, get_project_engine,
    set_current_project_id,
    _get_project_db_alias,
)
from django_app.core.models import User, Project, QorRecord, Module, ProjectMember

logger = logging.getLogger(__name__)


# =========================================================================
# 主页面
# =========================================================================

@login_required
def dashboard(request):
    """主 Dashboard 页面"""
    focus_record_id = request.GET.get('focus_record_id')
    if focus_record_id:
        try:
            focus_record_id = int(focus_record_id)
        except (ValueError, TypeError):
            focus_record_id = None
    pre_project_id = request.GET.get('project_id')
    if pre_project_id:
        try:
            pre_project_id = int(pre_project_id)
        except (ValueError, TypeError):
            pre_project_id = None
    pre_module_id = request.GET.get('module_id')
    if pre_module_id:
        try:
            pre_module_id = int(pre_module_id)
        except (ValueError, TypeError):
            pre_module_id = None
    pre_version = request.GET.get('version', '')
    pre_full_dir = request.GET.get('full_dir', '')
    return render(request, 'dashboard.html', {
        'user': request.user,
        'focus_record_id': focus_record_id,
        'pre_project_id': pre_project_id,
        'pre_module_id': pre_module_id,
        'pre_version': pre_version,
        'pre_full_dir': pre_full_dir,
    })


@login_required
def compare(request):
    """数据对比页面"""
    return render(request, 'compare.html', {'user': request.user})


@login_required
def review_page(request):
    """Review 流程主页面"""
    if request.user.is_viewer:
        return render(request, 'error.html', {
            'message': 'viewer 角色无 Review 权限',
            'user': request.user,
        }, status=403)
    return render(request, 'review.html', {'user': request.user})


@login_required
def admin_page(request):
    """管理员 / 数据用户页面 (v5.0)

    - admin:  完整管理权限 (项目管理/用户管理/数据上传/记录管理)
    - owner:  数据管理权限 (数据上传/记录管理, 含协作者授权)
    - viewer: 拒绝访问
    """
    if request.user.is_viewer:
        return HttpResponseForbidden()
    if not (request.user.is_admin or request.user.is_owner or request.user.is_release):
        return HttpResponseForbidden()
    return render(request, 'admin.html', {'user': request.user})


@login_required
def qor_record_detail_page(request, record_id):
    """QoR 记录详情页 (v5.0)

    跨项目库查找 QorRecord:
      - 先通过 _find_qor_record_project 定位项目 DB
      - 再在该项目库中查询 QorRecord 并检查权限

    - admin / owner: 可查看所有记录
    - viewer: 仅可看已发布记录 (未发布 404); 不受 ProjectMember 限制 (本身无项目角色)
    """
    # 跨项目库定位
    pid = _find_qor_record_project(record_id)
    if pid is None:
        raise Http404("记录不存在")

    # 获取项目库连接并查询
    alias = _get_project_db_alias(pid)
    get_project_engine(pid)

    try:
        rec = QorRecord.objects.using(alias).get(pk=record_id)
    except QorRecord.DoesNotExist:
        raise Http404("记录不存在")

    # 设置线程局部 project_id, 确保 rec.module 等关联查询能正确路由到项目库
    set_current_project_id(pid)

    # v5.0 viewer: 未发布记录视同不存在 (不受 ProjectMember 限制)
    if request.user.is_viewer:
        if not rec.is_released:
            raise Http404("记录不存在")
    elif not request.user.is_admin and not request.user.is_release and not request.user.is_owner:
        # 其它角色: 需是项目成员
        member = ProjectMember.objects.filter(
            project_id=rec.module.project_id, user=request.user,
        ).first()
        if not member:
            return HttpResponseForbidden('forbidden')

    return render(request, 'qor_record_detail.html', {
        'record_id': record_id,
        'user': request.user,
    })


# =========================================================================
# 数据库可视化 (替代 Adminer)
# =========================================================================

@login_required
def db_admin(request, subpath=''):
    """数据库可视化面板 (仅管理员)"""
    if not request.user.is_admin:
        return HttpResponseForbidden()
    if not getattr(settings, 'ENABLE_DB_ADMIN', False):
        return render(request, 'error.html', {
            'message': '数据库可视化未启用。请设置环境变量 ENABLE_DB_ADMIN=1',
        }, status=403)

    action = request.GET.get('action', 'tables')
    data = {}

    try:
        db_uri = settings.DATABASES['default'].get('ENGINE', '')
        is_sqlite = 'sqlite' in db_uri.lower()

        def _get_tables():
            """获取所有表名"""
            with connections['default'].cursor() as cursor:
                if is_sqlite:
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                else:
                    cursor.execute(
                        "SELECT table_name AS name FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() ORDER BY table_name"
                    )
                return [row[0] for row in cursor.fetchall()]

        def _get_columns(table):
            """获取表结构"""
            with connections['default'].cursor() as cursor:
                if is_sqlite:
                    cursor.execute(f"PRAGMA table_info({table})")
                    return [{
                        'name': row[1], 'type': row[2], 'notnull': row[3],
                        'default': row[4] if row[4] is not None else '',
                        'pk': row[5] > 0,
                    } for row in cursor.fetchall()]
                else:
                    cursor.execute(
                        f"SELECT column_name, data_type, is_nullable, column_default, column_key "
                        f"FROM information_schema.columns WHERE table_schema = DATABASE() "
                        f"AND table_name = '{table}' ORDER BY ordinal_position"
                    )
                    return [{
                        'name': row[0], 'type': row[1], 'notnull': row[2] == 'NO',
                        'default': row[3] if row[3] is not None else '',
                        'pk': row[4] == 'PRI',
                    } for row in cursor.fetchall()]

        def _safe_table(table):
            """验证表名安全性"""
            return table and table.replace('_', '').isalnum()

        data['tables'] = _get_tables()

        if action == 'tables':
            data['current_table'] = None
        elif action == 'schema':
            table = request.GET.get('table', '')
            data['current_table'] = table
            if not _safe_table(table):
                data['error'] = '无效的表名'
            else:
                data['columns'] = _get_columns(table)
                with connections['default'].cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    data['row_count'] = cursor.fetchone()[0]
        elif action == 'browse':
            table = request.GET.get('table', '')
            page = max(1, int(request.GET.get('page', 1)))
            per_page = 50
            offset = (page - 1) * per_page
            data['current_table'] = table
            if not _safe_table(table):
                data['error'] = '无效的表名'
            else:
                with connections['default'].cursor() as cursor:
                    cursor.execute(
                        f"SELECT * FROM {table} LIMIT %s OFFSET %s",
                        [per_page, offset],
                    )
                    rows = cursor.fetchall()
                    data['columns'] = [col[0] for col in cursor.description] if rows else []
                    data['rows'] = [list(r) for r in rows]
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    cnt = cursor.fetchone()[0]
                    data['total'] = cnt
                    data['page'] = page
                    data['per_page'] = per_page
                    data['total_pages'] = (cnt + per_page - 1) // per_page
        elif action == 'query':
            sql = request.GET.get('sql', '').strip()
            data['sql'] = sql
            if not sql.lower().startswith('select'):
                data['error'] = '只允许执行 SELECT 查询'
            else:
                try:
                    with connections['default'].cursor() as cursor:
                        cursor.execute(sql)
                        rows = cursor.fetchall()
                        data['columns'] = [col[0] for col in cursor.description] if rows else []
                        data['rows'] = [list(r) for r in rows[:200]]
                        data['truncated'] = len(rows) > 200
                except Exception as e:
                    data['error'] = str(e)
    except Exception as e:
        data['error'] = str(e)

    data['action'] = action
    data['db_type'] = 'sqlite' if is_sqlite else 'mysql'
    try:
        return render(request, 'dbadmin.html', {'data': data})
    except Exception as e:
        import traceback
        logger.error('[db_admin] 模板渲染失败: %s\n%s', e, traceback.format_exc())
        return HttpResponseForbidden(
            f'<pre>模板渲染错误: {e}</pre><pre>{traceback.format_exc()}</pre>'
        )


# =========================================================================
# 登录/登出
# =========================================================================

@csrf_exempt
def login_view(request):
    """用户登录

    GET: 显示登录表单 (已登录则跳转 dashboard / change_password)
    POST: 认证用户并登录
    """
    if request.user.is_authenticated:
        if getattr(request.user, 'must_change_password', False):
            return redirect('change_password_page')
        return redirect('dashboard')

    if request.method == 'POST':
        # 支持 JSON 格式和表单格式两种登录请求
        if request.content_type == 'application/json':
            import json as _json
            try:
                body = _json.loads(request.body) if request.body else {}
            except _json.JSONDecodeError:
                body = {}
            username = body.get('username', '').strip()
            password = body.get('password', '')
        else:
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            next_url = request.GET.get('next')
            if getattr(user, 'must_change_password', False):
                return redirect('change_password_page')
            return redirect(next_url or 'dashboard')
        else:
            messages.error(request, '用户名或密码错误')
            return render(request, 'login.html', {
                'error': '用户名或密码错误',
            })

    return render(request, 'login.html')


@login_required
def logout_view(request):
    """用户登出"""
    logout(request)
    return redirect('login')


# =========================================================================
# 强制改密页面
# =========================================================================

@login_required
def change_password_page(request):
    """强制改密页 (HTML)

    当 user.must_change_password=True 时，before_request 钩子
    会把所有其他页面请求都重定向到这里，改密成功后清零标志。
    """
    if not getattr(request.user, 'must_change_password', False):
        return redirect('dashboard')
    return render(request, 'change_password.html', {'user': request.user})