"""SQLAlchemy 多库路由

主库: SQLALCHEMY_DATABASE_URI 绑定的 .db, 存 users/projects/memberships
项目库: 每个 project 一个 .db, 存 modules/records/reviews

模型通过 __bind_key__ 区分:
  bind_key=None         -> 主库 (默认)
  bind_key='project'    -> 项目库 (运行时根据 g.current_project_id 动态选)

使用方式 (路由层两种风格):
  1. 自动路由 (推荐) - 业务代码不变, 通过 before_request 提取 project_id:
       @bp.route('/api/modules/<int:project_id>')
       def list(project_id):
           # g.current_project_id 已被 before_request 设置
           modules = Module.query.all()  # 自动从项目库读
  2. 显式切换 (复杂场景):
       with switch_to_project(pid):
           mods = Module.query.all()
"""
import os
import re
from contextlib import contextmanager

from flask import g, request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session, Session

from core.db import db
from core.project_db import (
    create_project_db, get_project_engine, get_project_session,
    project_db_path,
)


# =========================================================================
# 项目库表标识常量
# =========================================================================
# 这些模型只存在于项目库, 用此常量作为 __bind_key__
PROJECT_BIND = 'project'

# 项目库 session 缓存 {project_id: scoped_session}
_project_sessions = {}


def _build_project_session(project_id):
    """为指定项目创建 scoped session"""
    if project_id in _project_sessions:
        return _project_sessions[project_id]
    engine = get_project_engine(project_id)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)
    sess = scoped_session(factory)
    _project_sessions[project_id] = sess
    return sess


@contextmanager
def switch_to_project(project_id: int):
    """切换当前请求上下文到指定项目 DB

    用法:
        with switch_to_project(pid):
            mods = Module.query.all()  # 从项目库读
    """
    # 确保项目库存在
    if not os.path.exists(project_db_path(project_id)):
        create_project_db(project_id)

    g.current_project_id = project_id
    prev_stack = getattr(g, '_project_stack', [])
    g._project_stack = prev_stack + [project_id]
    try:
        yield
    finally:
        # 恢复
        if len(g._project_stack) > 1:
            g.current_project_id = g._project_stack[-2]
        else:
            g.current_project_id = None
        g._project_stack = prev_stack


def get_active_project_id():
    """从 Flask g 获取当前激活的项目 ID"""
    return getattr(g, 'current_project_id', None)


# =========================================================================
# 自动 session 选择 (供 db.session.get_bind 等高级用法)
# =========================================================================
def _is_project_model(model_class) -> bool:
    """判断模型是否属于项目库"""
    bind_key = getattr(model_class, '__bind_key__', None)
    return bind_key == PROJECT_BIND


