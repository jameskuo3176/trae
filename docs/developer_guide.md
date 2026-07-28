# QoR Recorder 开发文档：设计思路与开发流程

## 1. 项目背景与目标

### 1.1 问题来源
芯片设计流程中，Design Compiler (DC) 综合后会产出大量 QoR (Quality of Results) 数据，包括面积、时序、功耗、违例路径等。传统做法是用 Excel 手工汇总，存在以下痛点：

- **数据散落**：每次综合产出多份 CSV，分散在不同目录，难以汇总
- **对比困难**：跨版本/跨模块的对比需要手工拼接，效率低且易错
- **历史追溯难**：没有统一存储，旧版本数据容易丢失
- **可视化弱**：Excel 图表能力有限，无法交互式钻取

### 1.2 目标定位
QoR Recorder 是一个面向 IC 设计团队的**综合质量数据管理系统**，核心目标：

1. 统一存储多项目、多模块、多版本的综合数据
2. 提供 Web 化、交互式的可视化 Dashboard
3. 支持跨版本、跨模块的快速对比分析
4. 支持违例路径的下钻分析与版本间 diff
5. 数据可导出为 Excel/CSV，便于二次加工
6. 支持多数据库后端（SQLite / MySQL / MongoDB），适应团队规模增长

### 1.3 非目标
- 不替代综合工具，只做数据消费与分析
- 不做大规模数据流处理，定位为团队级（万条记录量级）工具
- 不做权限细粒度管理（admin / user / release 三类角色）

## 2. 技术选型

| 层 | 选型 | 选型理由 |
|---|---|---|
| Web 框架 | Flask 3.1 | 轻量、灵活，适合中小型内部工具；生态成熟 |
| ORM | Flask-SQLAlchemy | 与 Flask 无缝集成；支持多数据库后端、多 binds |
| 数据库后端 | SQLite（默认）/ MySQL / PostgreSQL / MongoDB | 单一变量 `DB_TYPE` 切换；按项目分库解决累计数据性能下降 |
| 数据处理 | pandas + openpyxl | CSV 解析与 Excel 导出的工业标准 |
| 前端图表 | ECharts (本地化) | 功能强大、交互丰富；本地化到 `static/vendor/` 支持离线 |
| 认证 | Flask-Login + Werkzeug | 会话管理 + 密码哈希，够用且不臃肿 |
| 模板 | Jinja2 (Flask 内置) | 服务端渲染，无前端构建依赖 |
| 数据库迁移 | Flask-Migrate (Alembic) | 主库 schema 版本管理；项目库用 ORM create_all 兜底 |

**选型原则**：内部工具优先「单进程可跑、易备份、随团队增长可扩展」。SQLite + Flask 单进程即可服务一个 10-20 人团队；按项目分库后单项目万级记录性能仍优良；多后端切换满足团队跨规模迁移需求。

