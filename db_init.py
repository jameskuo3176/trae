"""数据库初始化与迁移脚本

根据 DB_TYPE 自动选择后端:
  - sqlite   : 创建 .db 文件 + 运行 flask db upgrade
  - sql      : 连接 DB 并 CREATE DATABASE (如不存在) + flask db upgrade
  - mongodb  : 连接 Mongo 并创建必要索引 + flask db upgrade (SQLite 只读回退)

用法:
  python db_init.py                 # 根据 .env 初始化并迁移
  python db_init.py --db-type sql   # 临时切换到 sql 分支
  python db_init.py --check         # 仅检查当前 DB_TYPE 是否配置正确
  python db_init.py --migrate-only  # 跳过建库, 只跑迁移
  python db_init.py --seed          # 迁移后跑 seed_demo_data.py
"""
import argparse
import os
import sys
import subprocess

# 让脚本可被任何目录调用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DB_TYPE_SQLITE, DB_TYPE_SQL, DB_TYPE_MONGODB,
    SUPPORTED_DB_TYPES, _detect_db_type, _build_database_uri,
)


def _set_env(args):
    """根据 --db-type 参数临时覆盖 DB_TYPE"""
    if args.db_type:
        if args.db_type not in SUPPORTED_DB_TYPES:
            print(f'[ERR] 未知 DB_TYPE={args.db_type}, 支持: {", ".join(SUPPORTED_DB_TYPES)}')
            sys.exit(1)
        os.environ['DB_TYPE'] = args.db_type
        print(f'[CFG] 临时设置 DB_TYPE={args.db_type}')


def check_config():
    """检查配置: DB_TYPE 与 DATABASE_URL / MONGODB_URI 一致性"""
    db_type = _detect_db_type()
    print(f'[CHK] DB_TYPE = {db_type}')

    if db_type == DB_TYPE_MONGODB:
        print(f'[CHK] MONGODB_URI = {os.environ.get("MONGODB_URI", "mongodb://localhost:27017")}')
        print(f'[CHK] MONGODB_DB  = {os.environ.get("MONGODB_DB", "qor_recorder")}')

    if db_type == DB_TYPE_SQL:
        url = os.environ.get('DATABASE_URL', '').strip()
        if not url:
            print('[ERR] DB_TYPE=sql 但未设置 DATABASE_URL')
            print('     示例: mysql+pymysql://root:password@localhost:3306/qor_recorder?charset=utf8mb4')
            return False
        # 隐藏密码
        safe = url.split('@', 1)[0] + '@***' if '@' in url else url
        print(f'[CHK] DATABASE_URL = {safe}')

    if db_type == DB_TYPE_SQLITE:
        from config import BASE_DIR
        db_path = os.path.join(BASE_DIR, 'qor_recorder.db')
        print(f'[CHK] SQLite 文件 = {db_path}')

    # SQLAlchemy URI
    try:
        uri = _build_database_uri()
        if db_type == DB_TYPE_MONGODB:
            # mongodb 时 SQL 走 SQLite fallback
            from config import SQLALCHEMY_DATABASE_URI
            uri = SQLALCHEMY_DATABASE_URI
        safe = uri.split('@', 1)[0] + '@***' if (uri and '@' in uri) else uri
        print(f'[CHK] SQLAlchemy URI = {safe}')
    except RuntimeError as e:
        print(f'[ERR] {e}')
        return False

    return True


