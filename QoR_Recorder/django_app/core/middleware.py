"""Django 自定义中间件

包含:
  - SecurityMiddleware: 安全检查 (must_change_password / viewer 只读 / CSRF)
  - RateLimitMiddleware: 内存滑动窗口限流
  - CSRFMiddleware: 自定义 CSRF 保护 (兼容 Flask 版本的 token 格式)

在 settings.MIDDLEWARE 中注册:
    'django_app.core.middleware.SecurityMiddleware',
    'django_app.core.middleware.RateLimitMiddleware',
    'django_app.core.middleware.ProjectContextMiddleware',
"""
import json
import time
from collections import defaultdict, deque

from django.conf import settings
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import resolve

# 从 db_routing 导入 ProjectContextMiddleware (保持向后兼容)
from django_app.core.db_routing import ProjectContextMiddleware  # noqa: F401


# =========================================================================
# SecurityMiddleware
# =========================================================================
class SecurityMiddleware:
    """Django 安全中间件

    功能:
      1. must_change_password=True 的用户强制改密
         - GET 请求: 重定向到 /change_password/
         - POST/PUT/DELETE/PATCH: 返回 403 JSON
         - 例外: change_password / logout / user_change_own_password 本身
      2. viewer 角色禁止写操作
         - 允许: 改密 / 主题 / dashboard 等纯个人设置
      3. CSRF 保护 (委托给 CSRFMiddleware)
    """

    # must_change_password=True 的用户唯一可访问的端点
    MUST_CHANGE_ALLOWED_NAMES = {
        'user_change_own_password',
        'admin_user_change_own_password_legacy',
        'change_password_page',
        'logout',
        # API 端点（允许 GET 请求加载数据，写操作仍被拦截）
        'api_get_projects',
        'api_get_modules',
        'api_get_module_records',
        'api_get_versions',
        'api_get_qor_data',
        'api_get_metrics',
        'api_get_dir_modules',
        'api_get_qor_run',
        'api_get_violations',
        'api_get_violation_groups',
        'api_get_violation_source_files',
        'api_get_violation_diff',
        'api_get_run_notes',
        'api_get_compare',
        'api_get_record_detail',
        'api_get_dashboard_config',
        'api_v1_login',
        'api_v1_me',
        'api_v1_logout',
        'api_v1_projects',
        'api_v1_project_detail',
        'api_v1_upload',
        'api_v1_alerts',
        'api_v1_locks',
        'api_v1_metrics',
    }

    # must_change_password=True 的用户 GET 访问以下端点时重定向到改密页
    MUST_CHANGE_REDIRECT_NAMES = {
        'dashboard',
        'compare',
        'review_page',
        'admin_page',
        'qor_record_detail_page',
        'db_admin',
        'db_admin_subpath',
    }

    # viewer 角色允许的写操作端点
    VIEWER_ALLOWED_WRITE_NAMES = {
        'user_change_own_password',
        'admin_user_change_own_password_legacy',
        # POST transport, but semantically a read-only batch lookup.
        'api_v2_annotation_batch',
        'save_user_theme',
        'get_user_theme',
        # 允许 viewer 登出 / 切换账号, 否则会被只读拦截卡死 (无法退出也无法登录其他账号)
        'api_v1_login',
        'api_v1_logout',
    }

    PASSWORD_CHANGE_PATHS = {
        '/api/user/password',
        '/api/admin/user/password',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 检查用户认证状态
        if hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user

            # 1. must_change_password 强制改密
            if getattr(user, 'must_change_password', False):
                response = self._handle_must_change_password(request)
                if response is not None:
                    return response

            # 2. viewer 角色只读限制
            if getattr(user, 'is_viewer', False):
                response = self._handle_viewer_restriction(request)
                if response is not None:
                    return response

        response = self.get_response(request)
        return response

    def _handle_must_change_password(self, request):
        """处理强制改密逻辑"""
        if request.path_info.rstrip('/') in self.PASSWORD_CHANGE_PATHS:
            return None

        try:
            url_name = resolve(request.path_info).url_name
        except Exception:
            url_name = None

        if url_name in self.MUST_CHANGE_ALLOWED_NAMES:
            return None

        # 写操作: 返回 403
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            return JsonResponse(
                {'error': '请先修改密码后再操作', 'must_change_password': True},
                status=403,
            )

        # GET: 重定向到 /change_password
        if request.method == 'GET' and url_name in self.MUST_CHANGE_REDIRECT_NAMES:
            return HttpResponseRedirect('/change_password/')

        return None

    def _handle_viewer_restriction(self, request):
        """处理 viewer 角色只读限制"""
        if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
            return None

        if request.path_info.rstrip('/') in self.PASSWORD_CHANGE_PATHS:
            return None

        try:
            url_name = resolve(request.path_info).url_name
        except Exception:
            url_name = None

        if url_name in self.VIEWER_ALLOWED_WRITE_NAMES:
            return None

        return JsonResponse(
            {'error': 'viewer 账号为只读权限, 不允许此操作'},
            status=403,
        )


# =========================================================================
# RateLimitMiddleware
# =========================================================================
class _SlidingWindowLimiter:
    """内存滑动窗口限流器

    线程安全说明: 单进程 GIL 保护足够, 多进程需替换为 Redis。
    """

    def __init__(self):
        self._buckets = defaultdict(deque)
        self._last_cleanup = time.time()

    def _cleanup_all(self):
        """周期性清理过期桶 (每 5 分钟)"""
        now = time.time()
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now
        stale_keys = []
        for key, dq in self._buckets.items():
            cutoff = now - 600
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                stale_keys.append(key)
        for k in stale_keys:
            del self._buckets[k]

    def check(self, key, limit, window_seconds):
        """检查是否允许请求

        返回: (allowed: bool, remaining: int, retry_after: int)
        """
        self._cleanup_all()
        now = time.time()
        cutoff = now - window_seconds
        dq = self._buckets[key]

        while dq and dq[0] < cutoff:
            dq.popleft()

        if len(dq) >= limit:
            retry_after = int(dq[0] + window_seconds - now) + 1
            return False, 0, max(retry_after, 1)

        dq.append(now)
        return True, limit - len(dq), 0


_limiter = _SlidingWindowLimiter()


class RateLimitMiddleware:
    """Django 限流中间件

    默认规则:
      - /api/v1/auth/login: 5 次 / 60 秒 (按 IP)
      - 其他端点: 不限流

    可通过 RATE_LIMIT_RULES 配置自定义规则。
    """

    # 默认限流规则: {url_name: (limit, window_seconds)}
    DEFAULT_RULES = {
        'api_v1_login': (5, 60),
    }

    def __init__(self, get_response):
        self.get_response = get_response
        self.rules = getattr(settings, 'RATE_LIMIT_RULES', self.DEFAULT_RULES)

    def __call__(self, request):
        try:
            url_name = resolve(request.path_info).url_name
        except Exception:
            url_name = None

        rule = self.rules.get(url_name) if url_name else None
        if rule is None:
            return self.get_response(request)

        limit, window_seconds = rule
        client_ip = self._get_client_ip(request)
        bucket_key = f'{url_name}:ip:{client_ip}'

        allowed, remaining, retry_after = _limiter.check(
            bucket_key, limit, window_seconds
        )

        if not allowed:
            resp = JsonResponse(
                {
                    'error': f'请求过于频繁, 请 {retry_after} 秒后重试',
                    'retry_after': retry_after,
                },
                status=429,
            )
            resp['Retry-After'] = str(retry_after)
            resp['X-RateLimit-Limit'] = str(limit)
            resp['X-RateLimit-Remaining'] = '0'
            return resp

        response = self.get_response(request)
        response['X-RateLimit-Limit'] = str(limit)
        response['X-RateLimit-Remaining'] = str(remaining)
        return response

    @staticmethod
    def _get_client_ip(request):
        """获取真实客户端 IP"""
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')


# =========================================================================
# CSRFMiddleware
# =========================================================================
class CSRFMiddleware:
    """Django 自定义 CSRF 中间件

    与 Flask 版本 security.py 的 CSRF 保护逻辑一致:
      - 安全方法 (GET/HEAD/OPTIONS) 跳过
      - API Key 请求 (Authorization/X-API-Key 头) 跳过
      - 登录/登出/静态文件端点跳过
      - 其余 POST/PUT/DELETE/PATCH 必须带有效 token
      - Token 来源: form 字段 'csrf_token', header 'X-CSRFToken' 或 'csrf_token'
    """

    _CSRF_SESSION_KEY = '_csrf_token'
    _SAFE_METHODS = frozenset(['GET', 'HEAD', 'OPTIONS', 'TRACE'])

    # 豁免 CSRF 检查的端点名称
    _EXEMPT_NAMES = {
        'login',
        'logout',
        'api_v1_login',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 安全方法豁免
        if request.method in self._SAFE_METHODS:
            return self.get_response(request)

        # API Key 请求豁免
        if self._is_api_key_request(request):
            return self.get_response(request)

        # 端点豁免
        try:
            url_name = resolve(request.path_info).url_name
        except Exception:
            url_name = None

        if url_name in self._EXEMPT_NAMES:
            return self.get_response(request)

        # 静态文件豁免
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return self.get_response(request)

        # 验证 CSRF token
        token = (
            request.POST.get('csrf_token')
            or request.META.get('HTTP_X_CSRFTOKEN')
            # Backward compatibility for old clients.
            or request.META.get('HTTP_X_CSRF_TOKEN')
            or request.META.get('HTTP_CSRF_TOKEN')
        )
        expected = request.session.get(self._CSRF_SESSION_KEY)

        if not expected or not token or token != expected:
            import logging
            logger = logging.getLogger('django.security.csrf')
            logger.warning(
                '[CSRF] 拒绝请求: path=%s ip=%s',
                request.path,
                request.META.get('REMOTE_ADDR', 'unknown'),
            )
            return JsonResponse(
                {'error': 'CSRF 校验失败, 请刷新页面后重试'},
                status=400,
            )

        return self.get_response(request)

    @staticmethod
    def _is_api_key_request(request):
        """判断是否 API Key 请求"""
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            return True
        if request.META.get('HTTP_X_API_KEY'):
            return True
        return False