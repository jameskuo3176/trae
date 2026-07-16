"""应用配置

数据库后端支持:
  - 默认: SQLite (WAL 模式, 零运维, 适合小型团队)
  - 可选: MySQL/MariaDB (支持完整 MVCC 并发, 适合多项目大规模团队)

切换方式:
  设置环境变量 DATABASE_URL, 例如:
    # MySQL
    set DATABASE_URL=mysql+pymysql://user:password@localhost:3306/qor_recorder?charset=utf8mb4
    # SQLite (默认)
    set DATABASE_URL=sqlite:///qor_recorder.db

可视化:
  设置环境变量 ENABLE_DB_ADMIN=1 启用内置 Adminer (数据库 Web 可视化)

配置加载顺序 (优先级从高到低):
  1. 系统环境变量
  2. .env 文件 (若存在, 自动加载, 无需第三方依赖)
  3. 内置默认值
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


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


def _build_database_uri():
    """构建数据库 URI

    优先级:
      1. 环境变量 DATABASE_URL (支持 mysql://, mysql+pymysql://, sqlite://)
      2. 默认 SQLite (WAL 模式)
    """
    uri = os.environ.get('DATABASE_URL')
    if uri:
        # 兼容 mysql:// 开头 (SQLAlchemy 需要 mysql+pymysql://)
        if uri.startswith('mysql://'):
            uri = uri.replace('mysql://', 'mysql+pymysql://', 1)
        return uri
    # 默认 SQLite
    return 'sqlite:///' + os.path.join(BASE_DIR, 'qor_recorder.db')


def _is_sqlite():
    return _build_database_uri().startswith('sqlite')


class Config:
    # 数据库
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

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
