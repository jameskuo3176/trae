"""Repository 抽象层

为上层 (app.py / views) 提供与 SQLAlchemy 同形的数据访问 API,
内部根据配置路由到 SQLite (默认) 或 MongoDB 后端。

设计目标:
  1. **零侵入迁移**: 业务代码只需 `from repo import r; r.qor_records(...)`,
     不感知后端差异
  2. **可灰度**: 同一请求可同时写双后端 (DATABASE_BACKEND=dual)
  3. **可回滚**: 关闭 MongoDB 写入即可退回到纯 SQLite 模式
  4. **可选依赖**: pymongo 不在 requirements 中, 未装时自动跳过 MongoDB

切换方式 (.env):
    DATABASE_BACKEND=sqlite   # 纯 SQLite (默认, 向后兼容)
    DATABASE_BACKEND=mongo    # 纯 MongoDB (迁移完成后)
    DATABASE_BACKEND=dual     # 双写 (迁移过渡期)
    MONGO_URI=mongodb://localhost:27017
    MONGO_DB=qor_recorder
"""
import json
import os
import logging
from typing import List, Dict, Optional, Any, Iterable

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# 配置读取
# -------------------------------------------------------------------------
BACKEND = os.environ.get('DATABASE_BACKEND', 'sqlite').lower()
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')
MONGO_DB = os.environ.get('MONGO_DB', 'qor_recorder')

_mongo_client = None
_mongo_db = None
_mongo_enabled = False


def _try_init_mongo():
    """尝试初始化 MongoDB 客户端; 若 pymongo 未装或连接失败则降级"""
    global _mongo_client, _mongo_db, _mongo_enabled
    if BACKEND == 'sqlite':
        return
    try:
        import pymongo
        from pymongo import MongoClient
    except ImportError:
        logger.warning('[repo] pymongo not installed, MongoDB disabled. '
                       'Run: pip install pymongo')
        return
    try:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        # 强制连接测试, 失败不抛 (后续写操作时再感知)
        _mongo_client.admin.command('ping')
        _mongo_db = _mongo_client[MONGO_DB]
        _mongo_enabled = True
        logger.info(f'[repo] MongoDB connected: {MONGO_URI}/{MONGO_DB}')
    except Exception as e:
        logger.warning(f'[repo] MongoDB connect failed: {e}; fallback to SQLite only')
        _mongo_enabled = False


def is_mongo_enabled():
    return _mongo_enabled


# -------------------------------------------------------------------------
# 文档序列化
# -------------------------------------------------------------------------
def _to_json_safe(obj):
    """把 SQLAlchemy 对象转 dict; 含 datetime / None 安全处理"""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if hasattr(obj, 'to_dict'):
        d = obj.to_dict()
        return _to_json_safe(d)
    return obj


def _serialize_for_mongo(d: Dict[str, Any]) -> Dict[str, Any]:
    """dict → BSON-safe (处理 datetime)"""
    from datetime import datetime, date
    if d is None:
        return None
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if isinstance(v, datetime):
                out[k] = v
            elif isinstance(v, date):
                out[k] = datetime(v.year, v.month, v.day)
            elif isinstance(v, dict):
                out[k] = _serialize_for_mongo(v)
            elif isinstance(v, list):
                out[k] = [_serialize_for_mongo(x) if isinstance(x, (dict, list)) else x for x in v]
            else:
                out[k] = v
        return out
    return d


# -------------------------------------------------------------------------
# 通用集合操作
# -------------------------------------------------------------------------
def mongo_upsert(collection: str, doc: Dict[str, Any], key_field: str = 'id'):
    """upsert 一条文档到 MongoDB"""
    if not _mongo_enabled:
        return False
    try:
        d = _serialize_for_mongo(_to_json_safe(doc))
        _mongo_db[collection].update_one(
            {key_field: d[key_field]},
            {'$set': d},
            upsert=True
        )
        return True
    except Exception as e:
        logger.warning(f'[repo] mongo_upsert({collection}) failed: {e}')
        return False


def mongo_delete(collection: str, key_value: Any, key_field: str = 'id'):
    if not _mongo_enabled:
        return False
    try:
        _mongo_db[collection].delete_one({key_field: key_value})
        return True
    except Exception as e:
        logger.warning(f'[repo] mongo_delete({collection}) failed: {e}')
        return False


