"""Django settings for QoR Recorder.

数据库后端支持 (通过单一变量 DB_TYPE 切换):
  - DB_TYPE=sqlite   (默认)  本地文件, WAL 模式, 零运维
  - DB_TYPE=sql      MySQL / MariaDB / PostgreSQL (需要 DATABASE_URL)
  - DB_TYPE=mongodb  MongoDB (走 dual-write, 兼容 SQLite 只读回退)

切换方式 (推荐):
  1. 设置环境变量 DB_TYPE (sqlite / sql / mongodb)
  2. 对应设置 DATABASE_URL (sql) 或 MONGODB_URI (mongodb)

配置加载顺序 (优先级从高到低):
  1. 系统环境变量
  2. .env 文件 (若存在, 自动加载, 无需第三方依赖)
  3. 内置默认值
"""
import os
from pathlib import Path

# ===========================================================================
# 项目路径
# ===========================================================================
BASE_DIR = Path(__file__).resolve().parent  # django_app/
PARENT_DIR = BASE_DIR.parent  # QoR_Recorder/

# ===========================================================================
# 数据目录 (运行时数据库/备份/上传文件, 与源代码目录隔离)
# ===========================================================================
_DATA_DIR = os.environ.get('DATA_DIR', '').strip()
if _DATA_DIR:
    DATA_DIR = Path(_DATA_DIR).resolve()
else:
    DATA_DIR = PARENT_DIR / 'data'

UPLOAD_FOLDER = str(Path(
    os.environ.get('UPLOAD_FOLDER', str(DATA_DIR / 'uploads'))
).resolve())
BACKUP_DIR = str(Path(
    os.environ.get('BACKUP_DIR', str(DATA_DIR / 'backups'))
).resolve())
AUTO_BACKUP_ENABLED = os.environ.get('AUTO_BACKUP_ENABLED', '0') == '1'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# ===========================================================================
# 支持的数据库类型常量
# ===========================================================================
DB_TYPE_SQLITE = 'sqlite'
DB_TYPE_SQL = 'sql'
DB_TYPE_MONGODB = 'mongodb'
SUPPORTED_DB_TYPES = (DB_TYPE_SQLITE, DB_TYPE_SQL, DB_TYPE_MONGODB)


# ===========================================================================
# .env 文件加载
# ===========================================================================
def _load_dotenv():
    """加载 .env 文件 (轻量实现, 不依赖 python-dotenv)

    仅当 .env 存在时加载, 不覆盖已存在的环境变量。
    """
    env_path = PARENT_DIR / '.env'
    if not env_path.is_file():
        return
    try:
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


_load_dotenv()

# ====== JSON 响应补丁开始 ======
# 默认 ensure_ascii=False，避免 API JSON 把中文转义成 \uXXXX，便于阅读/排查。
# 放在 dotenv 之后、应用导入之前：视图随后 from django.http import JsonResponse 会拿到补丁类。
import django.http
import django.http.response
from django.http import JsonResponse as _OriginJsonResponse


class PatchedJsonResponse(_OriginJsonResponse):
    """全局 JsonResponse：默认 ensure_ascii=False（仍可用 json_dumps_params 覆盖）。"""

    def __init__(self, *args, **kwargs):
        params = kwargs.get('json_dumps_params')
        if params is None:
            kwargs['json_dumps_params'] = {'ensure_ascii': False}
        else:
            params.setdefault('ensure_ascii', False)
        super().__init__(*args, **kwargs)


django.http.response.JsonResponse = PatchedJsonResponse
django.http.JsonResponse = PatchedJsonResponse
# ====== 补丁结束 ======

# A directory upload commonly contains one CSV per module. Django's default
# limit is 100 uploaded files, which rejects the request before the preview
# view can report per-file validation errors.
DATA_UPLOAD_MAX_NUMBER_FILES = int(
    os.environ.get('DATA_UPLOAD_MAX_NUMBER_FILES', '500')
)


# ===========================================================================
# 数据库类型检测
# ===========================================================================
def _detect_db_type():
    """根据 DB_TYPE 或 DATABASE_URL 自动推导数据库类型"""
    explicit = os.environ.get('DB_TYPE', '').strip().lower()
    if explicit in SUPPORTED_DB_TYPES:
        return explicit
    url = os.environ.get('DATABASE_URL', '').strip().lower()
    if url.startswith('sqlite'):
        return DB_TYPE_SQLITE
    if url.startswith(('mysql', 'postgresql', 'postgres')):
        return DB_TYPE_SQL
    if url.startswith('mongodb'):
        return DB_TYPE_MONGODB
    return DB_TYPE_SQLITE


