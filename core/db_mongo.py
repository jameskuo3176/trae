"""MongoDB 适配层 (DB_TYPE=mongodb)

设计原则:
  - 仍然保留 SQLAlchemy 模型作为 "主 ORM", 用于跨后端的统一模型定义
  - DB_TYPE=mongodb 时启用 dual-write 模式:
      * 写:  同时写入 SQLAlchemy (SQLite fallback) + Mongo
      * 读:  优先 Mongo, 失败回退到 SQL
  - 若 pymongo 未安装, 全部走 SQL, Mongo 调用静默 no-op
  - 集合 (collection) 名采用复数化的 model 名 (lowercase)
"""
from typing import Optional, Tuple

_client = None           # pymongo.MongoClient 单例
_db = None               # pymongo.Database 单例
_enabled = False         # MongoDB 分支是否启用 (连接成功)


def init_mongo_client(app) -> Tuple[Optional[object], Optional[object]]:
    """初始化 Mongo 客户端 (单例)

    返回 (client, db) 或 (None, None) (不可用时)
    """
    global _client, _db, _enabled
    if _client is not None:
        return _client, _db

    try:
        from pymongo import MongoClient
    except ImportError:
        # pymongo 未安装, 静默返回 None
        return None, None

    uri = app.config.get('MONGODB_URI', 'mongodb://localhost:27017')
    db_name = app.config.get('MONGODB_DB', 'qor_recorder')

    try:
        # serverSelectionTimeoutMS=2s 避免启动时挂死
        client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        # 立即 ping 一次, 验证连接
        client.admin.command('ping')
        _client = client
        _db = client[db_name]
        _enabled = True
        return _client, _db
    except Exception:
        # 连接失败 (mongo 未启动/网络不通), 静默降级
        _client = None
        _db = None
        _enabled = False
        return None, None


def is_mongo_enabled() -> bool:
    """MongoDB 分支是否可用 (连接成功且启用)"""
    return _enabled


def get_db():
    """获取当前 Mongo db 句柄 (未启用时返回 None)"""
    return _db if _enabled else None


def collection_for(model_name: str):
    """根据模型名获取对应集合 (如 'User' -> 'users')

    未启用时返回 None, 调用方应跳过 Mongo 写。
    """
    if not _enabled or _db is None:
        return None
    # 简单的复数化: 大写变小写 + 's'
    return _db[model_name.lower() + 's']


def sync_to_mongo(model_name: str, record_dict: dict, key: str = 'id'):
    """同步一条记录到 Mongo (无副作用, 失败仅记录日志)

    model_name: 'User' / 'Project' / 'QorRecord' 等
    record_dict: 序列化后的 dict
    key: 主键字段名
    """
    if not _enabled:
        return False
    try:
        coll = collection_for(model_name)
        if coll is None:
            return False
        # _id 改为 str 防止 pymongo 抛 InvalidDocument
        d = dict(record_dict)
        if '_id' in d and not isinstance(d['_id'], str):
            d['_id'] = str(d['_id'])
        # 主键字段也存一份, 方便按 id 查询
        if key in d and key != '_id':
            d[key] = d[key]
        coll.replace_one({key: d.get(key)}, d, upsert=True)
        return True
    except Exception as e:
        # 静默失败, 不阻塞主流程
        import logging
        logging.getLogger(__name__).warning(f'[Mongo] sync {model_name} 失败: {e}')
        return False


def delete_from_mongo(model_name: str, key: str, value):
    """从 Mongo 删除一条记录"""
    if not _enabled:
        return False
    try:
        coll = collection_for(model_name)
        if coll is None:
            return False
        coll.delete_one({key: value})
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'[Mongo] delete {model_name} 失败: {e}')
        return False