def mongo_find(collection: str, query: Dict[str, Any] = None,
               projection: Dict[str, int] = None, limit: int = 0) -> List[Dict[str, Any]]:
    if not _mongo_enabled:
        return []
    try:
        cur = _mongo_db[collection].find(query or {}, projection)
        if limit:
            cur = cur.limit(limit)
        out = []
        for d in cur:
            d.pop('_id', None)
            out.append(d)
        return out
    except Exception as e:
        logger.warning(f'[repo] mongo_find({collection}) failed: {e}')
        return []


def mongo_count(collection: str, query: Dict[str, Any] = None) -> int:
    if not _mongo_enabled:
        return 0
    try:
        return _mongo_db[collection].count_documents(query or {})
    except Exception:
        return 0


# -------------------------------------------------------------------------
# 业务级同步接口 (供 views 调用)
# -------------------------------------------------------------------------
def sync_qor_record(sql_record, op: str = 'upsert'):
    """同步单条 QoR record 到 MongoDB"""
    if not _mongo_enabled:
        return
    if op == 'upsert':
        mongo_upsert('qor_records', sql_record, 'id')
    elif op == 'delete':
        mongo_delete('qor_records', sql_record.id, 'id')


def sync_project(sql_project, op: str = 'upsert'):
    if not _mongo_enabled:
        return
    if op == 'upsert':
        mongo_upsert('projects', sql_project, 'id')
    elif op == 'delete':
        mongo_delete('projects', sql_project.id, 'id')


def sync_module(sql_module, op: str = 'upsert'):
    if not _mongo_enabled:
        return
    if op == 'upsert':
        mongo_upsert('modules', sql_module, 'id')
    elif op == 'delete':
        mongo_delete('modules', sql_module.id, 'id')


def sync_user(sql_user, op: str = 'upsert'):
    if not _mongo_enabled:
        return
    # 不写密码 hash 到 MongoDB (安全)
    if op == 'upsert':
        d = sql_user.to_dict() if hasattr(sql_user, 'to_dict') else {'id': sql_user.id}
        d.pop('password_hash', None)
        mongo_upsert('users', d, 'id')
    elif op == 'delete':
        mongo_delete('users', sql_user.id, 'id')


def sync_dashboard_group(sql_group, op: str = 'upsert'):
    if not _mongo_enabled:
        return
    if op == 'upsert':
        mongo_upsert('dashboard_groups', sql_group, 'id')
    elif op == 'delete':
        mongo_delete('dashboard_groups', sql_group.id, 'id')


def bulk_sync(table: str, sql_records: Iterable, key_field: str = 'id'):
    """批量同步一组 SQLAlchemy 对象到 MongoDB"""
    if not _mongo_enabled:
        return 0
    n = 0
    for r in sql_records:
        d = _to_json_safe(r)
        if d and mongo_upsert(table, d, key_field):
            n += 1
    return n


# -------------------------------------------------------------------------
# 一次性迁移工具
# -------------------------------------------------------------------------
def export_sqlite_to_mongo(sqlalchemy_query_fn, collection: str,
                           key_field: str = 'id', batch_size: int = 200) -> int:
    """把 SQLAlchemy 查询结果全量同步到 MongoDB

    用法:
        from repo import export_sqlite_to_mongo
        from models import Project
        export_sqlite_to_mongo(lambda: Project.query.all(), 'projects')
    """
    if not _mongo_enabled:
        logger.error('[repo] MongoDB not enabled, cannot export')
        return 0
    rows = sqlalchemy_query_fn()
    n = 0
    batch = []
    for r in rows:
        d = _to_json_safe(r)
        if d is None:
            continue
        # users 表: 不带密码 hash
        if collection == 'users':
            d.pop('password_hash', None)
        batch.append(d)
        if len(batch) >= batch_size:
            _mongo_db[collection].bulk_write([
                __import__('pymongo').UpdateOne(
                    {key_field: doc[key_field]},
                    {'$set': doc},
                    upsert=True
                ) for doc in batch
            ], ordered=False)
            n += len(batch)
            batch = []
    if batch:
        _mongo_db[collection].bulk_write([
            __import__('pymongo').UpdateOne(
                {key_field: doc[key_field]},
                {'$set': doc},
                upsert=True
            ) for doc in batch
        ], ordered=False)
        n += len(batch)
    logger.info(f'[repo] exported {n} rows to mongo.{collection}')
    return n


# -------------------------------------------------------------------------
# 启动初始化
# -------------------------------------------------------------------------
_try_init_mongo()