DB_TYPE = _detect_db_type()

# ===========================================================================
# Django 安全
# ===========================================================================
SECRET_KEY = os.environ.get('SECRET_KEY', 'qor-recorder-dev-key-change-in-prod')
_DEFAULT_SECRET_KEY = 'qor-recorder-dev-key-change-in-prod'

DEBUG = os.environ.get('DEBUG', '0') == '1'

# 内网部署默认放开 Host 头；生产可改回环境变量白名单。
ALLOWED_HOSTS = ["*"]
# ALLOWED_HOSTS = [
#     value.strip()
#     for value in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
#     if value.strip()
# ]

# ===========================================================================
# 应用定义
# ===========================================================================
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_app.core',
    'django_app.api',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # 自定义中间件
    'django_app.core.middleware.SecurityMiddleware',
    'django_app.core.middleware.RateLimitMiddleware',
    'django_app.core.db_routing.ProjectContextMiddleware',
]

ROOT_URLCONF = 'django_app.urls'

WSGI_APPLICATION = 'django_app.wsgi.application'

# ===========================================================================
# 模板
# ===========================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [str(BASE_DIR / 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django_app.core.context_processors.settings_context',
            ],
        },
    },
]

# ===========================================================================
# 数据库
# ===========================================================================
def _build_database_config():
    """构建 Django DATABASES 配置"""
    if DB_TYPE == DB_TYPE_MONGODB:
        return {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': str(DATA_DIR / 'qor_recorder.db'),
            },
        }
    if DB_TYPE == DB_TYPE_SQLITE:
        return {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': str(DATA_DIR / 'qor_recorder.db'),
                'OPTIONS': {
                    'timeout': 30,
                },
            },
        }
    # DB_TYPE == 'sql'
    uri = os.environ.get('DATABASE_URL', '').strip()
    if not uri:
        raise RuntimeError(
            'DB_TYPE=sql 需要设置 DATABASE_URL 环境变量'
        )
    if uri.startswith('mysql://'):
        uri = uri.replace('mysql://', 'mysql+pymysql://', 1)
    if uri.startswith('postgres://'):
        uri = uri.replace('postgres://', 'postgresql+psycopg2://', 1)

    # 解析 DATABASE_URL
    import re
    m = re.match(
        r'^(?P<engine>[\w+]+)://(?:(?P<user>[^:@]+)?(?::(?P<password>[^@]+))?@)?(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<name>[^?]+)',
        uri,
    )
    if m:
        engine = m.group('engine')
        if 'postgresql' in engine:
            django_engine = 'django.db.backends.postgresql'
        elif 'mysql' in engine:
            django_engine = 'django.db.backends.mysql'
        else:
            django_engine = 'django.db.backends.sqlite3'
        return {
            'default': {
                'ENGINE': django_engine,
                'NAME': m.group('name'),
                'USER': m.group('user') or '',
                'PASSWORD': m.group('password') or '',
                'HOST': m.group('host') or 'localhost',
                'PORT': m.group('port') or '',
            },
        }
    return {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(DATA_DIR / 'qor_recorder.db'),
        },
    }


DATABASES = _build_database_config()

# 数据库路由
DATABASE_ROUTERS = ['django_app.core.db_routing.ProjectRouter']

# ===========================================================================
# 认证
# ===========================================================================
AUTH_USER_MODEL = 'core.User'
LOGIN_URL = '/login/'

# ===========================================================================
# Session / Cookie 安全配置
# ===========================================================================
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = int(os.environ.get('SESSION_LIFETIME_HOURS', '12')) * 3600
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', '0') == '1'
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.environ.get('SECURE_HSTS_INCLUDE_SUBDOMAINS', '0') == '1'
)
SECURE_HSTS_PRELOAD = os.environ.get('SECURE_HSTS_PRELOAD', '0') == '1'

