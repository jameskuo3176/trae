"""认证与授权装饰器

Django 版本, 与 Flask 版本 api_auth.py 对应的装饰器功能一致。

包含:
  - login_required: 要求登录的装饰器
  - api_auth_required: API Key 认证装饰器
  - admin_required: 管理员权限检查
  - owner_or_admin_required: owner 或 admin 权限
  - project_access_required: 项目访问控制
  - data_lock_required: 数据锁检查
"""
import hashlib
import hmac
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import redirect

User = get_user_model()


# =========================================================================
# 登录要求
# =========================================================================

def login_required(view_func):
    """要求用户登录的装饰器

    未登录: AJAX 返回 401 JSON, 页面返回 302 重定向到登录页
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if _is_ajax(request):
                return JsonResponse({'error': '请先登录'}, status=401)
            return redirect(f'{settings.LOGIN_URL}?next={request.path}')
        return view_func(request, *args, **kwargs)
    return wrapper


def login_required_ajax(view_func):
    """要求登录, 未登录返回 401 JSON"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': '请先登录'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


# =========================================================================
# API Key 认证
# =========================================================================

def authenticate_request(request):
    """认证 API 请求

    支持两种认证方式:
      1. Session 认证 (浏览器登录)
      2. API Key 认证 (X-API-Key 或 Authorization: Bearer 头)

    返回:
      User 对象 (认证成功) 或 None
    """
    # 1. Session 认证
    if hasattr(request, 'user') and request.user.is_authenticated:
        return request.user

    # 2. API Key 认证
    api_key = (
        request.META.get('HTTP_X_API_KEY')
        or _extract_bearer_token(request)
    )
    if api_key:
        from django_app.core.models import ApiKey
        key_hash = ApiKey.hash_key(api_key)
        try:
            key_obj = ApiKey.objects.select_related('user').get(
                key_hash=key_hash,
                revoked=False,
            )
            if key_obj.is_valid:
                # 更新最后使用时间
                from django.utils import timezone
                ApiKey.objects.filter(id=key_obj.id).update(
                    last_used_at=timezone.now()
                )
                request.api_key = key_obj
                request.auth_method = 'api_key'
                return key_obj.user
        except ApiKey.DoesNotExist:
            pass

    return None


def _extract_bearer_token(request):
    """从 Authorization: Bearer <token> 提取 token"""
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.startswith('Bearer '):
        return auth[7:]
    return None


def api_auth_required(required_scope=None):
    """要求认证的装饰器

    参数:
      required_scope: 需要的 scope (read / upload / admin), None=任意已认证用户
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = authenticate_request(request)
            if not user:
                return JsonResponse(
                    {'error': '未认证。请提供 X-API-Key 或登录。'},
                    status=401,
                )

            if required_scope and getattr(request, 'auth_method', None) == 'api_key':
                if not request.api_key.has_scope(required_scope):
                    return JsonResponse(
                        {'error': f'API Key 缺少 {required_scope} 权限'},
                        status=403,
                    )

            # 注入 user 到 request
            request.user = user
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# =========================================================================
# 角色检查
# =========================================================================

def admin_required(view_func):
    """要求管理员权限"""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin:
            if _is_ajax(request):
                return JsonResponse({'error': '需要管理员权限'}, status=403)
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def owner_or_admin_required(view_func):
    """要求 owner 或 admin 权限"""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin and not request.user.is_owner:
            if _is_ajax(request):
                return JsonResponse({'error': '需要数据管理权限'}, status=403)
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


# =========================================================================
# 项目访问控制
# =========================================================================

def project_access_required():
    """检查用户是否有权访问指定项目

    从 request 中提取 project_id, 验证用户是否有权限。
    用于视图函数, 返回装饰器。
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            project_id = kwargs.get('project_id') or request.GET.get('project_id')
            if not project_id:
                return JsonResponse({'error': '缺少 project_id'}, status=400)

            try:
                project_id = int(project_id)
            except (ValueError, TypeError):
                return JsonResponse({'error': '无效的 project_id'}, status=400)

            # admin 有所有权限
            if request.user.is_admin:
                return view_func(request, *args, **kwargs)

            # 检查项目成员
            from django_app.core.models import ProjectMember
            is_member = ProjectMember.objects.filter(
                project_id=project_id,
                user=request.user,
            ).exists()

            if not is_member and not request.user.is_admin:
                return JsonResponse(
                    {'error': '无权限访问此项目'},
                    status=403,
                )

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# =========================================================================
# 数据锁检查
# =========================================================================

def data_lock_required(resource_type):
    """检查资源是否有活跃锁

    返回装饰器, 在写操作前检查锁状态。
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            resource_id = kwargs.get('pk') or kwargs.get(f'{resource_type}_id')
            if not resource_id:
                return view_func(request, *args, **kwargs)

            from django_app.core.models import DataLock
            from django.utils import timezone

            lock = DataLock.objects.filter(
                resource_type=resource_type,
                resource_id=resource_id,
                expires_at__gt=timezone.now(),
            ).first()

            if lock and lock.locked_by_id != request.user.id:
                return JsonResponse({
                    'error': f'此资源已被 {lock.locked_by.username} 锁定',
                    'locked_by': lock.locked_by_id,
                    'locked_by_name': lock.locked_by.username,
                    'expires_at': lock.expires_at.isoformat(),
                }, status=423)

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# =========================================================================
# 辅助函数
# =========================================================================

def _is_ajax(request):
    """判断是否为 AJAX 请求"""
    return (
        request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        or request.META.get('HTTP_ACCEPT', '').startswith('application/json')
        or request.content_type == 'application/json'
    )


def generate_csrf_token(request):
    """生成 CSRF token (兼容旧版 API)"""
    from django_app.core.security import generate_csrf_token as _gen
    return _gen(request)


def csrf_protect(request):
    """CSRF 保护 (兼容旧版 API)"""
    from django_app.core.security import csrf_protect as _protect
    return _protect(request)