def setup_binds(app):
    """配置 SQLAlchemy 多库 binds 路由

    必须在 db.init_app 之后调用.

    工作原理:
      - Monkey-patch flask_sqlalchemy Session.get_bind, 拦截对 __bind_key__='project'
        模型的查询, 动态返回项目库 engine.
      - 同时保留 do_orm_execute 事件作为兜底.
    """
    from flask_sqlalchemy import session as _fs_session

    _original_get_bind = _fs_session.Session.get_bind

    def _patched_get_bind(self, mapper=None, clause=None, bind=None, **kw):
        """替代 Flask-SQLAlchemy 的 get_bind, 支持动态 project bind"""
        if bind is not None:
            return bind

        # 1) 从 mapper 找 bind_key
        bind_key = None
        if mapper is not None:
            try:
                insp = __import__('sqlalchemy').inspect(mapper)
            except Exception:
                insp = None
            if insp is not None:
                bind_key = getattr(insp.class_, '__bind_key__', None)

        # 2) 从 clause (table) 找 bind_key (兼容 Flask-SQLAlchemy 原始方式)
        if bind_key is None and clause is not None:
            table = None
            if isinstance(clause, __import__('sqlalchemy').Table):
                table = clause
            elif hasattr(clause, 'table') and isinstance(clause.table, __import__('sqlalchemy').Table):
                table = clause.table
            if table is not None:
                bind_key = table.metadata.info.get('bind_key')

        # 3) 非 project bind -> 走 Flask-SQLAlchemy 原始逻辑
        if bind_key != PROJECT_BIND:
            return _original_get_bind(self, mapper=mapper, clause=clause, bind=bind, **kw)

        # 4) 已是项目库 session -> 直接返回
        if self.bind is not None:
            bind_str = str(getattr(self.bind, 'url', ''))
            if 'qor_p_' in bind_str:
                return self.bind

        # 5) 从 Flask g 取 active project_id
        try:
            pid = get_active_project_id()
        except RuntimeError:
            pid = None
        if pid is None:
            # 兜底 1: 从 mapper 的 instance dict 拿 project_id (e.g. Module(project_id=X))
            try:
                from sqlalchemy import inspect as _sa_inspect
                if mapper is not None:
                    for obj in self.new:
                        if isinstance(obj, mapper.class_):
                            pid = getattr(obj, 'project_id', None)
                            if pid:
                                break
            except Exception:
                pass
        if pid is None:
            # 兜底 2: 第 1 个项目库
            from core.project_db import list_all_project_dbs
            dbs = list_all_project_dbs()
            if dbs:
                pid = dbs[0]['project_id']
        if pid is None:
            # 兜底 3: 主库 (兼容 seed/test 阶段无项目库)
            return _original_get_bind(self, mapper=mapper, clause=clause, bind=bind, **kw)
        # 确保项目库存在, 否则自动创建
        from core.project_db import project_db_path, create_project_db
        if not os.path.exists(project_db_path(pid)):
            try:
                create_project_db(pid)
            except Exception:
                pass
        return get_project_engine(pid)

    _fs_session.Session.get_bind = _patched_get_bind

    # Monkey-patch db._call_for_binds: 拦截 'project' bind, 遍历所有项目库
    # 避免 Flask-SQLAlchemy 默认逻辑查 SQLALCHEMY_BINDS 找不到 'project' 而报错
    from core.db import db as _db_ext
    from flask_sqlalchemy.extension import SQLAlchemy as _FSA

    # 取原方法副本 (在替换前, 否则会无限递归)
    _orig_call_for_binds = _FSA._call_for_binds

    def _do_for_project_dbs(self, op_name):
        from core.project_db import list_all_project_dbs
        for info in list_all_project_dbs():
            eng = get_project_engine(info['project_id'])
            getattr(self.metadata, op_name)(bind=eng)

    def _patched_call_for_binds(self, bind_key, op_name):
        if bind_key == '__all__':
            _do_for_project_dbs(self, op_name)
            # 主库
            try:
                _orig_call_for_binds(self, None, op_name)
            except Exception:
                pass
            return
        if bind_key == PROJECT_BIND:
            _do_for_project_dbs(self, op_name)
            return
        # 其他 (主库) -> 走原始
        return _orig_call_for_binds(self, bind_key, op_name)

    # 在 class 上替换 (不要在 instance 上, 否则 self 不会自动绑定)
    _FSA._call_for_binds = _patched_call_for_binds

    # 兼容: 监听 do_orm_execute 拦截显式 bind 替换
    @event.listens_for(Session, 'do_orm_execute')
    def _route_query(execute_state):
        if execute_state.is_orm_statement:
            bind_arguments = execute_state.bind_arguments
            if not bind_arguments:
                return
            mapper = bind_arguments.get('mapper')
            if not mapper:
                return
            bind_key = getattr(mapper.class_, '__bind_key__', None)
            if bind_key != PROJECT_BIND:
                return
            session = execute_state.session
            if session is not None and session.bind is not None:
                bind_str = str(getattr(session.bind, 'url', ''))
                if 'qor_p_' in bind_str:
                    return
            try:
                pid = get_active_project_id()
            except RuntimeError:
                pid = None
            if pid is None:
                from core.project_db import list_all_project_dbs
                dbs = list_all_project_dbs()
                if not dbs:
                    raise RuntimeError(
                        '项目库模型查询但无活跃项目上下文 '
                        '(current_project_id=None) 且无任何项目库'
                    )
                pid = dbs[0]['project_id']
            bind_arguments['bind'] = get_project_engine(pid)


# =========================================================================
# before_request: 自动从 URL/参数提取 project_id
# =========================================================================
def _extract_project_id_from_request():
    """从请求 URL 路径 / query / body 提取 project_id

    支持的模式:
      - /api/.../<int:project_id>  (URL path)
      - ?project_id=xx  (query)
      - {"project_id": xx}  (JSON body, 仅 POST/PUT/PATCH)
    """
    # 1. URL 路径: 匹配 /.../(\d+)/...  模式
    path = request.path or ''
    # 优先匹配 /modules/<id> /projects/<id> /tile_reviews/<id> 等
    m = re.search(r'/(?:modules|projects|tile_reviews|group_reviews|subsystem_reviews|review_snapshots|review_files|alerts|data_snapshots|records|notes|violations|runs)/(\d+)', path)
    if m:
        return int(m.group(1))
    # 兜底: 任意 /<id> 形式 (排除明显非ID的, 如 /api, /static, /login)
    parts = [p for p in path.split('/') if p]
    for p in reversed(parts):
        if p.isdigit() and len(p) <= 6:  # 限长防误判
            return int(p)

    # 2. query 参数
    pid = request.args.get('project_id', type=int)
    if pid:
        return pid

    # 3. JSON body
    if request.method in ('POST', 'PUT', 'PATCH') and request.is_json:
        try:
            data = request.get_json(silent=True) or {}
            pid = data.get('project_id')
            if pid:
                return int(pid)
        except Exception:
            pass
    return None


