"""数据库并发优化与重试机制

负责:
  - SQLite WAL 模式配置 / MySQL 连接事件
  - 数据库写入重试装饰器
  - 轻量级列迁移 (无 alembic 升级)
"""
import os
import time
from datetime import datetime
from functools import wraps

from flask import current_app
from sqlalchemy import event, text

from models import db


def _ensure_columns_in_app(app):
    """检查并补充新增列 (用于已存在数据库的平滑升级)

    仅支持新增列 (ADD COLUMN), 不支持改类型/删列。
    新增列必须有默认值或可空, 以兼容旧行。
    """
    new_columns = [
        # QorRecord: release 标记
        ('qor_records', 'is_released', "BOOLEAN DEFAULT 0"),
        ('qor_records', 'released_at', "DATETIME"),
        ('qor_records', 'released_by', "INTEGER"),
        # RunNote: full_dir 字段
        ('run_notes', 'full_dir', "VARCHAR(1000)"),
    ]
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    is_sqlite = uri.startswith('sqlite')
    try:
        for table, col, ddl in new_columns:
            if is_sqlite:
                rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
                existing = {r[1] for r in rows}
            else:
                rows = db.session.execute(text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
                ), {'t': table}).fetchall()
                existing = {r[0] for r in rows}
            if col in existing:
                continue
            try:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                db.session.commit()
                print(f"[DB] 已新增列: {table}.{col}")
            except Exception as e:
                db.session.rollback()
                print(f"[DB] 新增列失败 {table}.{col}: {e}")
    except Exception as e:
        print(f"[DB] _ensure_columns 异常: {e}")

    # 创建新表 (主库部分, run_notes 已在项目库)
    try:
        from models import _collect_master_models
        master_tables = [m.__table__ for m in _collect_master_models()]
        if master_tables:
            db.metadata.create_all(db.engine, tables=master_tables)
    except Exception as e:
        print(f"[DB] create_all 异常: {e}")


def init_db_concurrency(app):
    """根据数据库类型初始化并发优化配置

    SQLite: 启用 WAL 模式, 允许并发读不阻塞写
    MySQL:   设置 utf8mb4 字符集与 READ COMMITTED 隔离级别
    MongoDB: 初始化 pymongo 客户端 (通过 db_mongo 统一管理)
    """
    db_type = app.config.get('DB_TYPE', 'sqlite')

    if db_type == 'sqlite':
        @event.listens_for(db.engine, 'connect')
        def _set_sqlite_pragma(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA busy_timeout=30000')
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()
        app.logger.info('[DB] SQLite WAL 模式已启用 (并发读不阻塞写)')
    elif db_type == 'sql':
        @event.listens_for(db.engine, 'connect')
        def _set_sql_charset(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("SET NAMES utf8mb4")
                cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            finally:
                cursor.close()
        app.logger.info(f'[DB] SQL 后端 ({app.config["SQLALCHEMY_DATABASE_URI"].split("://")[0]}) 已配置连接池')
    elif db_type == 'mongodb':
        # 初始化 Mongo 客户端 (失败也不阻塞启动, 由后续调用决定是否报错)
        try:
            from core.db_mongo import init_mongo_client
            client, dbh = init_mongo_client(app)
            if client is not None:
                app.logger.info(f'[DB] MongoDB 已连接: {app.config["MONGODB_URI"]}  db={app.config["MONGODB_DB"]}')
            else:
                app.logger.warning('[DB] pymongo 未安装或连接失败, MongoDB 分支不可用')
        except Exception as e:
            app.logger.warning(f'[DB] MongoDB 初始化失败: {e}')


def with_db_retry(max_retries=3, base_delay=0.1):
    """数据库写入重试装饰器

    应对 SQLite "database is locked" 和 MySQL "Deadlock found" 等并发冲突。
    指数退避: base_delay * 2^attempt
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    err_str = str(e).lower()
                    is_retryable = (
                        'database is locked' in err_str or
                        'deadlock found' in err_str or
                        'lock timeout' in err_str or
                        'could not serialize' in err_str
                    )
                    if not is_retryable or attempt == max_retries - 1:
                        raise
                    last_err = e
                    delay = base_delay * (2 ** attempt)
                    current_app.logger.warning(
                        '[DB] 写入冲突, 第 %d 次重试 (%.2fs): %s',
                        attempt + 1, delay, err_str,
                    )
                    time.sleep(delay)
                    db.session.rollback()
            raise last_err
        return wrapper
    return decorator


def ensure_columns(app):
    """补充新增列, 用于已存在数据库的平滑升级"""
    with app.app_context():
        _ensure_columns_in_app(app)
