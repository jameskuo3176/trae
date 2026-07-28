"""按项目分库管理器

设计:
  - 主库 qor_recorder.db 存: users, projects, project_memberships, api_keys
  - 每个项目独立 .db 文件: qor_p_<id>.db
    存: modules, qor_records, tile_reviews, group_reviews, subsystem_reviews,
        review_files, review_snapshots, run_notes
  - 通过 SQLAlchemy binds + 动态绑定实现路由
  - 锁定: status=locked 时, 文件设为只读 (0444)
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, scoped_session

from config import BASE_DIR

# 项目 DB 锁 (防止并发创建/迁移)
_lock = threading.Lock()

# 已创建的 engine 缓存 {project_id: Engine}
_engines: dict = {}
_sessions: dict = {}


def project_db_path(project_id: int) -> str:
    """获取项目 DB 文件路径"""
    return os.path.join(BASE_DIR, f'qor_p_{project_id}.db')


def project_db_exists(project_id: int) -> bool:
    return os.path.exists(project_db_path(project_id))


def create_project_db(project_id: int) -> str:
    """为新项目创建独立的 .db 文件, 跑迁移, 启用 WAL.

    返回 DB 文件路径.
    """
    path = project_db_path(project_id)
    with _lock:
        if os.path.exists(path):
            return path  # 已存在, 跳过

        # 1. 创建空文件 + 启用 WAL
        engine = create_engine(f'sqlite:///{path}', echo=False)
        with engine.connect() as conn:
            conn.exec_driver_sql('PRAGMA journal_mode=WAL')
            conn.exec_driver_sql('PRAGMA synchronous=NORMAL')
            conn.exec_driver_sql('PRAGMA busy_timeout=30000')
            conn.exec_driver_sql('PRAGMA foreign_keys=ON')
        engine.dispose()

        # 2. 跑迁移 (在项目 DB 上创建表)
        _run_migrations_on_project_db(project_id, path)

        return path


def _run_migrations_on_project_db(project_id: int, db_path: str):
    """在指定项目 DB 上创建表结构

    策略: 主库用 alembic 管理 schema, 项目库用 ORM create_all 创建.
    项目库结构与主库保持一致 (因为主表定义相同), 无 alembic 升级路径.
    新增项目库表时, 修改 models.py 即可 (下次 create_project_db 会自动应用).
    """
    from core.db_routing import _create_project_tables_via_orm
    _create_project_tables_via_orm(db_path)


def get_project_engine(project_id: int) -> Engine:
    """获取/创建项目 DB engine (带缓存)"""
    if project_id in _engines:
        return _engines[project_id]
    path = project_db_path(project_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f'项目 DB 不存在: {path} (id={project_id})')

    with _lock:
        if project_id in _engines:
            return _engines[project_id]
        engine = create_engine(f'sqlite:///{path}', echo=False)

        @event.listens_for(engine, 'connect')
        def _set_pragma(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA busy_timeout=30000')
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        _engines[project_id] = engine
        return engine


def get_project_session(project_id: int):
    """获取项目 DB 的 scoped session"""
    if project_id not in _sessions:
        engine = get_project_engine(project_id)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        _sessions[project_id] = scoped_session(session_factory)
    return _sessions[project_id]


@contextmanager
def project_session_scope(project_id: int):
    """事务作用域: 进入自动 commit, 异常自动 rollback"""
    if not project_db_exists(project_id):
        create_project_db(project_id)
    session = get_project_session(project_id)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def lock_project_db(project_id: int) -> bool:
    """锁定项目 DB: status=locked 时调用, 文件设为只读"""
    path = project_db_path(project_id)
    if not os.path.exists(path):
        return False

    # 1. 关闭缓存的 engine, 释放文件锁
    close_project_engine(project_id)

    # 2. WAL checkpoint 后设为只读
    try:
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.close()
    except Exception:
        pass

    try:
        os.chmod(path, 0o444)
        return True
    except Exception as e:
        print(f'[ProjectDB] 锁定失败 id={project_id}: {e}')
        return False


def unlock_project_db(project_id: int) -> bool:
    """解锁项目 DB: status=active 时调用"""
    path = project_db_path(project_id)
    if not os.path.exists(path):
        return False

    try:
        os.chmod(path, 0o644)
        # 清缓存让下次重新打开时启用 WAL
        return True
    except Exception as e:
        print(f'[ProjectDB] 解锁失败 id={project_id}: {e}')
        return False


def close_project_engine(project_id: int):
    """关闭并清空某个项目的 engine 缓存"""
    if project_id in _engines:
        try:
            _engines[project_id].dispose()
        except Exception:
            pass
        del _engines[project_id]
    if project_id in _sessions:
        try:
            _sessions[project_id].remove()
        except Exception:
            pass
        del _sessions[project_id]


def delete_project_db(project_id: int) -> bool:
    """删除项目 DB 文件 (硬删除, 不可逆)

    用于 admin_hard_delete_project 流程.
    """
    path = project_db_path(project_id)
    close_project_engine(project_id)
    if os.path.exists(path):
        try:
            os.chmod(path, 0o644)  # 解除只读
            os.remove(path)
            # 顺带删 WAL/SHM 文件
            for ext in ('-wal', '-shm', '-journal'):
                p = path + ext
                if os.path.exists(p):
                    try: os.remove(p)
                    except: pass
            return True
        except Exception as e:
            print(f'[ProjectDB] 删除失败 id={project_id}: {e}')
            return False
    return True


def list_all_project_dbs() -> list:
    """列出所有项目 DB 文件 (供管理/备份)"""
    files = []
    for name in os.listdir(BASE_DIR):
        if name.startswith('qor_p_') and name.endswith('.db'):
            try:
                pid = int(name[len('qor_p_'):-len('.db')])
                full = os.path.join(BASE_DIR, name)
                size = os.path.getsize(full)
                files.append({'project_id': pid, 'path': full, 'size_kb': size // 1024})
            except ValueError:
                continue
    return sorted(files, key=lambda x: x['project_id'])