def register_project_context(app):
    """注册 before_request 钩子, 自动从请求提取 project_id

    必须在 setup_binds 之后调用.
    """
    @app.before_request
    def _set_project_context():
        g.current_project_id = None
        g._project_stack = []
        pid = _extract_project_id_from_request()
        if pid:
            # 验证项目存在
            from models import Project
            p = Project.query.get(pid)
            if p is not None:
                g.current_project_id = pid
                g._project_stack = [pid]


# =========================================================================
# 手动查询 (更可靠, 不依赖 ORM event)
# =========================================================================
def project_query(model_class):
    """获取项目库模型的 Query 对象

    用法:
        from models import Module
        q = project_query(Module)
        q.filter(...).all()
    """
    pid = get_active_project_id()
    if pid is None:
        raise RuntimeError(
            'project_query() 需要先调用 switch_to_project(pid) '
            '或在请求中提供 project_id (URL / query / body)'
        )
    sess = _build_project_session(pid)
    return sess.query(model_class)


def project_add(model_instance):
    """添加对象到项目库 session"""
    pid = get_active_project_id()
    if pid is None:
        raise RuntimeError('project_add() 需要活跃项目上下文')
    sess = _build_project_session(pid)
    sess.add(model_instance)
    return sess


def project_commit():
    """提交当前项目库事务"""
    pid = get_active_project_id()
    if pid is None:
        raise RuntimeError('project_commit() 需要活跃项目上下文')
    sess = _build_project_session(pid)
    sess.commit()


def project_rollback():
    """回滚当前项目库事务"""
    pid = get_active_project_id()
    if pid is None:
        return
    sess = _build_project_session(pid)
    sess.rollback()


# =========================================================================
# 跨库查询辅助 (常用查询模式封装)
# =========================================================================
def _resolve_project_ids(project_ids_str='', module_ids_str=''):
    """解析查询参数中的 project_ids (跨库时按 project 迭代需要)

    Returns: list[int] - 项目 ID 列表
    """
    from models import Project
    proj_id_list = []
    if project_ids_str:
        proj_id_list = [int(x) for x in project_ids_str.split(',') if x.strip().isdigit()]
    if not proj_id_list:
        # 兜底: 所有 active 项目
        proj_id_list = [p.id for p in Project.query.filter(Project.status != 'hidden').all()]
    return proj_id_list


def query_records_by_projects(
    proj_id_list=None,
    module_ids_str='',
    versions_str='',
    owner_id=None,
    release_only=False,
    order_desc=True,
    limit=5000,
):
    """按项目迭代查询 QorRecord, 跨库安全的查询模式

    取代原 "QorRecord.query.join(Module).join(Project)" 模式, 避免跨库 JOIN 失败.

    参数:
      proj_id_list:  list[int], 限定项目; None = 全部 active
      module_ids_str: 逗号分隔字符串
      versions_str:   逗号分隔字符串
      owner_id:       int
      release_only:   True = 仅 is_released
      order_desc:     True = recorded_at 倒序
      limit:          每项目上限
    """
    if proj_id_list is None:
        proj_id_list = _resolve_project_ids()

    mod_id_filter = None
    if module_ids_str:
        mod_id_filter = set(int(x) for x in module_ids_str.split(',') if x.strip().isdigit())
    ver_filter = None
    if versions_str:
        ver_filter = set(v.strip() for v in versions_str.split(',') if v.strip())

    from models import QorRecord
    all_records = []
    for pid in proj_id_list:
        with switch_to_project(pid):
            q = QorRecord.query
            if release_only:
                q = q.filter(QorRecord.is_released.is_(True))
            if mod_id_filter:
                q = q.filter(QorRecord.module_id.in_(mod_id_filter))
            if ver_filter:
                q = q.filter(QorRecord.version.in_(ver_filter))
            if owner_id is not None:
                q = q.filter(QorRecord.owner_id == owner_id)
            order = QorRecord.recorded_at.desc() if order_desc else QorRecord.recorded_at.asc()
            all_records.extend(q.order_by(order).limit(limit).all())

    # 跨项目排序
    all_records.sort(
        key=lambda r: r.recorded_at or 0,
        reverse=order_desc,
    )
    return all_records[:limit]


# =========================================================================
# ORM create_all 兜底 (无 alembic 时的备用)
# =========================================================================
def _create_project_tables_via_orm(db_path: str):
    """在指定项目 DB 上 create_all 所有带 __bind_key__='project' 的模型表

    注意: 需要在所有项目库模型 import 之后调用
    """
    engine = create_engine(f'sqlite:///{db_path}')
    from models import _collect_project_models
    tables = [m.__table__ for m in _collect_project_models()]
    db.metadata.create_all(engine, tables=tables)
    engine.dispose()
