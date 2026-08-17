"""Django 多库路由

主库: settings.DATABASES['default'] 绑定的 .db, 存 users/projects/memberships
项目库: 每个 project 一个 .db, 存 modules/records/reviews

通过 Django Database Router 实现动态路由:
  - 从请求中提取 project_id (URL / query / body)
  - 根据模型名判断是否属于项目库
  - 动态注册/获取项目库 DB 连接

ProjectContextMiddleware 负责从请求中提取 project_id 并存入 request 对象。
"""
import json
import os
import re
import threading
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError
from django.utils import timezone

# =========================================================================
# 常量
# =========================================================================
PROJECT_DB_PREFIX = 'qor_p_'

# 项目库模型名集合 (与 Flask 版本 __bind_key__='project' 的模型一致)
PROJECT_MODEL_NAMES = {
    'Module', 'QorRecord', 'ViolationPath', 'RunNote',
    'RecordAnnotation', 'RecordAnnotationImage',
    'DashboardGroup', 'AlertRule', 'AlertEvent', 'DataSnapshot',
    'TileReview', 'GroupReview', 'SubsystemReview',
    'ReviewSnapshot', 'ReviewFile',
}

# 项目 DB 锁 (防止并发创建/迁移)
_lock = threading.Lock()

# engine 缓存 {project_id: sqlite3 engine}
_project_engines = {}

# 线程局部存储: 当前请求的 project_id
_thread_local = threading.local()


# =========================================================================
# 路径工具
# =========================================================================
def project_db_path(project_id):
    """Return the preferred project database path with legacy fallback."""
    data_dir = str(settings.DATA_DIR) if hasattr(settings, 'DATA_DIR') else str(settings.BASE_DIR.parent / 'data')
    legacy_path = os.path.join(data_dir, f'{PROJECT_DB_PREFIX}{project_id}.db')
    try:
        from django.apps import apps
        Project = apps.get_model('core', 'Project')
        project = Project.objects.using('default').only('name', 'db_path').get(pk=project_id)
        safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', project.name).strip('._-')
        if not safe_name:
            safe_name = f'project_{project_id}'
        preferred = os.path.join(data_dir, f'{safe_name}_syn_qor.db')
        configured = os.path.abspath(project.db_path) if project.db_path else ''
        if configured and configured.endswith('_syn_qor.db') and os.path.exists(configured):
            return configured
        if os.path.exists(preferred) or not os.path.exists(legacy_path):
            return preferred
    except Exception:
        pass
    return legacy_path


def _get_project_db_alias(project_id):
    """返回项目 DB 的 Django 连接别名"""
    return f'project_{project_id}'


# =========================================================================
# Engine 管理
# =========================================================================
def get_project_engine(project_id):
    """获取或创建项目 DB 的 SQLite engine

    返回 Django 连接别名对应的 engine。
    """
    alias = _get_project_db_alias(project_id)

    # 检查是否已在 Django connections 中注册
    if alias in connections.databases:
        return connections[alias]

    path = project_db_path(project_id)
    if not os.path.exists(path):
        # 自动创建项目 DB
        create_project_db(project_id)

    # 动态注册到 Django connections
    with _lock:
        if alias in connections.databases:
            return connections[alias]

        connections.databases[alias] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': path,
            'OPTIONS': {
                'timeout': 30,
            },
            'ATOMIC_REQUESTS': False,
            'AUTOCOMMIT': True,
            'CONN_MAX_AGE': 0,
            'CONN_HEALTH_CHECKS': False,
            'TIME_ZONE': settings.TIME_ZONE,
            'TEST': {
                'CHARSET': None, 'COLLATION': None, 'MIGRATE': True,
                'MIRROR': None, 'NAME': None,
            },
        }
        # 确保连接可用
        conn = connections[alias]
        conn.ensure_connection()

    return connections[alias]


