"""API 认证与权限控制

支持两种认证方式:
  1. X-API-Key 请求头 (自动化场景, DC 流程上传)
  2. Flask-Login session (浏览器场景, 兼容现有 Jinja2 UI)

项目级权限:
  - admin: 全部访问
  - owner: 项目所有者
  - editor: 可上传/修改数据
  - viewer: 只读
  - 非成员: 不可见该项目
"""
from functools import wraps
from flask import request, g, jsonify
from flask_login import current_user
from models import db, ApiKey, ProjectMember, DataLock, Project
from datetime import datetime


def authenticate_request():
    """认证当前请求, 优先 API Key, 其次 session

    成功后设置 g.auth_user 和 g.auth_method。
    返回 User 对象或 None。
    """
    # 优先: API Key (X-API-Key 头)
    api_key_raw = request.headers.get('X-API-Key') or request.headers.get('Authorization', '').replace('Bearer ', '', 1) if request.headers.get('Authorization', '').startswith('Bearer ') else request.headers.get('X-API-Key')
    if not api_key_raw:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            api_key_raw = auth_header[7:]

    if api_key_raw:
        key_hash = ApiKey.hash_key(api_key_raw)
        api_key = ApiKey.query.filter_by(key_hash=key_hash, revoked=False).first()
        if api_key and api_key.is_valid:
            # 更新最后使用时间
            api_key.last_used_at = datetime.utcnow()
            db.session.commit()
            g.auth_user = api_key.user
            g.auth_method = 'api_key'
            g.api_key = api_key
            return api_key.user
        return None

    # 其次: session (浏览器)
    if current_user.is_authenticated:
        g.auth_user = current_user
        g.auth_method = 'session'
        g.api_key = None
        return current_user

    return None


def api_auth_required(required_scope=None):
    """要求认证的装饰器

    参数:
      required_scope: 需要的 scope (read/upload/admin), None=任意已认证用户
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = authenticate_request()
            if not user:
                return jsonify({'error': '未认证。请提供 X-API-Key 或登录。'}), 401

            if required_scope and g.auth_method == 'api_key':
                if not g.api_key.has_scope(required_scope):
                    return jsonify({'error': f'API Key 缺少 {required_scope} 权限'}), 403

            return func(*args, **kwargs)
        return wrapper
    return decorator


def get_user_project_role(user, project_id):
    """获取用户在指定项目的角色

    返回:
      'admin' - 系统管理员 (全部权限)
      'owner' / 'editor' / 'viewer' - 项目成员角色
      None - 非成员 (无权限)
    """
    if user.is_admin:
        return 'admin'

    membership = ProjectMember.query.filter_by(
        project_id=project_id, user_id=user.id
    ).first()
    return membership.role if membership else None


def can_access_project(user, project_id):
    """用户是否能访问项目 (查看)"""
    role = get_user_project_role(user, project_id)
    return role is not None


def can_edit_project(user, project_id):
    """用户是否能编辑项目数据 (上传/修改/删除)"""
    role = get_user_project_role(user, project_id)
    return role in ('admin', 'owner', 'editor')


def can_manage_project(user, project_id):
    """用户是否能管理项目 (管理成员/锁)"""
    role = get_user_project_role(user, project_id)
    return role in ('admin', 'owner')


def require_project_access(perm='view'):
    """要求项目访问权限的装饰器

    参数:
      perm: 'view' / 'edit' / 'manage'
    从 URL 参数中提取 project_id (支持 query 参数和 JSON body)
    """
    perm_check = {
        'view': can_access_project,
        'edit': can_edit_project,
        'manage': can_manage_project,
    }.get(perm, can_access_project)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = getattr(g, 'auth_user', None) or authenticate_request()
            if not user:
                return jsonify({'error': '未认证'}), 401

            # 从 kwargs / query / body 中提取 project_id
            project_id = kwargs.get('project_id')
            if not project_id:
                project_id = request.args.get('project_id')
            if not project_id and request.is_json:
                project_id = request.get_json(silent=True).get('project_id') if request.get_json(silent=True) else None
            if not project_id:
                project_id = request.form.get('project_id')

            if not project_id:
                return jsonify({'error': '缺少 project_id'}), 400

            try:
                pid = int(project_id)
            except (ValueError, TypeError):
                return jsonify({'error': '无效的 project_id'}), 400

            if not perm_check(user, pid):
                return jsonify({'error': '无权限访问此项目'}), 403

            return func(*args, **kwargs)
        return wrapper
    return decorator


def check_data_lock(resource_type, resource_id, user):
    """检查资源是否被锁定, 以及当前用户是否持锁

    返回:
      (locked_by_other, lock)
      locked_by_other=True 表示资源被其他人锁定
    """
    lock = DataLock.query.filter_by(
        resource_type=resource_type, resource_id=resource_id
    ).first()

    if not lock or lock.is_expired:
        return False, lock

    if lock.locked_by == user.id or user.is_admin:
        return False, lock

    return True, lock


def filter_projects_by_permission(user, query=None):
    """过滤用户可访问的项目查询

    admin: 返回全部
    其他: 返回其所在项目 + 公开项目 (暂无公开概念, 仅成员项目)
    """
    if user.is_admin:
        if query is not None:
            return query
        return Project.query

    member_project_ids = db.session.query(ProjectMember.project_id).filter_by(
        user_id=user.id
    ).subquery()
    if query is not None:
        return query.filter(Project.id.in_(member_project_ids))
    return Project.query.filter(Project.id.in_(member_project_ids))