## 3. 架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                      浏览器 (前端)                        │
│   dashboard.html / compare.html / admin.html            │
│   ECharts 图表 + Fetch API 调用后端                       │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP/JSON
┌────────────────────────▼────────────────────────────────┐
│                   Flask 应用 (app.py)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ 认证层    │  │ 路由层    │  │ 业务逻辑层            │  │
│  │ Flask-   │  │ 页面路由  │  │  - 跨库查询 (按项目迭代)│  │
│  │ Login    │  │ API 路由  │  │  - 聚合/对比/Diff     │  │
│  │ API Key  │  │ 导出路由  │  │  - Bus 合并算法       │  │
│  └──────────┘  └──────────┘  └──────────┬───────────┘  │
│                                         │              │
│  ┌──────────────────────────────────────▼───────────┐  │
│  │ DB 路由层 (core/db_routing.py)                     │  │
│  │  - __bind_key__='project' 的模型 → 项目库          │  │
│  │  - 其余 → 主库                                    │  │
│  │  - before_request 自动提取 project_id             │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                 数据层 (主库 + 项目库)                    │
│  ┌──────────────────────┐  ┌──────────────────────┐    │
│  │ 主库 (qor_recorder.db) │  │ 项目库 (qor_p_<id>.db)│    │
│  │ - users               │  │ - modules            │    │
│  │ - projects            │  │ - qor_records        │    │
│  │ - project_memberships │  │ - violation_paths    │    │
│  │ - api_keys            │  │ - run_notes          │    │
│  │ - user_dashboards     │  │ - tile_reviews ...   │    │
│  │ - dashboard_groups    │  │ - alert_rules ...    │    │
│  └──────────────────────┘  └──────────────────────┘    │
│  (可切换 MySQL/PostgreSQL/MongoDB)                       │
└─────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
QoR_Recorder/
├── app.py              # 主应用入口 (init_default_data)
├── config.py           # 配置 (DB_TYPE 切换, URI 构造)
├── db_init.py          # 数据库初始化/迁移入口 (sqlite/sql/mongodb)
├── models.py           # 数据模型 (__bind_key__ 区分主库/项目库)
├── core/               # 核心模块
│   ├── factory.py      # 应用工厂 (create_app)
│   ├── db.py           # 主库 SQLAlchemy 实例
│   ├── db_mongo.py     # MongoDB 适配
│   ├── db_routing.py   # 多库路由 (__bind_key__ 拦截, before_request 提取)
│   ├── project_db.py   # 项目库生命周期 (create/lock/unlock/delete)
│   ├── security.py     # CSRF / 限流
│   ├── errors.py       # 错误处理
│   └── __init__.py
├── routes/             # 路由蓝图
│   ├── auth.py         # 登录/登出
│   ├── main.py         # 页面路由 (dashboard/compare/admin)
│   ├── qor.py          # QoR 数据 API (含 query_records_by_projects)
│   ├── dashboard.py    # Dashboard API
│   ├── review.py       # Review 三级审核
│   ├── violations.py   # 违例路径
│   ├── admin.py        # 管理员操作
│   └── api_v1.py       # 外部 API (v1, 兼容 DC 脚本)
├── services/           # 业务服务
│   ├── qor_import.py   # CSV 导入
│   └── backup_service.py
├── migrate_to_per_project_db.py   # 历史数据 → 项目库迁移
├── migrate_sqlite_to_mongo.py     # SQLite → MongoDB 迁移
├── seed_demo_data.py              # 演示数据生成
├── qor_recorder.db     # 主库 SQLite 文件
├── qor_p_<id>.db       # 项目库文件 (每个项目一个)
├── backups/            # 启动时自动备份的主库历史
├── uploads/            # 上传的 CSV 文件暂存
├── migrations/         # Alembic 迁移 (主库)
└── templates/          # Jinja2 模板
```

### 3.3 分层职责
严格遵循「路由薄、业务厚、模型纯」的原则：

- **路由层**：只做参数提取、调用业务函数、返回 JSON/模板
- **业务层**：查询构建、数据清洗、聚合计算、Bus 合并、Diff 算法
- **模型层**：只定义字段与 `to_dict()`，不含业务逻辑；通过 `__bind_key__` 声明归属
- **解析层**：`qor_parser.py` 独立负责 CSV → dict 的转换，与数据库解耦
- **DB 路由层**：`core/db_routing.py` 负责「当前请求用哪个库」的决策

### 3.4 按项目分库架构（v4.0 核心设计）

**为什么按项目分库？**

1. **性能隔离**：项目累计数据量大时，单库查询拖慢整个系统；分库后单项目性能独立
2. **可归档**：项目周期结束后，整项目 DB 文件归档/锁定/删除都不影响其他项目
3. **物理级锁定**：`status=locked` 时将文件 `chmod 0444`，从文件系统层防止误写
4. **可清理**：硬删除项目只需删一个文件，零牵连
5. **可分团队管理**：未来可按项目分散到不同机器/存储

**架构设计**：

- **主库** `qor_recorder.db`：存系统级数据（用户、项目元数据、API Key、成员关系）
- **项目库** `qor_p_<id>.db`：每个项目一个文件，存该项目的所有业务数据
- **schema 同步**：项目库表结构与主库中带 `__bind_key__='project'` 的模型一致
- **跨库关系**：通过 `primaryjoin` + `foreign()` 显式声明，避免 ORM 误以为有外键约束

**模型归属**：

```python
class User(db.Model):
    __tablename__ = 'users'      # 主库 (无 __bind_key__)

class Project(db.Model):
    __tablename__ = 'projects'   # 主库

class Module(db.Model):
    __tablename__ = 'modules'
    __bind_key__ = 'project'     # 项目库

class QorRecord(db.Model):
    __tablename__ = 'qor_records'
    __bind_key__ = 'project'     # 项目库
```

**请求路由**：

1. `before_request` 钩子从 URL/query/body 提取 `project_id`
2. 验证后存入 `flask.g.current_project_id`
3. SQLAlchemy `do_orm_execute` 事件拦截 ORM 查询，若 model 属于项目库则替换 bind 为对应项目库 engine
4. 业务代码中 `Module.query` / `QorRecord.query` 等调用无需感知分库

**跨项目查询**（Dashboard 场景）：

```python
# core/db_routing.py
def query_records_by_projects(proj_id_list=None, ...):
    """按项目迭代查询 QorRecord, 跨库安全"""
    all_records = []
    for pid in proj_id_list:
        with switch_to_project(pid):
            q = QorRecord.query.filter(...)
            all_records.extend(q.order_by(...).all())
    all_records.sort(key=lambda r: r.recorded_at, reverse=True)
    return all_records