def create_project_db(project_id):
    """创建项目 DB 文件并初始化表结构

    创建 SQLite 文件, 启用 WAL, 然后通过 Django migration 或
    ORM 创建项目模型对应的表。
    """
    path = project_db_path(project_id)
    with _lock:
        if os.path.exists(path):
            return path

        import sqlite3
        # 1. 创建空文件 + 启用 WAL
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.close()

        # 2. 注册到 Django 并创建表
        alias = _get_project_db_alias(project_id)
        connections.databases[alias] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': path,
            'OPTIONS': {
                'timeout': 30,
            },
            'ATOMIC_REQUESTS': False,
            'AUTOCOMMIT': True,
            'CONN_MAX_AGE': 0,
            'CONN_HEALTH_CHECKS': False,
            'TIME_ZONE': settings.TIME_ZONE,
            'TEST': {
                'CHARSET': None, 'COLLATION': None, 'MIGRATE': True,
                'MIRROR': None, 'NAME': None,
            },
        }

        # 3. 通过 Django schema 迁移创建项目模型表
        _create_project_tables(project_id, alias)

        return path


def _create_project_tables(project_id, alias):
    """在项目 DB 上创建项目模型对应的表

    使用 Django schema_editor 在指定连接上创建表。
    """
    from django.apps import apps
    from django.core.management import call_command

    try:
        # 尝试使用 migrate 命令 (需要 migrations 已配置)
        call_command('migrate', '--database', alias, '--run-syncdb', verbosity=0, interactive=False)
    except Exception:
        # 兜底: 使用 schema_editor 直接创建表
        from django.db import connections as dj_connections
        connection = dj_connections[alias]
        connection.ensure_connection()

        # 找出所有项目模型
        project_models = []
        for app_config in apps.get_app_configs():
            for model in app_config.get_models():
                if model.__name__ in PROJECT_MODEL_NAMES:
                    project_models.append(model)

        if project_models:
            from django.db.migrations.executor import MigrationExecutor
            executor = MigrationExecutor(connection)
            # 使用 schema_editor 创建表
            from django.db import models as dj_models
            with connection.schema_editor() as schema_editor:
                for model in project_models:
                    try:
                        schema_editor.create_model(model)
                    except Exception:
                        pass  # 表可能已存在


def list_all_project_dbs():
    """List databases belonging to current Project rows."""
    data_dir = str(settings.DATA_DIR) if hasattr(settings, 'DATA_DIR') else str(settings.BASE_DIR.parent / 'data')
    if not os.path.isdir(data_dir):
        return []

    files = []
    try:
        from django.apps import apps
        Project = apps.get_model('core', 'Project')
        project_ids = Project.objects.using('default').order_by('id').values_list('id', flat=True)
        for pid in project_ids:
            try:
                full = project_db_path(pid)
                if not os.path.exists(full):
                    continue
                size = os.path.getsize(full)
                files.append({
                    'project_id': pid,
                    'path': full,
                    'name': os.path.basename(full),
                    'size_kb': size // 1024,
                })
            except OSError:
                continue
    except Exception:
        # Bootstrap fallback before the main Project table is available.
        prefix = PROJECT_DB_PREFIX
        for name in os.listdir(data_dir):
            if name.startswith(prefix) and name.endswith('.db'):
                try:
                    pid = int(name[len(prefix):-len('.db')])
                    full = os.path.join(data_dir, name)
                    files.append({
                        'project_id': pid,
                        'path': full,
                        'name': name,
                        'size_kb': os.path.getsize(full) // 1024,
                    })
                except (ValueError, OSError):
                    continue
    return sorted(files, key=lambda x: x['project_id'])


# =========================================================================
# 线程局部 project_id 管理
# =========================================================================
def set_current_project_id(project_id):
    """设置当前线程的活跃 project_id"""
    _thread_local.current_project_id = project_id


def get_current_project_id():
    """获取当前线程的活跃 project_id"""
    return getattr(_thread_local, 'current_project_id', None)


