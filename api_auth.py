"""API 认证与权限控制

支持两种认证方式:
  1. X-API-Key 请求头 (自动化场景, DC 流程上传)
  2. Flask-Login session (浏览器场景, 兼容现有 Jinja2 UI)

v5.0 角色模型:
  - admin  : 系统管理员 (所有权限)
  - owner  : 数据全权用户 (上传/管理自己+协作者模块/发布/授权)
  - viewer : 只读用户 (仅可查看已发布数据)

项目级权限 (兼容保留):
  - owner: 项目所有者
  - editor: 可上传/修改数据
  - viewer: 只读

模块级协作 (v5.0 新增):
  - 模块 owner (Module.owner_id) 唯一
  - 协作者列表 (Module.collaborators) 可管理该模块下所有数据
"""
from functools import wraps
from flask import request, g, jsonify
from flask_login import current_user
from models import db, ApiKey, ProjectMember, DataLock, Project
from datetime import datetime


def check_project_writable(project_id):
    """检查项目是否可写入 (未被锁定/归档)

    返回:
      (writable, error_message)
      writable=True 表示可写入
    """
    project = Project.query.get(project_id)
    if not project:
        return False, '项目不存在'
    if not project.is_writable:
        status_map = {'locked': '项目已锁定', 'archived': '项目已归档'}
        return False, status_map.get(project.status, f'项目状态为 {project.status}, 禁止写入')
    return True, None


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
    owner:  返回其所在项目 (旧 ProjectMember 概念, v5.0 起 owner 全项目可读)
    viewer: 仅其所在项目 (is_released 过滤在数据层做)
    """
    if user.is_admin:
        if query is not None:
            return query
        return Project.query

    # v5.0 owner/viewer: 项目级成员关系 (ProjectMember) + 公开项目
    member_project_ids = db.session.query(ProjectMember.project_id).filter_by(
        user_id=user.id
    ).subquery()
    if query is not None:
        return query.filter(Project.id.in_(member_project_ids))
    return Project.query.filter(Project.id.in_(member_project_ids))


# =========================================================================
# v5.0 模块级协作权限
# =========================================================================

def can_manage_module(user, module) -> bool:
    """用户是否可管理指定模块 (admin / 模块owner / 协作者)

    用于 v5.0 owner 角色:
      - admin: 所有模块
      - module.owner_id == user.id: 模块创建者
      - user.id in module.get_collaborator_ids(): 被授权协作者
    viewer 角色永远返回 False.
    """
    if user is None:
        return False
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_admin:
        return True
    if user.is_viewer:
        return False
    # owner 角色: 模块 owner 或 协作者
    if module is None:
        return False
    if getattr(module, 'owner_id', None) == user.id:
        return True
    try:
        return user.id in module.get_collaborator_ids()
    except Exception:
        return False


def can_view_unpublished_data(user) -> bool:
    """用户是否可查看未发布数据 (admin / owner = 是, viewer = 否)"""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_admin or user.is_owner:
        return True
    return False


def can_manage_collaborators(user, module) -> bool:
    """仅模块 owner (创建者) 和 admin 可管理协作者列表

    协作者 (非 owner) 不能添加/删除其他协作者, 避免权限扩散
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_admin:
        return True
    if module is None:
        return False
    return getattr(module, 'owner_id', None) == user.id