def ensure_sql_database():
    """DB_TYPE=sql 时确保目标数据库存在 (无表结构)"""
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        print('[ERR] DATABASE_URL 未设置')
        sys.exit(1)
    # 解析 driver://user:pass@host:port/dbname?...
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url.replace('mysql+pymysql://', 'mysql://').replace('postgresql+psycopg2://', 'postgresql://'))
        db_name = parsed.path.lstrip('/')
        if not db_name:
            print('[ERR] 无法从 DATABASE_URL 解析出 dbname')
            sys.exit(1)
        user = parsed.username
        password = parsed.password
        host = parsed.hostname or 'localhost'
        port = parsed.port or (3306 if 'mysql' in url else 5432)
    except Exception as e:
        print(f'[ERR] 解析 DATABASE_URL 失败: {e}')
        sys.exit(1)

    print(f'[SQL] 准备创建数据库: {db_name} @ {host}:{port}')

    if 'mysql' in url:
        try:
            import pymysql
        except ImportError:
            print('[ERR] 需要 pymysql: pip install pymysql')
            sys.exit(1)
        try:
            conn = pymysql.connect(host=host, port=port, user=user, password=password, charset='utf8mb4')
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            conn.commit()
            conn.close()
            print(f'[SQL] 数据库 {db_name} 已就绪 (utf8mb4 / utf8mb4_unicode_ci)')
        except Exception as e:
            print(f'[ERR] 连接 MySQL 失败: {e}')
            sys.exit(1)
    elif 'postgres' in url or 'psql' in url:
        try:
            import psycopg2
        except ImportError:
            print('[ERR] 需要 psycopg2: pip install psycopg2-binary')
            sys.exit(1)
        try:
            conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname='postgres')
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'CREATE DATABASE "{db_name}"')
            conn.close()
            print(f'[SQL] 数据库 {db_name} 已就绪')
        except psycopg2.errors.DuplicateDatabase:
            print(f'[SQL] 数据库 {db_name} 已存在, 跳过创建')
        except Exception as e:
            print(f'[ERR] 连接 PostgreSQL 失败: {e}')
            sys.exit(1)
    else:
        print(f'[ERR] 暂不支持的 SQL 后端: {url}')
        sys.exit(1)


def ensure_mongo_database():
    """DB_TYPE=mongodb 时检查 Mongo 连通性 + 创建索引"""
    uri = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017')
    db_name = os.environ.get('MONGODB_DB', 'qor_recorder')
    print(f'[MONGO] 连接: {uri}  db={db_name}')
    try:
        from pymongo import MongoClient
    except ImportError:
        print('[ERR] 需要 pymongo: pip install pymongo')
        sys.exit(1)
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')
        d = client[db_name]
        # 创建常用索引
        d.users.create_index('username', unique=True)
        d.projects.create_index('name')
        d.qorrecords.create_index([('project_id', 1), ('module_id', 1), ('version', 1)])
        d.qorrecords.create_index('full_dir')
        print('[MONGO] 已创建索引 (users.username unique, qorrecords.project_id+module_id+version)')
    except Exception as e:
        print(f'[ERR] MongoDB 连接失败: {e}')
        print('     提示: MongoDB 未启动或网络不通, 请先 mongod --dbpath /data/db')
        sys.exit(1)


def run_migrations():
    """执行 flask db upgrade"""
    print('\n[MIGRATE] 启动 flask db upgrade ...')
    code = subprocess.call([sys.executable, '-m', 'flask', 'db', 'upgrade'])
    if code != 0:
        print(f'[ERR] flask db upgrade 失败 (exit={code})')
        sys.exit(code)
    print('[MIGRATE] 完成')


def run_seed():
    """执行 seed_demo_data.py"""
    print('\n[SEED] 启动 seed_demo_data.py ...')
    code = subprocess.call([sys.executable, 'seed_demo_data.py'])
    if code != 0:
        print(f'[WARN] seed_demo_data 退出码 {code} (非致命)')


def main():
    parser = argparse.ArgumentParser(description='QoR Recorder 数据库初始化')
    parser.add_argument('--db-type', choices=SUPPORTED_DB_TYPES, help='临时覆盖 DB_TYPE')
    parser.add_argument('--check', action='store_true', help='仅检查配置, 不建库')
    parser.add_argument('--migrate-only', action='store_true', help='跳过建库, 只跑迁移')
    parser.add_argument('--seed', action='store_true', help='迁移后跑 demo 数据')
    args = parser.parse_args()

    _set_env(args)

    print('=' * 60)
    print('QoR Recorder 数据库初始化工具')
    print('=' * 60)

    if not check_config():
        sys.exit(1)
    if args.check:
        print('\n[OK] 配置检查通过')
        return

    db_type = _detect_db_type()

    if not args.migrate_only:
        if db_type == DB_TYPE_SQL:
            ensure_sql_database()
        elif db_type == DB_TYPE_MONGODB:
            ensure_mongo_database()
        elif db_type == DB_TYPE_SQLITE:
            # SQLite 自动创建文件, 不需要预创建
            print('[SQLITE] 文件不存在将在首次迁移时自动创建')

    run_migrations()

    if args.seed:
        run_seed()

    print('\n' + '=' * 60)
    print('[DONE] 数据库就绪')
    print('=' * 60)


if __name__ == '__main__':
    main()