# =========================================================================
# Django Database Router
# =========================================================================
class ProjectDBRouter:
    """Django 数据库路由器: 将项目模型路由到对应的项目 DB

    使用方式: 在 settings.DATABASE_ROUTERS 中注册
        DATABASE_ROUTERS = ['django_app.core.db_routing.ProjectDBRouter']

    路由逻辑:
      - 模型名在 PROJECT_MODEL_NAMES 中 → 路由到项目 DB
      - 其他模型 → 默认主库
      - 项目 DB 别名从线程局部变量 current_project_id 获取
    """

    def _get_project_db(self, model, **hints):
        """获取模型对应的项目 DB 别名"""
        if model.__name__ not in PROJECT_MODEL_NAMES:
            return None

        # 尝试从 hints 获取 project_id
        project_id = hints.get('project_id')
        if project_id is None:
            # 尝试从实例获取
            instance = hints.get('instance')
            if instance and hasattr(instance, 'project_id'):
                project_id = instance.project_id

        if project_id is None:
            # 从线程局部变量获取
            project_id = get_current_project_id()

        if project_id is None:
            return None

        alias = _get_project_db_alias(project_id)
        # 确保连接已注册
        get_project_engine(project_id)
        return alias

    def db_for_read(self, model, **hints):
        """读取时路由"""
        return self._get_project_db(model, **hints)

    def db_for_write(self, model, **hints):
        """写入时路由"""
        return self._get_project_db(model, **hints)

    def allow_relation(self, obj1, obj2, **hints):
        """允许同一 DB 内的关联"""
        db1 = self.db_for_read(type(obj1))
        db2 = self.db_for_read(type(obj2))
        if db1 is None and db2 is None:
            return True  # 都在主库
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """控制迁移:
        - 主库 (default): 只允许非项目模型迁移 (User, Project, ApiKey 等)
        - 项目库: 只允许项目模型迁移 (Module, QorRecord 等)
        """
        project_model_names = {name.lower() for name in PROJECT_MODEL_NAMES}
        if db == 'default':
            if app_label == 'core' and model_name:
                return model_name.lower() not in project_model_names
            return True
        if db.startswith('project_'):
            # A migration is still recorded by Django when all of its
            # operations are routed away. This keeps graph history complete
            # without copying users/auth/global tables into every project DB.
            if app_label != 'core':
                return False
            if model_name is None:
                # RunPython/RunSQL operations without a model hint are global
                # unless a migration explicitly opts into a project model.
                return False
            return model_name.lower() in project_model_names
        return None


# 兼容 settings.py 中的引用名
ProjectRouter = ProjectDBRouter


