"""安全模块: CSRF 保护 / Rate Limiting / 密码策略

设计原则:
  - 零外部依赖 (不引入 Flask-WTF / Flask-Limiter, 避免 Redis 依赖)
  - API Key 请求豁免 CSRF (自动化场景用 Authorization 头, 浏览器同源策略已防护)
  - 内存计数器, 适合单实例部署; 多实例需替换为 Redis
"""
import hashlib
import hmac
import re
import time
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps

from flask import current_app, request, session, g, jsonify


# =========================================================================
# CSRF 保护
# =========================================================================

_CSRF_FIELD = 'csrf_token'
_CSRF_HEADER = 'X-CSRF-Token'
_CSRF_SESSION_KEY = '_csrf_token'
# 豁免的方法 (GET/HEAD/OPTIONS 只读, 无需 CSRF)
_SAFE_METHODS = frozenset(['GET', 'HEAD', 'OPTIONS', 'TRACE'])


def _secret_key():
    return current_app.config['SECRET_KEY'].encode('utf-8')


def generate_csrf_token():
    """生成/获取当前会话的 CSRF token

    使用 HMAC(secret, session_id || random) 派生, 不依赖额外存储。
    token 绑定到 session, 退出登录后失效。
    """
    token = session.get(_CSRF_SESSION_KEY)
    if token:
        return token
    # 基于 secret + 时间戳 + session sid 生成 (sid 由 flask 自动管理)
    sid = session.get('_sid', '') or str(int(time.time() * 1000))
    raw = f'{sid}:{time.time()}'.encode('utf-8')
    token = hmac.new(_secret_key(), raw, hashlib.sha256).hexdigest()
    session[_CSRF_SESSION_KEY] = token
    # 强制写入 session (确保 cookie 下发)
    session.permanent = True
    return token


def _is_api_key_request():
    """判断当前请求是否通过 API Key 认证 (豁免 CSRF)"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return True
    if request.headers.get('X-API-Key'):
        return True
    return False


def csrf_protect():
    """CSRF 校验 (作为 before_request hook 调用)

    规则:
      - 安全方法 (GET/HEAD/OPTIONS) 跳过
      - API Key 请求 (Authorization/X-API-Key 头) 跳过
      - /api/auth/login 等无 session 端点跳过
      - 其余 POST/PUT/DELETE/PATCH 必须带有效 token
    """
    if request.method in _SAFE_METHODS:
        return None

    # API Key 调用豁免
    if _is_api_key_request():
        return None

    # 登录端点豁免 (此时还没有 session, token 由前端从 meta 读取)
    # 注: 登录端点的 CSRF 通过 SameSite cookie + Origin 校验防护
    if request.endpoint in ('login', 'logout'):
        return None

    # 静态资源豁免
    if request.endpoint == 'static':
        return None

    token = (
        request.form.get(_CSRF_FIELD)
        or request.headers.get(_CSRF_HEADER)
        or request.headers.get(_CSRF_FIELD)
    )
    expected = session.get(_CSRF_SESSION_KEY)

    if not expected or not token or not hmac.compare_digest(str(token), str(expected)):
        current_app.logger.warning(
            '[CSRF] 拒绝请求: endpoint=%s path=%s ip=%s',
            request.endpoint, request.path, request.remote_addr
        )
        return jsonify({'error': 'CSRF 校验失败, 请刷新页面后重试'}), 400

    return None


def init_csrf(app):
    """初始化 CSRF: 注入模板全局变量"""
    app.jinja_env.globals['csrf_token'] = generate_csrf_token
    app.jinja_env.globals['csrf_field'] = lambda: (
        f'<input type="hidden" name="{_CSRF_FIELD}" value="{generate_csrf_token()}">'
    )


# =========================================================================
# Rate Limiting (内存滑动窗口)
# =========================================================================

class _RateLimiter:
    """内存滑动窗口限流器

    线程安全说明: 使用 GIL 保护简单 deque 操作, 单进程足够。
    多进程部署需替换为 Redis。
    """

    def __init__(self):
        # key -> deque[timestamps]
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
            # 保留最近 10 分钟的数据
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

        # 清除窗口外
        while dq and dq[0] < cutoff:
            dq.popleft()

        if len(dq) >= limit:
            # 计算最早一条到期时间
            retry_after = int(dq[0] + window_seconds - now) + 1
            return False, 0, max(retry_after, 1)

        dq.append(now)
        return True, limit - len(dq), 0


_limiter = _RateLimiter()


def rate_limit(limit, window_seconds=60, key_func=None):
    """装饰器: 对单个端点限流

    参数:
      limit: 窗口内最大请求数
      window_seconds: 窗口大小 (秒)
      key_func: 自定义 key 函数, 默认按 IP

    使用:
      @app.route('/login', methods=['POST'])
      @rate_limit(5, 60)  # 每 IP 每分钟 5 次
      def login(): ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if key_func:
                k = key_func()
            else:
                k = f'ip:{request.remote_addr}'
            bucket_key = f'{f.__name__}:{k}'
            allowed, remaining, retry_after = _limiter.check(
                bucket_key, limit, window_seconds
            )
            if not allowed:
                resp = jsonify({
                    'error': f'请求过于频繁, 请 {retry_after} 秒后重试',
                    'retry_after': retry_after,
                })
                resp.status_code = 429
                resp.headers['Retry-After'] = str(retry_after)
                resp.headers['X-RateLimit-Limit'] = str(limit)
                resp.headers['X-RateLimit-Remaining'] = '0'
                return resp

            resp = current_app.make_response(f(*args, **kwargs))
            if hasattr(resp, 'headers'):
                resp.headers['X-RateLimit-Limit'] = str(limit)
                resp.headers['X-RateLimit-Remaining'] = str(remaining)
            return resp
        return wrapped
    return decorator


def get_client_ip():
    """获取真实客户端 IP (考虑反代)"""
    # 信任 X-Forwarded-For 第一个 (部署在反代后时)
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or 'unknown'


# =========================================================================
# 密码策略
# =========================================================================

# 默认策略: 至少 8 位, 包含字母和数字 (商用基线)
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
    # 禁止明显弱口令
    weak = {'12345678', 'password', 'password1', 'admin123',
            'qwerty123', '11111111', '00000000'}
    if password.lower() in weak:
        return False, '密码强度不足, 请避免常见弱口令'
    return True, None


def is_default_admin_password_weak():
    """启动检查: admin 账户是否仍使用出厂默认密码

    用于启动时打印警告, 不阻止启动。
    检测两个历史版本的默认密码:
      - 旧版: admin123 (已废弃, 不符合新密码策略)
      - 新版: admin@2026 (当前默认, 首次登录后应立即修改)
    """
    try:
        from models import User
        admin = User.query.filter_by(username='admin').first()
        if admin and (
            admin.check_password('admin123') or
            admin.check_password('admin@2026')
        ):
            return True
    except Exception:
        pass
    return False
