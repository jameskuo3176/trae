"""应用配置

数据库后端支持 (通过单一变量 DB_TYPE 切换):
  - DB_TYPE=sqlite   (默认)  本地文件, WAL 模式, 零运维
  - DB_TYPE=sql      MySQL / MariaDB / PostgreSQL (需要 DATABASE_URL)
  - DB_TYPE=mongodb  MongoDB (走 dual-write, 兼容 SQLite 只读回退)

切换方式 (推荐):
  1. 设置环境变量 DB_TYPE (sqlite / sql / mongodb)
  2. 对应设置 DATABASE_URL (sql) 或 MONGODB_URI (mongodb)
  3. 执行 python db_init.py 自动建库/迁移

兼容旧方式: 直接设置 DATABASE_URL (不带 DB_TYPE) 也能工作, 会根据 URI 前缀自动推导 DB_TYPE.

可视化:
  设置环境变量 ENABLE_DB_ADMIN=1 启用内置 Adminer (数据库 Web 可视化, 仅 sql/sqlite)

配置加载顺序 (优先级从高到低):
  1. 系统环境变量
  2. .env 文件 (若存在, 自动加载, 无需第三方依赖)
  3. 内置默认值
"""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# 支持的数据库类型常量
# ---------------------------------------------------------------------------
DB_TYPE_SQLITE = 'sqlite'
DB_TYPE_SQL = 'sql'      # MySQL / MariaDB / PostgreSQL
DB_TYPE_MONGODB = 'mongodb'
SUPPORTED_DB_TYPES = (DB_TYPE_SQLITE, DB_TYPE_SQL, DB_TYPE_MONGODB)


def _load_dotenv():
    """加载 .env 文件 (轻量实现, 不依赖 python-dotenv)

    仅当 .env 存在时加载, 不覆盖已存在的环境变量。
    """
    env_path = os.path.join(BASE_DIR, '.env')
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行、注释
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip()
                # 去除引号
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                # 不覆盖已存在的环境变量
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass  # .env 加载失败不影响启动


_load_dotenv()


def _detect_db_type():
    """根据 DB_TYPE 或 DATABASE_URL 自动推导数据库类型

    优先级:
      1. 环境变量 DB_TYPE (sqlite / sql / mongodb)
      2. 根据 DATABASE_URL 前缀推导 (sqlite://, mysql://, postgresql://, mongodb://)
      3. 默认 sqlite
    """
    explicit = os.environ.get('DB_TYPE', '').strip().lower()
    if explicit in SUPPORTED_DB_TYPES:
        return explicit
    # 没有显式 DB_TYPE: 根据 URI 推导
    url = os.environ.get('DATABASE_URL', '').strip().lower()
    if url.startswith('sqlite'):
        return DB_TYPE_SQLITE
    if url.startswith(('mysql', 'postgresql', 'postgres')):
        return DB_TYPE_SQL
    if url.startswith('mongodb'):
        return DB_TYPE_MONGODB
    # 都没有: 默认 sqlite
    return DB_TYPE_SQLITE


def _build_database_uri(db_type=None):
    """构建 SQLAlchemy 数据库 URI

    参数:
      db_type: 可显式指定类型, 默认为自动推导

    行为:
      - db_type='sqlite' (默认)  -> sqlite:///<BASE_DIR>/qor_recorder.db
      - db_type='sql'            -> 必须设置 DATABASE_URL, 否则报错
      - db_type='mongodb'        -> 返回 None (SQLAlchemy 不直连, 见 db_mongo module)
    """
    if db_type is None:
        db_type = _detect_db_type()
    if db_type == DB_TYPE_MONGODB:
        # MongoDB 不走 SQLAlchemy, 返回 None
        return None
    if db_type == DB_TYPE_SQLITE:
        return 'sqlite:///' + os.path.join(BASE_DIR, 'qor_recorder.db')
    # db_type == 'sql'
    uri = os.environ.get('DATABASE_URL', '').strip()
    if not uri:
        raise RuntimeError(
            'DB_TYPE=sql 需要设置 DATABASE_URL 环境变量, 例如:\n'
            '  MySQL:    mysql+pymysql://user:password@localhost:3306/qor_recorder?charset=utf8mb4\n'
            '  Postgres: postgresql+psycopg2://user:password@localhost:5432/qor_recorder'
        )
    # 兼容 mysql:// 简写 (SQLAlchemy 需要 mysql+pymysql://)
    if uri.startswith('mysql://'):
        uri = uri.replace('mysql://', 'mysql+pymysql://', 1)
    if uri.startswith('postgres://'):
        uri = uri.replace('postgres://', 'postgresql+psycopg2://', 1)
    return uri


def _build_mongo_config(db_type=None):
    """构建 MongoDB 连接配置

    返回 dict: {uri, db_name, enabled}
    """
    if db_type is None:
        db_type = _detect_db_type()
    if db_type != DB_TYPE_MONGODB:
        return {'uri': None, 'db_name': None, 'enabled': False}
    uri = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017').strip()
    db_name = os.environ.get('MONGODB_DB', 'qor_recorder').strip()
    return {'uri': uri, 'db_name': db_name, 'enabled': True}


def _is_sqlite():
    return _detect_db_type() == DB_TYPE_SQLITE


def _is_sql():
    return _detect_db_type() == DB_TYPE_SQL


def _is_mongodb():
    return _detect_db_type() == DB_TYPE_MONGODB