# ===========================================================================
# CSRF
# ===========================================================================
# Django's documented AJAX contract reads this non-secret cookie and echoes it
# in X-CSRFToken. The authenticated session cookie remains HttpOnly.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
# Django expects browser clients to send the cookie token as X-CSRFToken.
CSRF_HEADER_NAME = 'HTTP_X_CSRFTOKEN'
CSRF_TRUSTED_ORIGINS = [
    value.strip()
    for value in os.environ.get(
        'CSRF_TRUSTED_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173,http://10.150.58.192:8888',
    ).split(',')
    if value.strip()
]
# Trust only the proxy's scheme header; production ingress must overwrite it.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ===========================================================================
# 静态文件 / 媒体文件
# ===========================================================================
STATIC_URL = '/static/'
# collectstatic 输出目录 (生产部署用)
STATIC_ROOT = str(PARENT_DIR / 'staticfiles')
# 开发环境直接从源码目录提供静态文件 (echarts 等 vendor 资源)
STATICFILES_DIRS = [str(PARENT_DIR / 'static')]
MEDIA_URL = '/uploads/'
MEDIA_ROOT = UPLOAD_FOLDER

# ===========================================================================
# 数据库可视化
# ===========================================================================
ENABLE_DB_ADMIN = os.environ.get('ENABLE_DB_ADMIN', '0') == '1'
DB_ADMIN_SERVER = os.environ.get('DB_ADMIN_SERVER', 'localhost')
DB_ADMIN_NAME = os.environ.get('DB_ADMIN_NAME', 'qor_recorder')

# ===========================================================================
# 服务器监听
# ===========================================================================
HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '5000'))

# ===========================================================================
# 安全开关
# ===========================================================================
ENFORCE_SECRET_KEY = os.environ.get('ENFORCE_SECRET_KEY', '1') == '1'

# ===========================================================================
# MongoDB 配置
# ===========================================================================
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017')
MONGODB_DB = os.environ.get('MONGODB_DB', 'qor_recorder')
MONGODB_DATA_DIR = Path(
    os.environ.get('MONGODB_DATA_DIR', str(PARENT_DIR / 'mongodbdir'))
).resolve()
MONGODB_TIMEOUT_MS = int(os.environ.get('MONGODB_TIMEOUT_MS', '2000'))

# orm: project SQLite only; mongo: Mongo only; hybrid: Mongo-first with ORM
# fallback. DB_TYPE remains accepted for legacy deployments.
_default_persistence = 'hybrid' if DB_TYPE == DB_TYPE_MONGODB else 'orm'
PERSISTENCE_MODE = os.environ.get('PERSISTENCE_MODE', _default_persistence).strip().lower()
if PERSISTENCE_MODE not in ('orm', 'mongo', 'hybrid'):
    raise RuntimeError('PERSISTENCE_MODE must be orm, mongo, or hybrid')

# Deployment cutover marker. Nginx serves Vue by default while the legacy
# server-rendered dashboard remains reachable at /legacy/dashboard/.
FRONTEND_MODE = os.environ.get('FRONTEND_MODE', 'vue').strip().lower()
if FRONTEND_MODE not in ('vue', 'legacy'):
    raise RuntimeError('FRONTEND_MODE must be vue or legacy')
FRONTEND_URL = os.environ.get('FRONTEND_URL', '/').strip() or '/'
# Vue 构建产物目录 (轻量单服务部署时由 Django 直接托管)
FRONTEND_DIST_DIR = Path(
    os.environ.get('FRONTEND_DIST', str(PARENT_DIR.parent / 'frontend-vue' / 'dist'))
).resolve()

# ===========================================================================
# 日志
# DEBUG=1 时默认 DEBUG 级别；可用 LOG_LEVEL 覆盖 (DEBUG/INFO/WARNING/ERROR)
# Linux/systemd 下控制台日志在 journalctl；同时写入 LOG_DIR/qor_recorder.log
# ===========================================================================
_VALID_LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
_log_level_env = os.environ.get('LOG_LEVEL', '').strip().upper()
if _log_level_env in _VALID_LOG_LEVELS:
    LOG_LEVEL = _log_level_env
else:
    LOG_LEVEL = 'DEBUG' if DEBUG else 'INFO'

_LOG_DIR_ENV = os.environ.get('LOG_DIR', '').strip()
LOG_DIR = Path(_LOG_DIR_ENV).resolve() if _LOG_DIR_ENV else (PARENT_DIR / 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = str(LOG_DIR / 'qor_recorder.log')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '[%(asctime)s] %(levelname)s %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_FILE,
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'encoding': 'utf-8',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'django_app': {
            'handlers': ['console', 'file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'gunicorn': {
            'handlers': ['console', 'file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}

# ===========================================================================
# 国际化
# ===========================================================================
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# ===========================================================================
# 默认主键
# ===========================================================================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'