```

**关键决策**：

- 跨库 JOIN 不可用（无 FK 约束）→ 用「按项目迭代 + 内存合并」替代
- 项目库表用 ORM `create_all` 创建（无 alembic 升级路径）；新增表时改 `models.py` 即可
- 主库 schema 仍由 alembic 管理（`flask db upgrade`）
- 项目库独立 `qor_p_<id>.db` 文件，但跨项目关系（外键逻辑）通过 `primaryjoin` 显式声明

### 3.5 多数据库后端切换（v4.0）

通过单一环境变量 `DB_TYPE` 控制后端：

| DB_TYPE    | URI 构造                       | 适配器                          |
|------------|--------------------------------|---------------------------------|
| `sqlite`   | `sqlite:///<BASE_DIR>/qor_recorder.db` | 标准 SQLAlchemy            |
| `sql`      | `DATABASE_URL` 环境变量         | 标准 SQLAlchemy + 驱动 (pymysql/psycopg2) |
| `mongodb`  | `MONGODB_URI` 环境变量          | `core/db_mongo.py` + dual-write 抽象层 |

**MongoDB 模式特殊性**：

- 主库走 SQLite（只读回退）：Mongo 主要承担业务数据
- 通过 `repo.py` 抽象层实现 dual-write（同时写 Mongo + SQLite）
- 读优先 Mongo，SQLite 兜底
- 迁移脚本 `migrate_sqlite_to_mongo.py` 支持历史数据从 SQLite 迁到 Mongo

**配置入口**：

```python
# config.py
def _detect_db_type():
    explicit = os.environ.get('DB_TYPE', '').strip().lower()
    if explicit in ('sqlite', 'sql', 'mongodb'):
        return explicit
    # 兼容旧方式: 通过 DATABASE_URL 前缀推导
    url = os.environ.get('DATABASE_URL', '').lower()
    if url.startswith(('mysql', 'postgresql')): return 'sql'
    if url.startswith('mongodb'): return 'mongodb'
    return 'sqlite'
```

**启动入口**：

```bash
# 验证配置
python db_init.py --check

# 初始化（自动建库 + alembic 迁移 + demo 数据）
python db_init.py --seed

# 临时切换后端 (单次执行)
python db_init.py --db-type sql --check
```

## 4. 数据模型设计

### 4.1 ER 关系（含跨库关系）

```
主库:
User ──< UserDashboard
User ──< ApiKey
Project ──< ProjectMember
Project ──< DashboardGroup  (主键)

跨库关系 (无 FK, 用 primaryjoin 显式连接):
Project.modules    ──< Module (项目库)
Module.records     ──< QorRecord (项目库)
Project.dashboard_groups ──< DashboardGroup (项目库)

项目库:
Module ──< QorRecord ──< ViolationPath
                    └─< RunNote
TileReview ──< GroupReview ──< SubsystemReview
                    └─< ReviewSnapshot ──< ReviewFile
AlertRule ──< AlertEvent
DataSnapshot (独立)
```

### 4.2 表设计要点

#### 主库表

- **User / Project / ApiKey / ProjectMember / UserDashboard / DashboardGroup**：系统级数据，存主库
- **Project 扩展字段**（v4.0）：`status`（active/locked/archived/hidden）、`db_path`（项目库文件路径）、`hidden_at` / `hidden_by`（软删除）

#### 项目库表（__bind_key__='project'）

- **Module**：`(__bind_key__='project')`，`project_id` 字段仅作逻辑外键
- **QorRecord**：`(__bind_key__='project')`，核心业务表
- **ViolationPath / RunNote / TileReview / GroupReview / SubsystemReview / ReviewSnapshot / ReviewFile / AlertRule / AlertEvent / DataSnapshot**

#### QorRecord
- 核心表，存储一次综合运行的全部 QoR 指标
- **固定列**：覆盖面积、时序、功耗、单元统计、频率、物理（MBB/CG/utilization/congestion）6 大类共 30+ 指标
- **`full_dir` (v3.0 独立列)**：Run 的工作目录绝对路径（`<base_dir>/<sub_path>/<run_name>`），用于：
  - 解决同名 run 在不同 base_dir 下的歧义
  - 目录聚合 API（`/api/qor/aggregate?group_by=run|base_dir|module`）
  - Run 备注按目录精确关联
  - QoR 记录详情页（`/qor_record/<id>`）的路径展示
- **extra_fields (JSON)**：存储未映射到固定列的字段（如 `comment`、各 clock 的 period/wns/tns/path）。高频查询字段建为固定列并可索引，低频字段入 JSON，兼顾性能与灵活性
- `(module_id, version)` 作为业务唯一键，上传时做 upsert（已存在则更新）
- `is_released` 标记是否已发布（release 角色账号只能看到 `is_released=True` 的数据）

#### 跨库关系声明（关键代码模式）

```python
# models.py
class Module(db.Model):
    __bind_key__ = 'project'
    project_id = db.Column(db.Integer, nullable=False)  # 仅作整数存储
    # 跨库关系: Module -> Project (主库), 用 primaryjoin 显式连接
    project = db.relationship(
        'Project',
        primaryjoin='foreign(Module.project_id)==Project.id',
        viewonly=True,
    )
```