class Config:
    # =========================================================================
    # 数据库后端 (通过 DB_TYPE 切换)
    # =========================================================================
    DB_TYPE = _detect_db_type()  # sqlite / sql / mongodb
    MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017')
    MONGODB_DB = os.environ.get('MONGODB_DB', 'qor_recorder')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    @classmethod
    def _resolve_uri(cls):
        """延迟解析 SQLAlchemy URI (避免类定义时因 DB_TYPE=sql 但缺 DATABASE_URL 而抛错)"""
        try:
            return _build_database_uri() or (
                'sqlite:///' + os.path.join(BASE_DIR, 'qor_recorder.db')
            )
        except RuntimeError as e:
            # 启动时会在 app.py 再次检查, 这里先返回 None 让用户明确看到错误
            print(f'[CONFIG] 警告: {e}', flush=True)
            return None

    # 使用 property 形式, 让 SQLAlchemy 延后到第一次访问时才校验
    # Flask-SQLAlchemy 会在工厂里调用 config['SQLALCHEMY_DATABASE_URI']
    # 那里再校验并给出友好错误
    pass  # 占位: 实际属性在类外通过 __class_getitem__ / metaclass 注入

    # 连接池与并发优化
    if _is_sqlite():
        # SQLite: 启用 WAL 模式解决读写并发, 设置 busy_timeout 避免锁等待失败
        SQLALCHEMY_ENGINE_OPTIONS = {
            'connect_args': {
                'timeout': 30,  # busy_timeout (秒), 写入冲突时等待
                'check_same_thread': False,  # 允许多线程共享连接
            },
            'pool_pre_ping': True,  # 连接前检测有效性
            'pool_recycle': 3600,
        }
    else:
        # MySQL/PostgreSQL: 连接池配置, 支持高并发
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 10,  # 持久连接数
            'max_overflow': 20,  # 超出 pool_size 的最大临时连接
            'pool_timeout': 30,  # 获取连接超时 (秒)
            'pool_recycle': 1800,  # 连接回收周期 (秒), MySQL 默认 wait_timeout=28800
            'pool_pre_ping': True,  # 连接前检测, 避免 "MySQL server has gone away"
        }

    # 密钥
    SECRET_KEY = os.environ.get('SECRET_KEY', 'qor-recorder-dev-key-change-in-prod')

    # 默认密钥指纹 (用于检测是否仍是出厂默认值)
    _DEFAULT_SECRET_KEY = 'qor-recorder-dev-key-change-in-prod'

    # 文件上传
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # 允许的文件扩展名
    ALLOWED_EXTENSIONS = {'csv'}

    # 数据库可视化 (Adminer)
    ENABLE_DB_ADMIN = os.environ.get('ENABLE_DB_ADMIN', '0') == '1'

    # MySQL 连接信息 (仅用于 Adminer 自动填充, 可选)
    DB_ADMIN_SERVER = os.environ.get('DB_ADMIN_SERVER', 'localhost')
    DB_ADMIN_NAME = os.environ.get('DB_ADMIN_NAME', 'qor_recorder')

    # 服务器监听地址与端口 (可通过环境变量覆盖)
    # HOST: 0.0.0.0=监听所有网卡 (允许远程访问), 127.0.0.1=仅本机
    # PORT: Web 服务端口
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', '5000'))
    DEBUG = os.environ.get('DEBUG', '0') == '1'

    # =========================================================================
    # Session / Cookie 安全配置
    # =========================================================================
    # HttpOnly: 阻止 JS 读取 cookie (防 XSS 窃取 session)
    SESSION_COOKIE_HTTPONLY = True
    # SameSite=Lax: 阻止跨站 POST 自动带 cookie (防 CSRF, 允许顶部导航)
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Secure: 仅 HTTPS 传输 (生产环境必须开启)
    # 默认 False 兼容 HTTP 开发环境; 生产环境设置 SESSION_COOKIE_SECURE=1
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
    # Session 有效期 (默认 12 小时)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get('SESSION_LIFETIME_HOURS', '12')))
    # Remember-Me cookie (若启用 flask-login remember)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
    REMEMBER_COOKIE_SAMESITE = 'Lax'

    # =========================================================================
    # 安全开关 (生产环境必须配置)
    # =========================================================================
    # 是否强制检查 SECRET_KEY (生产环境若仍是默认值则拒绝启动)
    # 设 ENFORCE_SECRET_KEY=0 可关闭 (仅限本地调试)
    ENFORCE_SECRET_KEY = os.environ.get('ENFORCE_SECRET_KEY', '1') == '1'


# =========================================================================
# 延迟注入 SQLALCHEMY_DATABASE_URI (避免 DB_TYPE=sql 缺 DATABASE_URL 时类定义即抛错)
# =========================================================================
def _inject_sqlalchemy_uri():
    """在 Config 类定义后注入 URI, 错误信息更友好"""
    try:
        uri = _build_database_uri() or (
            'sqlite:///' + os.path.join(BASE_DIR, 'qor_recorder.db')
        )
        Config.SQLALCHEMY_DATABASE_URI = uri
    except RuntimeError as e:
        Config.SQLALCHEMY_DATABASE_URI = None
        print('=' * 60, flush=True)
        print(f'[CONFIG] 配置错误: {e}', flush=True)
        print('=' * 60, flush=True)


_inject_sqlalchemy_uri()
