"""安全模块: CSRF 保护 / Rate Limiting / 密码策略

Django 版本, 与 Flask security.py 功能一致。

设计原则:
  - 零外部依赖 (不引入 django-axes / django-ratelimit, 避免 Redis 依赖)
  - API Key 请求豁免 CSRF (自动化场景用 Authorization 头, 浏览器同源策略已防护)
  - 内存计数器, 适合单实例部署; 多实例需替换为 Redis
"""
import hashlib
import hmac
import re
import time
from collections import defaultdict, deque
from functools import wraps

from django.conf import settings
from django.http import JsonResponse


# =========================================================================
# CSRF 保护
# =========================================================================

_CSRF_FIELD = 'csrf_token'
_CSRF_HEADER = 'X-CSRF-Token'
_CSRF_SESSION_KEY = '_csrf_token'
_SAFE_METHODS = frozenset(['GET', 'HEAD', 'OPTIONS', 'TRACE'])


def _secret_key():
    """获取 Django SECRET_KEY 的 bytes 形式"""
    return settings.SECRET_KEY.encode('utf-8') if isinstance(settings.SECRET_KEY, str) else settings.SECRET_KEY


def generate_csrf_token(request):
    """生成/获取当前会话的 CSRF token

    使用 HMAC(secret, session_key || random) 派生, 不依赖额外存储。
    token 绑定到 session, 退出登录后失效。
    """
    token = request.session.get(_CSRF_SESSION_KEY)
    if token:
        return token

    session_key = request.session.session_key or ''
    if not session_key:
        # 确保 session 已创建
        request.session.save()
        session_key = request.session.session_key or ''

    raw = f'{session_key}:{time.time()}'.encode('utf-8')
    token = hmac.new(_secret_key(), raw, hashlib.sha256).hexdigest()
    request.session[_CSRF_SESSION_KEY] = token
    return token


def _is_api_key_request(request):
    """判断当前请求是否通过 API Key 认证 (豁免 CSRF)"""
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        return True
    if request.META.get('HTTP_X_API_KEY'):
        return True
    return False


def csrf_protect(request):
    """CSRF 校验 (作为视图装饰器或手动调用)

    规则:
      - 安全方法 (GET/HEAD/OPTIONS) 跳过
      - API Key 请求 (Authorization/X-API-Key 头) 跳过
      - /api/auth/login 等无 session 端点跳过
      - 其余 POST/PUT/DELETE/PATCH 必须带有效 token

    返回:
      None 表示通过, 否则返回 JsonResponse (400)
    """
    if request.method in _SAFE_METHODS:
        return None

    # API Key 调用豁免
    if _is_api_key_request(request):
        return None

    # 登录/登出端点豁免
    from django.urls import resolve
    try:
        url_name = resolve(request.path_info).url_name
    except Exception:
        url_name = None

    if url_name in ('login', 'logout', 'api_v1_login'):
        return None

    # 静态资源豁免
    if request.path.startswith('/static/') or request.path.startswith('/media/'):
        return None

    token = (
        request.POST.get(_CSRF_FIELD)
        or request.META.get(f'HTTP_{_CSRF_HEADER.replace("-", "_").upper()}')
        or request.META.get(f'HTTP_{_CSRF_FIELD.upper()}')
    )
    expected = request.session.get(_CSRF_SESSION_KEY)

    if not expected or not token or not hmac.compare_digest(str(token), str(expected)):
        import logging
        logger = logging.getLogger('django.security.csrf')
        logger.warning(
            '[CSRF] 拒绝请求: path=%s ip=%s',
            request.path,
            request.META.get('REMOTE_ADDR', 'unknown'),
        )
        return JsonResponse({'error': 'CSRF 校验失败, 请刷新页面后重试'}, status=400)

    return None


def init_csrf(app=None):
    """初始化 CSRF: 注入模板全局变量

    在 Django 中, 通过 context_processors 实现, 而非直接操作 jinja_env。
    此函数作为兼容入口, 实际使用需在 settings.TEMPLATES 中配置
    context_processors。
    """
    pass


def csrf_context_processor(request):
    """Django 模板 context processor: 注入 CSRF token 到模板上下文"""
    return {
        'csrf_token': generate_csrf_token(request),
        'csrf_field': (
            f'<input type="hidden" name="{_CSRF_FIELD}" '
            f'value="{generate_csrf_token(request)}">'
        ),
    }


# =========================================================================
# Rate Limiting (内存滑动窗口)
# =========================================================================

class _RateLimiter:
    """内存滑动窗口限流器

    线程安全说明: 使用 GIL 保护简单 deque 操作, 单进程足够。
    多进程部署需替换为 Redis。
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

        返回:
          (allowed: bool, remaining: int, retry_after: int)
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


_limiter = _RateLimiter()


def rate_limit(limit, window_seconds=60, key_func=None):
    """装饰器: 对 Django 视图函数限流

    参数:
      limit: 窗口内最大请求数
      window_seconds: 窗口大小 (秒)
      key_func: 自定义 key 函数, 接收 request 参数, 默认按 IP

    使用:
      @rate_limit(5, 60)
      def login_view(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if key_func:
                k = key_func(request)
            else:
                k = f'ip:{get_client_ip(request)}'
            bucket_key = f'{view_func.__name__}:{k}'
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

            response = view_func(request, *args, **kwargs)
            if hasattr(response, '__setitem__'):
                response['X-RateLimit-Limit'] = str(limit)
                response['X-RateLimit-Remaining'] = str(remaining)
            return response
        return wrapped
    return decorator


def get_client_ip(request):
    """获取真实客户端 IP (考虑反代)"""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


# =========================================================================
# 密码策略
# =========================================================================

PASSWORD_MIN_LENGTH = 8
PASSWORD_REQUIRE_LETTER = True
PASSWORD_REQUIRE_DIGIT = True


def validate_password(password):
    """校验密码强度

    返回:
      (ok: bool, error: str|None)
    """
    if not password:
        return False, '密码不能为空'
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f'密码至少 {PASSWORD_MIN_LENGTH} 位'
    if PASSWORD_REQUIRE_LETTER and not re.search(r'[A-Za-z]', password):
        return False, '密码必须包含字母'
    if PASSWORD_REQUIRE_DIGIT and not re.search(r'\d', password):
        return False, '密码必须包含数字'

    weak = {'12345678', 'password', 'password1', 'admin123',
            'qwerty123', '11111111', '00000000'}
    if password.lower() in weak:
        return False, '密码强度不足, 请避免常见弱口令'
    return True, None


def is_default_admin_password_weak():
    """启动检查: admin 账户是否仍使用出厂默认密码

    检测两个历史版本的默认密码:
      - 旧版: admin123 (已废弃)
      - 新版: admin@2026 (当前默认)
    """
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        admin = User.objects.filter(username='admin').first()
        if admin and (
            admin.check_password('admin123') or
            admin.check_password('admin@2026')
        ):
            return True
    except Exception:
        pass
    return False


def check_secret_key():
    """检查 SECRET_KEY 是否仍是默认值 (生产环境拒绝启动)"""
    sk = settings.SECRET_KEY
    default = getattr(settings, '_DEFAULT_SECRET_KEY', 'qor-recorder-dev-key-change-in-prod')
    enforce = getattr(settings, 'ENFORCE_SECRET_KEY', True)
    is_default = (sk == default) or not sk

    if not is_default:
        return

    if settings.DEBUG:
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