#### RunNote（v3.0 起独立模型）
- 记录 Run 级别的备注项（item + description）
- 通过 `(qor_record_id, full_dir)` 关联到具体 run
- 重复上传同 `(record, full_dir)` 会覆盖，不会累积
- 不同 `full_dir` 的备注独立，互不影响

#### TileReview / GroupReview / SubsystemReview（v3.0 新增）
- 三级审核模型：Tile（单模块）→ Group（模块组）→ Subsystem（子系统）
- 状态流转：`Draft → Submitted → Approved`，`Rejected` 后可修订再提交
- GroupReview 自动汇总其下 TileReview 的指标
- SubsystemReview 自动汇总其下 GroupReview 的指标
- 配合 ReviewSnapshot 归档历史快照（包含违规路径文件、JSON 报告等）

#### UserDashboard
- 每用户可保存多份 Dashboard 配置（JSON），支持 `is_default`
- 配置内容包括选中的项目、模块、图表类型、指标等

#### User.theme (JSON)
- 每用户独立的界面主题，存储为 JSON 字符串于 `users.theme` 字段
- 字段包括 `primary / primary_gradient_end / background / surface / surface_hover / text / text_secondary / border / navbar_text / navbar_text_active`
- `get_theme()` 自动与 `DEFAULT_THEME` 合并，保证字段完整性，兼容历史数据
- 默认主题 `classic`（深蓝主色 `#1a237e`，深灰文字 `#333333`，白底）
- 通过 `THEME_PRESETS` 提供 classic / dark / green / purple / orange 5 套预设
- 颜色值在后端用正则校验（`#hex` / `rgb()` / `rgba()` / `hsl()` / `hsla()`），写入前经 `_validate_theme` 清洗

### 4.3 设计权衡

**为什么固定列 + JSON？**
早期方案曾考虑把所有指标都存 JSON，但这样无法用 SQL 高效过滤/排序。最终采用**混合方案**：
- 高频查询字段（area_total、wns_setup 等）建为固定列，可索引
- 低频/可变字段（各 clock 的细节、comment）存入 `extra_fields` JSON

**为什么按项目分库？**
1. 累计数据性能问题：单 SQLite 文件在 10w+ 记录后查询明显变慢；分库后每项目独立 IO
2. 数据隔离：项目数据生命周期独立，删除/归档不影响其他项目
3. 物理级保护：锁定项目直接 chmod 0444，无法绕过应用层误写
4. 备份灵活：可单独备份重要项目

**为什么不用一个 MongoDB collection？**
- SQLite 单文件仍是最简单的运维/备份模式
- MongoDB 是可选升级路径（团队规模扩张后）
- 双后端兼容保证老数据可平滑迁移

## 5. 核心模块设计

### 5.1 CSV 解析器 (qor_parser.py)

#### 设计挑战
DC 导出的 CSV 格式不统一：
- 列名变体多：`area_total` / `total_area` / `Area` / `TOTAL_CELL_AREA`
- 编码不一：UTF-8 BOM / GBK / Latin-1
- 数据脏：空值表示有 `-`、`N/A`、`NULL`、空字符串等多种
- 数值格式杂：科学计数法、千分位逗号、带单位后缀

#### 解决方案
1. **列名模糊匹配**：定义 `FIELD_ALIASES` 映射表，标准化时统一转小写、去空格/下划线/连字符
2. **编码自动探测**：按 `utf-8-sig → utf-8 → gbk → latin-1` 顺序尝试解码
3. **安全数值解析**：`_safe_float()` 函数处理千分位、单位后缀、百分比、空值标记
4. **位置兜底**：若表头完全无法识别，按标准列顺序位置映射
5. **统计返回**：返回 `{records, stats, timing_group}`，便于前端展示解析质量

#### 违例路径解析的特殊处理
- `timing_group` 从文件名提取（如 `SRAMCLK_violations.csv` → `SRAMCLK`）
- 处理 `11=-212835712990` 这种异常格式（取 `=` 前的数值）
- 列名别名独立于 QoR 解析器，避免污染

### 5.2 DB 路由层 (core/db_routing.py)

#### 设计目标
让业务代码（routes/qor.py 等）**不感知分库**：
```python
# 业务代码
@bp.route('/api/qor_data')
def api_get_qor_data():
    records = QorRecord.query.filter(...).all()  # 自动从正确项目库读
```

#### 实现方式

**方式 A：自动路由（推荐）**

```python
# core/db_routing.py
@event.listens_for(Session, 'do_orm_execute')
def _route_query(execute_state):
    """拦截 ORM 查询, 根据 model 自动路由到项目库"""
    if execute_state.is_orm_statement:
        mapper = execute_state.bind_arguments.get('mapper')
        if mapper and getattr(mapper.class_, '__bind_key__', None) == 'project':
            pid = get_active_project_id()
            bind_arguments['bind'] = get_project_engine(pid)
```

**方式 B：手动切换（复杂场景）**