# =========================================================================
# ProjectContextMiddleware
# =========================================================================
class ProjectContextMiddleware:
    """Django 中间件: 从请求中提取 project_id 并存入 request 对象

    提取优先级:
      1. URL 路径: /api/modules/<id>/ 或 /api/projects/<id>/ 等
      2. Query 参数: ?project_id=<id>
      3. JSON Body: {"project_id": <id>} (仅 POST/PUT/PATCH)

    用法: 在 settings.MIDDLEWARE 中注册
        'django_app.core.db_routing.ProjectContextMiddleware'
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        project_id = self._extract_project_id(request)
        request.project_id = project_id
        if project_id is not None:
            set_current_project_id(project_id)
        else:
            set_current_project_id(None)

        response = self.get_response(request)
        return response

    def _extract_project_id(self, request):
        """从请求中提取 project_id"""
        path = request.path or ''

        # 1. URL 路径: 匹配 /api/modules/<id>/... 等已知模式
        m = re.search(
            r'/(?:modules|projects|tile_reviews|group_reviews|subsystem_reviews'
            r'|review_snapshots|review_files|alerts|data_snapshots'
            r'|records|notes|violations|runs)/(\d+)',
            path,
        )
        if m:
            return int(m.group(1))

        # 2. Query 参数
        pid = request.GET.get('project_id')
        if pid and pid.isdigit():
            return int(pid)

        # 3. JSON Body (仅 POST/PUT/PATCH)
        if request.method in ('POST', 'PUT', 'PATCH'):
            try:
                body = request.body
                if body:
                    data = json.loads(body)
                    pid = data.get('project_id')
                    if pid is not None:
                        return int(pid)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        return None


# =========================================================================
# 跨库查询辅助
# =========================================================================
def _resolve_project_ids(project_ids_str=''):
    """解析逗号分隔的 project ID 字符串

    返回: list[int] - 项目 ID 列表
    """
    if project_ids_str:
        proj_id_list = [int(x) for x in project_ids_str.split(',') if x.strip().isdigit()]
        if proj_id_list:
            return proj_id_list

    # 兜底: 所有存在项目 DB 的项目
    dbs = list_all_project_dbs()
    return [d['project_id'] for d in dbs]


def _map_module_ids_to_projects(module_id_set, proj_id_list=None):
    """批量查找 module ID 所属的项目, 返回 {project_id: set(module_id)}

    由于每个项目库的 module ID 独立自增, 同一 ID 可能存在于多个项目中,
    此函数返回每个项目中实际存在的 module ID 集合 (不做互斥分配).
    """
    from django.apps import apps
    Module = apps.get_model('core', 'Module')

    if proj_id_list is None:
        proj_id_list = _resolve_project_ids()

    project_module_map = {}

    for pid in proj_id_list:
        alias = _get_project_db_alias(pid)
        try:
            get_project_engine(pid)
            found = set(
                Module.objects.using(alias)
                .filter(id__in=list(module_id_set))
                .values_list('id', flat=True)
            )
            if found:
                project_module_map[pid] = found
        except OperationalError:
            continue

    return project_module_map


def query_records_by_projects(
    proj_id_list=None,
    module_ids_str='',
    versions_str='',
    owner_id=None,
    release_only=False,
    dir_prefix=None,
    order_desc=True,
    limit=5000,
):
    """按项目迭代查询 QorRecord, 跨库安全的查询模式

    参数:
      proj_id_list:  list[int], 限定项目; None = 全部有 DB 的项目
      module_ids_str: 逗号分隔的 module ID 字符串
      versions_str:   逗号分隔的版本字符串
      owner_id:       int
      release_only:   True = 仅 is_released
      dir_prefix:     str, 按 full_dir 前缀过滤
      order_desc:     True = released_at（为空回退 recorded_at）倒序
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

    from django.apps import apps
    QorRecord = apps.get_model('core', 'QorRecord')

    # 当指定了 module_ids 时, 必须先解析每个 module 属于哪个项目,
    # 因为各项目库的 module ID 独立自增, 直接用 module_id__in 在所有
    # 项目中过滤会误匹配其他项目中相同 ID 的模块.
    project_module_map = None
    if mod_id_filter:
        project_module_map = _map_module_ids_to_projects(mod_id_filter, proj_id_list)
        # 只查询实际包含所选模块的项目
        query_proj_list = [pid for pid in proj_id_list if pid in project_module_map]
    else:
        query_proj_list = list(proj_id_list)

    all_records = []
    for pid in query_proj_list:
        set_current_project_id(pid)
        alias = _get_project_db_alias(pid)
        try:
            get_project_engine(pid)
        except Exception:
            continue

        try:
            qs = QorRecord.objects.using(alias).select_related('module').all()
            if release_only:
                qs = qs.filter(is_released=True)
            if mod_id_filter and project_module_map:
                # 仅使用该项目中实际存在的 module ID 子集
                pid_mods = project_module_map.get(pid, set())
                if not pid_mods:
                    continue
                qs = qs.filter(module_id__in=pid_mods)
            if ver_filter:
                qs = qs.filter(version__in=ver_filter)
            if owner_id is not None:
                qs = qs.filter(owner_id=owner_id)
            if dir_prefix:
                qs = qs.filter(full_dir__startswith=dir_prefix)
            order = '-released_at' if order_desc else 'released_at'
            rows = list(qs.order_by(order, '-recorded_at', '-id')[:limit])
            for row in rows:
                # Preserve the source project after the thread-local router
                # advances to the next project database.
                row._qor_project_id = pid
            all_records.extend(rows)
        except OperationalError:
            continue
        except Exception:
            continue

    # 跨项目排序
    all_records.sort(
        key=lambda r: r.released_at or r.recorded_at or timezone.make_aware(
            datetime.min, timezone.get_current_timezone()
        ),
        reverse=order_desc,
    )
    return all_records[:limit]


def _find_qor_record_project(record_id):
    """查找包含指定 QorRecord ID 的项目 DB

    返回: project_id (int) 或 None
    """
    from django.apps import apps
    QorRecord = apps.get_model('core', 'QorRecord')

    for db_info in list_all_project_dbs():
        pid = db_info['project_id']
        alias = _get_project_db_alias(pid)
        try:
            get_project_engine(pid)
            if QorRecord.objects.using(alias).filter(id=record_id).exists():
                return pid
        except OperationalError:
            continue
    return None


def _find_module_project_id(module_id):
    """查找包含指定 Module ID 的项目 DB

    返回: project_id (int) 或 None
    """
    from django.apps import apps
    Module = apps.get_model('core', 'Module')

    for db_info in list_all_project_dbs():
        pid = db_info['project_id']
        alias = _get_project_db_alias(pid)
        try:
            get_project_engine(pid)
            if Module.objects.using(alias).filter(id=module_id).exists():
                return pid
        except OperationalError:
            continue
    return None