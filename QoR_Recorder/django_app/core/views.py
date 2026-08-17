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
import re

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
    if not (request.user.is_admin or request.user.is_owner):
        return HttpResponseForbidden()
    return render(request, 'admin.html', {'user': request.user})


@login_required
def qor_record_detail_page(request, record_id):
    """QoR 记录详情页 (v5.0)

    跨项目库查找 QorRecord:
      - 先通过 _find_qor_record_project 定位项目 DB
      - 再在该项目库中查询 QorRecord 并检查权限

    - admin / owner / viewer: 可查看所有非隐藏项目记录
    - viewer 仍由中间件保持严格只读
    """
    # 跨项目库定位
    pid = _find_qor_record_project(record_id)
    if pid is None:
        raise Http404("记录不存在")
    if not Project.objects.exclude(status='hidden').filter(pk=pid).exists():
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

    if not request.user.is_admin and not request.user.is_owner and not request.user.is_viewer:
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
    """Admin-only raw database browser/editor for main and project databases."""
    if not request.user.is_admin:
        return HttpResponseForbidden()
    if not getattr(settings, 'ENABLE_DB_ADMIN', False):
        return render(request, 'error.html', {
            'message': '数据库可视化未启用。请设置环境变量 ENABLE_DB_ADMIN=1',
        }, status=403)

    action = request.POST.get('action') or request.GET.get('action', 'tables')
    data = {'action': action}
    database_choices = [{
        'alias': 'default',
        'label': '主数据库',
        'path': str(settings.DATABASES['default'].get('NAME', '')),
    }]
    for project in Project.objects.order_by('name'):
        alias = _get_project_db_alias(project.id)
        try:
            connection = get_project_engine(project.id)
            database_choices.append({
                'alias': alias,
                'label': f'{project.name} ({project.id})',
                'path': str(connection.settings_dict.get('NAME', '')),
            })
        except Exception as exc:
            logger.warning('Cannot register project DB %s: %s', project.id, exc)
    allowed_aliases = {item['alias'] for item in database_choices}
    db_alias = request.POST.get('database') or request.GET.get('database', 'default')
    if db_alias not in allowed_aliases:
        db_alias = 'default'
    data.update({
        'databases': database_choices,
        'database': db_alias,
        'database_info': next(item for item in database_choices if item['alias'] == db_alias),
    })

    try:
        connection = connections[db_alias]
        is_sqlite = 'sqlite' in connection.settings_dict.get('ENGINE', '').lower()
        quote = connection.ops.quote_name
        tables = sorted(connection.introspection.table_names())
        data['tables'] = tables

        table = request.POST.get('table') or request.GET.get('table', '')
        data['current_table'] = table or None
        if table and table not in tables:
            data['error'] = '无效的表名'
            table = ''

        def get_columns(selected_table):
            with connection.cursor() as cursor:
                description = connection.introspection.get_table_description(
                    cursor, selected_table,
                )
                constraints = connection.introspection.get_constraints(
                    cursor, selected_table,
                )
            primary_names = {
                column
                for constraint in constraints.values()
                if constraint.get('primary_key')
                for column in constraint.get('columns', [])
            }
            return [{
                'name': column.name,
                'type': str(column.type_code),
                'notnull': not bool(column.null_ok),
                'default': getattr(column, 'default', '') or '',
                'pk': column.name in primary_names,
            } for column in description]

        columns = get_columns(table) if table else []
        pk_column = next((column['name'] for column in columns if column['pk']), None)
        data['column_details'] = columns
        data['pk_column'] = pk_column

        if request.method == 'POST' and action in ('update', 'delete'):
            if not table or not pk_column:
                data['error'] = '该表没有可用的单列主键，禁止修改'
            else:
                if getattr(settings, 'AUTO_BACKUP_ENABLED', False):
                    from django_app.services.backup_service import perform_backup
                    backup = perform_backup(
                        backup_type='pre_db_admin_edit',
                        user=request.user,
                    )
                    if not backup.get('ok'):
                        raise RuntimeError(f'写入前备份失败: {backup.get("error")}')
                pk_value = request.POST.get('pk_value')
                if action == 'delete':
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f'DELETE FROM {quote(table)} WHERE {quote(pk_column)} = %s',
                            [pk_value],
                        )
                    messages.success(request, f'已删除 {table}.{pk_column}={pk_value}')
                else:
                    editable = [
                        column['name'] for column in columns
                        if column['name'] != pk_column
                    ]
                    values = [
                        None if request.POST.get(f'field__{name}') == '__NULL__'
                        else request.POST.get(f'field__{name}', '')
                        for name in editable
                    ]
                    assignments = ', '.join(f'{quote(name)} = %s' for name in editable)
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f'UPDATE {quote(table)} SET {assignments} '
                            f'WHERE {quote(pk_column)} = %s',
                            values + [pk_value],
                        )
                    messages.success(request, f'已更新 {table}.{pk_column}={pk_value}')
                return redirect(
                    f"{request.path}?database={db_alias}&action=browse&table={table}"
                )

        if action == 'schema' and table:
            data['columns'] = columns
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT COUNT(*) FROM {quote(table)}')
                data['row_count'] = cursor.fetchone()[0]
        elif action == 'browse' and table:
            page = max(1, int(request.GET.get('page', 1)))
            per_page = 50
            offset = (page - 1) * per_page
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT * FROM {quote(table)} LIMIT %s OFFSET %s',
                    [per_page, offset],
                )
                rows = cursor.fetchall()
                names = [column[0] for column in cursor.description]
                cursor.execute(f'SELECT COUNT(*) FROM {quote(table)}')
                total = cursor.fetchone()[0]
            pk_index = names.index(pk_column) if pk_column in names else None
            data.update({
                'columns': names,
                'rows': [{
                    'cells': list(row),
                    'pk': row[pk_index] if pk_index is not None else None,
                } for row in rows],
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': max(1, (total + per_page - 1) // per_page),
            })
        elif action == 'edit' and table and pk_column:
            pk_value = request.GET.get('pk')
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT * FROM {quote(table)} WHERE {quote(pk_column)} = %s',
                    [pk_value],
                )
                row = cursor.fetchone()
                names = [column[0] for column in cursor.description]
            if row is None:
                data['error'] = '记录不存在'
            else:
                data['edit_fields'] = [
                    {'name': name, 'value': value, 'pk': name == pk_column}
                    for name, value in zip(names, row)
                ]
                data['pk_value'] = pk_value
        elif action == 'query':
            sql = request.GET.get('sql', '').strip()
            data['sql'] = sql
            if sql and not re.match(r'^\s*select\b', sql, re.I):
                data['error'] = '只允许 SELECT 查询'
            elif sql:
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    rows = cursor.fetchmany(201)
                    data['columns'] = [column[0] for column in cursor.description]
                    data['rows'] = [{'cells': list(row)} for row in rows[:200]]
                    data['truncated'] = len(rows) > 200
        data['db_type'] = 'sqlite' if is_sqlite else connection.vendor
    except Exception as exc:
        data['error'] = str(exc)
        data.setdefault('db_type', 'unknown')

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