```python
from core.db_routing import switch_to_project
with switch_to_project(pid):
    modules = Module.query.all()
```

#### before_request 自动提取 project_id

```python
# core/db_routing.py
def _extract_project_id_from_request():
    # 1. URL path: /modules/<id>, /projects/<id>, /records/<id> ...
    # 2. ?project_id=xx (query)
    # 3. JSON body: {"project_id": xx}
    ...
```

支持的 URL 模式：`/modules/<id>` / `/projects/<id>` / `/tile_reviews/<id>` / `/group_reviews/<id>` / `/subsystem_reviews/<id>` / `/review_snapshots/<id>` / `/review_files/<id>` / `/alerts/<id>` / `/data_snapshots/<id>` / `/records/<id>` / `/notes/<id>` / `/violations/<id>` / `/runs/<id>`

### 5.3 项目库生命周期 (core/project_db.py)

```python
def create_project_db(project_id: int) -> str:
    """为新项目创建独立的 .db 文件, 跑迁移, 启用 WAL."""
    path = project_db_path(project_id)  # qor_p_<id>.db
    # 1. 创建空文件 + 启用 WAL
    # 2. ORM create_all 创建表结构
    return path

def lock_project_db(project_id: int) -> bool:
    """status=locked 时: chmod 0444 (只读)"""
    close_project_engine(project_id)  # 释放缓存
    sqlite3.connect(path).execute('PRAGMA wal_checkpoint(TRUNCATE)')
    os.chmod(path, 0o444)
    return True

def unlock_project_db(project_id: int) -> bool:
    os.chmod(path, 0o644)

def delete_project_db(project_id: int) -> bool:
    """硬删除: 删除文件 + WAL/SHM/Journal"""
    ...
```

### 5.4 数据上传与清洗 (routes/api_v1.py `_save_records_to_db`)

#### 清洗策略
```python
NUMERIC_RANGES = {
    'area_total': (0, 1e9),       # 面积必须非负且 < 10亿
    'wns_setup': (-1e6, 1e6),     # WNS 合理范围
    'power_total': (0, 1e6),      # 功耗非负
    ...
}
```
- **数值范围校验**：超出合理范围的值置为 None（视为脏数据）
- **NaN/Infinity 过滤**：`v != v` 判断 NaN
- **字符串截断**：超长字符串截断至 500 字符，防止破坏 DB
- **Upsert**：(module_id, version) 已存在则更新，避免重复记录

#### 四种数据类型（v3.0）
上传时通过 `data_type` 表单字段区分：
1. **`qor`**：新建 QorRecord（若 (module_id, version) 已存在则更新）。`full_dir` 字段被同时写入 `QorRecord.full_dir` 独立列和 `extra_fields` JSON（兼容老数据回填）。
2. **`power`**：合并到已有 QorRecord（按 模块+版本 匹配），仅更新 `power_*` 字段
3. **`violation`**：关联到已有 QorRecord（违例路径必须先有 QoR 记录），`timing_group` 从文件名提取
4. **`notes`**：按 (qor_record_id, full_dir) 删除并重建 RunNote 记录。full_dir 缺失则关联到该 (module, version) 的第一条记录（兼容老数据）

#### full_dir 来源优先级（v3.0 核心约定）
1. CSV 行内 `full_dir` 列（最高优先，notes/qor/power 都支持）
2. 上传时通过 `--full-dir` 参数 / `QOR_FULL_DIR` 环境变量 / 表单 `full_dir` 字段传入
3. 若都没有 → `full_dir = null`，作为该 module+version 的通用备注

#### API 端点
- `POST /api/v1/upload` （multipart/form-data，推荐，DC 脚本使用）
- `POST /api/v1/qor/upload` （JSON 格式，程序化提交）
- `GET  /api/run_notes?module_id=&version=&full_dir=` （获取 Run 备注）

#### 配套脚本
- `scripts/upload_qor.sh`：bash 封装 curl，4 种 data_type 全支持
- `scripts/Makefile.example`：DC 流程 Makefile 模板，覆盖 `make upload / upload-all / release / check-api-key` 目标
- `seed_demo_data.py`：演示数据生成，5 项目 / 37 模块 / 227 records

### 5.5 违例路径分析

#### Bus 合并算法
**问题**：一个 64-bit bus 的 64 条违例路径本质上是一个问题，逐条展示噪音太大。

**算法** ([_group_bus_endpoints](file:///d:/trae/trace_clock/qor_recorder/QoR_Recorder/app.py#L336-L366))：
```python
# 正则提取 bus 前缀和后缀
m = re.match(r'^(.+?)(?:_)(\d+)(?=[/_]|$)(.*)$', endpoint)
# data_bus_7_/D → prefix="data_bus", suffix="_/D"
# data_bus_0_/D ~ data_bus_63_/D 归为同一 bus_key
```
- 同一 bus_key 的多条记录合并为一条，`vio_number` 统计合并数量
- 保留 slack 最差的那一条（因为查询时按 slack 升序，第一条即最差）
- **取数优化**：bus 合并时先取 `limit×20` 条再分组，避免分组后条数不足

#### 跨版本 Diff 算法
**问题**：如何对比同一模块两个版本（run）的违例差异，判断时序变好还是变差？

**算法** ([api_violations_diff](file:///d:/trae/trace_clock/qor_recorder/QoR_Recorder/app.py#L388-L488))：
1. 按 `(startpoint, endpoint)` 作为路径唯一键
2. 在两版本中分别建立字典：`{path_key: path_record}`
3. 遍历两字典的并集，计算每条路径的状态：
   - `both`：两版都有 → 计算 `delta = slack_b - slack_a`（正=改善，负=恶化）
   - `new`：B 有 A 无 → 新增违例
   - `removed`：A 有 B 无 → 已修复
4. 按 delta 升序排序（恶化最多的在前）
5. 汇总统计：改善数、恶化数、新增数、修复数
6. 可选 Bus 合并

### 5.6 Dashboard 可视化

#### 图表设计
| 图表 | 类型 | 用途 |
|---|---|---|
| 面积趋势 | 柱状图 | 多模块多版本面积对比 |
| 时序趋势 | 折线图 | WNS/TNS 随版本变化 |
| 功耗趋势 | 柱状图 | 功耗分解对比 |
| 单元统计 | 堆叠柱状图 | 组合/时序单元占比 |
| 面积构成 | 饼图 | 多选模块的面积占比 |

#### 前后端交互
- 前端通过 Fetch API 调用 `/api/qor_data`、`/api/compare` 等接口
- 后端返回 JSON，前端用 ECharts 渲染
- 违例面板有独立的 4 级联动下拉框（模块→版本→TG→CSV），与顶部图表筛选器解耦

## 6. 开发流程

### 6.1 环境搭建
```bash
# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库（自动按 DB_TYPE 切换后端）
python db_init.py --seed
# 上面会自动建主库 + 跑 alembic 迁移 + 创建 demo 项目库 + seed 演示数据

# 4. 启动
python app.py
# 访问 http://localhost:5000，admin/admin@2026
```

### 6.2 切换数据库后端

```bash
# SQLite (默认)
DB_TYPE=sqlite python db_init.py --seed

# MySQL
DB_TYPE=sql DATABASE_URL='mysql+pymysql://root:pwd@localhost:3306/qor_recorder' \
  python db_init.py --seed

# MongoDB
DB_TYPE=mongodb MONGODB_URI=mongodb://localhost:27017 \
  python db_init.py --seed
```

### 6.3 开发迭代节奏
项目采用「需求驱动、小步快跑」的迭代方式：

1. **需求确认**：与用户确认数据格式、查询场景、展示诉求
2. **模型先行**：先在 `models.py` 定义/修改表结构
   - 主库表：自动通过 `flask db migrate` + `flask db upgrade` 升级
   - 项目库表：直接生效（下次 `create_project_db` 用 ORM `create_all` 应用）
3. **解析器开发**：在 `qor_parser.py` 实现新格式的解析，用真实 CSV 验证
4. **API 开发**：在 `routes/` 实现路由，用脚本或 Postman 测试
5. **前端开发**：在 `templates/` 实现页面，浏览器验证
6. **数据验证**：用 demo 数据或真实数据端到端验证

### 6.4 数据库迁移策略

**主库**（v4.0 起使用 Flask-Migrate / Alembic）：
```bash
# 修改 models.py 后
flask db migrate -m "add xxx"
flask db upgrade
```

**项目库**：修改 `models.py` 中带 `__bind_key__='project'` 的模型即可。下次新创建项目库时自动应用 `create_all`；已有项目库需要手动跑 `db_init.py --migrate-only` 或调用 `migrate_to_per_project_db.py` 重新建表。

**跨项目迁移**（v3.x → v4.0 升级）：
```bash
# 1. 升级代码 + alembic 主库迁移
flask db upgrade

# 2. 迁移历史业务数据到项目库
python migrate_to_per_project_db.py --dry-run  # 预览
python migrate_to_per_project_db.py             # 执行
python migrate_to_per_project_db.py --clean     # 清理主库残留
```

**跨后端迁移**（SQLite → MongoDB）：
```bash
# 1. 设置 DB_TYPE=mongodb + MONGODB_URI
# 2. 跑迁移脚本
python migrate_sqlite_to_mongo.py --dry-run
python migrate_sqlite_to_mongo.py
```

### 6.5 测试方式

- 单元测试：`test_*.py`（如 `test_qor_aggregate.py`, `test_review_workflow.py`）
- 端到端测试：`_verify_e2e.py` 验证主库 + 项目库 + ORM 路由
- HTTP 端点测试：`_http_test.py`, `test_groups_http.py`
- 集成测试：MongoDB dual-write 模式通过 `test_groups_and_repo.py` 验证

### 6.6 代码规范
- 中文注释（与用户语言一致）
- 函数文档字符串说明参数、返回值、行为
- 业务函数以 `_` 前缀表示内部辅助（如 `_save_records_to_db`）
- 路由函数以 `api_` 前缀表示 API，以 `admin_` 前缀表示管理员路由

## 7. 安全设计

### 7.1 认证与授权
- 密码使用 Werkzeug 的 `generate_password_hash` 哈希存储（PBKDF2）
- 所有路由均加 `@login_required`，管理路由额外检查 `current_user.is_admin`
- Flask-Login 管理会话，未登录用户重定向到 `/login`

### 7.2 数据安全
- 上传文件大小限制 16MB（`MAX_CONTENT_LENGTH`）
- 只允许 `.csv` 扩展名
- 数值范围校验防止脏数据污染
- 字符串截断防止超长输入破坏 DB/JSON

### 7.3 安全增强 (已实现)
- `SECRET_KEY` 默认值仅在 `DEBUG=1` 模式下生效, 生产环境 (`DEBUG=0`) 必须通过环境变量覆盖, 否则启动会被拒绝 (`ENFORCE_SECRET_KEY=1`)
- SQLite 采用 WAL 模式 + busy_timeout + 重试装饰器缓解写并发; 团队级 (< 20 人) 足够, 大规模团队可切换 MySQL
- CSRF 保护: 所有 POST/PUT/DELETE/PATCH 端点强制校验 CSRF Token (API Key 认证的请求豁免)
- 登录限流: 每 IP 每分钟最多 5 次 `/login` 请求
- Session Cookie: `HttpOnly=True`, `SameSite='Lax'`, HTTPS 部署时启用 `Secure`
- 角色权限: admin / user / release 三级, release 仅可查看已发布数据 (`is_released=True`)
- API 认证: 支持 Session + X-API-Key 双轨认证, 适用于 DC 流程自动化
- 项目库物理锁定: `status=locked` 时 DB 文件 `chmod 0444`，防止绕过应用层的写入
- 密码强度校验: `security.validate_password()` 要求 >= 8 位 + 字母 + 数字 + 非弱口令黑名单 (`12345678` / `password` / `admin123` 等), 改密和重置密码端点统一调用
- 强制改密: `User.must_change_password` 标志位, 触发场景包括首次创建账号 (默认 admin/user/release) + 管理员重置密码, before_request 钩子拦截所有非改密/登出端点, 强制跳转 `/change_password` 页

### 7.4 强制改密流程 (must_change_password)

**触发场景**：

| 场景 | 设置 `must_change_password=True` 的位置 |
|---|---|
| 系统初始化默认账号 | `app.py::init_default_data` 创建 admin / user / release 时 |
| 管理员重置密码 | `routes/admin.py::admin_reset_user_password` |
| 兜底检查 | `app.py::init_default_data` 启动时检测到账号仍用出厂默认密码时 |

**清零场景**：

- `routes/admin.py::user_change_own_password` 改密成功后, 同时更新 `password_changed_at = utcnow()`

**拦截实现** ([core/security.py](file:///d:/trae/trace_clock/qor_recorder/QoR_Recorder/core/security.py))：

```python
MUST_CHANGE_ALLOWED_EP = {
    'user_change_own_password',       # API
    'admin.user_change_own_password',  # 蓝图全名
    'logout',
    'change_password_page',
}

@app.before_request
def _security_before_request():
    if (current_user.is_authenticated
            and getattr(current_user, 'must_change_password', False)):
        ep = request.endpoint
        if ep not in MUST_CHANGE_ALLOWED_EP:
            # 写操作: 403
            if request.method in ('POST','PUT','DELETE','PATCH'):
                return jsonify({'error':'请先修改密码后再操作',
                                'must_change_password':True}), 403
            # GET 受保护页面: 重定向到 /change_password
            if request.method == 'GET' and ep in MUST_CHANGE_REDIRECT_EP:
                return redirect('/change_password')
    ...
```

**端点 endpoint 名约定**：

- 蓝图下路由的 endpoint 是 `<bp>.<func>` 形式 (如 `admin.user_change_own_password`)
- `factory.add_url_rule(..., endpoint='xxx', ...)` 注册的端点是 `xxx` (无前缀)
- 白名单必须同时列出短名和全名 (因为 url_for 接受两者)

**前端改密页** ([templates/change_password.html](file:///d:/trae/trace_clock/qor_recorder/QoR_Recorder/templates/change_password.html))：

- 实时显示密码强度 (弱/中/强, 列出未通过项)
- 必须填旧密码 + 新密码 + 确认新密码
- 提交时带 `X-CSRF-Token` 头
- 改密成功后跳转回首页 (或仍留在改密页若后端返回 must_change_password=True)

## 8. 性能考量

### 8.1 查询优化
- 关键字段建索引：`module_id`、`version`、`timing_group`、`qor_record_id`、`full_dir`
- 列表查询限制 5000 条，防止全表扫描
- 违例查询限制最大 2000 条
- 跨项目查询：按项目迭代 + 内存合并（替代跨库 JOIN）

### 8.2 前端优化
- ECharts 本地化到 `static/vendor/`，减少网络依赖
- 大表用 `max-height + overflow:auto` 虚拟滚动
- 端点字段超长时 `text-overflow:ellipsis`，hover 显示完整值

### 8.3 Bus 合并的取数策略
```python
# Bus 合并时先取更多数据再分组，避免分组后条数不足
if bus_grouping:
    fetch_limit = min(total, max(limit * 20, 2000))
```
这是一个重要的设计决策：直接 `limit(N)` 再分组会导致分组后不足 N 条。改为先取 `limit×20` 再分组再截断，保证了用户体验。

### 8.4 按项目分库的性能优势
- 10w 记录级单项目：单库下查询 > 1s，分库后 < 100ms
- 多项目并发查询：分库后各项目 IO 不互斥
- 大项目归档：直接迁移/备份/锁定单文件，不影响其他项目

## 9. 扩展性与未来方向

### 9.1 当前架构的扩展点
- **数据库后端**：`DB_TYPE` 环境变量切换 sqlite / sql / mongodb，无需改代码
- **按项目分库**：`__bind_key__='project'` 模式可扩展到任意粒度（如按 tenant 分）
- **解析器**：`FIELD_ALIASES` 可继续扩展，支持更多 DC 版本的列名变体
- **图表**：ECharts 配置化，新增图表只需加一个 `render*Chart()` 函数

### 9.2 已实现的扩展
- ✅ 项目软删除（`status=hidden`）
- ✅ 项目锁定（物理只读 + 状态校验）
- ✅ MongoDB dual-write 抽象层
- ✅ API Key 认证（DC 流程自动化）
- ✅ 主题自定义（CSS 变量 + 服务端注入）
- ✅ 三级 Review 工作流
- ✅ 目录聚合 API（`group_by=run|base_dir|module`）
- ✅ QoR 记录详情页

### 9.3 潜在改进方向
1. **API 化**：将模板渲染改为纯 API，前端用 React/Vue 重构
2. **项目级权限**：基于 ProjectMember 的细粒度权限
3. **跨项目数据汇总**：内置跨项目合并报表
4. **趋势预警**：WNS 突然恶化时自动告警
5. **MongoDB 写入优化**：批量写 + 异步队列

## 10. 经验总结

### 10.1 做对的事
- **SQLite 优先 + 分库扩展**：单文件简单运维起步，按项目分库解决性能瓶颈
- **多后端抽象**：`DB_TYPE` 一键切换，避免团队规模变化时的硬迁移
- **混合存储**：固定列 + JSON 的组合，兼顾性能与灵活性
- **解析器独立**：CSV 解析与业务逻辑解耦，便于单独测试和复用
- **Bus 合并**：这个特性极大提升了违例分析的效率，是核心价值点
- **软删除 + 物理锁定**：既防误操作，又保留恢复可能

### 10.2 教训
- **f-string 转义**：在 shell 中用 `python -c` 执行含双引号的 f-string 会出错，应改用脚本文件
- **Flask debug 模式**：修改文件会自动重载，但有时不生效，需手动重启
- **正则贪婪性**：bus 合并的正则用了 `(.+?)` 非贪婪匹配，避免误匹配
- **跨库 JOIN 不可用**：SQLAlchemy 跨库无 FK 关系时，ORM 自动 JOIN 会失败；需用 `query_records_by_projects` 显式迭代
- **`_app_ctx_stack` 嵌套**：在同一个 `app_context` 内既做 data prep 又处理 request，会导致 `current_user` 解析错误；应分离为独立函数，app_context 退出后再处理
- **alembic 跨项目库**：项目库与主库使用相同的 model 定义，但项目库由 ORM `create_all` 管理（避免 alembic 版本爆炸）

### 10.3 v4.0 关键决策记录

| 决策                       | 原因                                                                                   |
|----------------------------|----------------------------------------------------------------------------------------|
| 主库 + 项目库分库          | 单项目大数据量性能下降；需物理级保护（锁定/删除）                                       |
| `__bind_key__` 路由         | 业务代码不感知分库；最小侵入式改造                                                     |
| 跨库无 FK + primaryjoin    | SQLAlchemy 跨库查询不会自动加 FK 约束；用 primaryjoin 显式声明                          |
| ORM create_all 替代 alembic | 项目库表结构简单（与主库部分模型一致），无需版本管理；新增表改 model 即可                |
| 跨项目查询用迭代合并        | 跨库 JOIN 不可用；按项目迭代 + 内存排序是当前最简单可靠方案                             |
| MongoDB dual-write          | 兼容旧代码 + 平滑迁移；SQLite 作为兜底保证系统不会因为 Mongo 故障停机                  |

---

*文档版本：4.0 | 最后更新：2026-07-28（按项目分库架构 + MongoDB dual-write + 多后端切换）*
