# QoR Recorder 开发文档：设计思路与开发流程

> 本文档描述当前运行架构：**Django 5.2 API + Vue 3 SPA + 主库/项目库分离**。
> 启动、迁移和部署必须以第 6 节及 `deploy/README.md` 为准，不再使用 Flask 命令。

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
- 不做业务数据的细粒度行级权限（v5.0 起为 admin / owner / viewer 三级角色）

## 2. 技术选型

| 层 | 选型 | 选型理由 |
|---|---|---|
| Web 框架 | Django 5.2 + Gunicorn | 自带 ORM、认证、Session、CSRF、迁移；生产 WSGI |
| ORM | Django ORM + Database Router | 主库/项目库动态路由（`ProjectDBRouter`） |
| 数据库后端 | SQLite（默认）/ MySQL / PostgreSQL / MongoDB | `DB_TYPE` + `PERSISTENCE_MODE` 双变量切换；按项目分库解决累计数据性能下降 |
| 数据处理 | pandas + openpyxl | CSV 解析与 Excel 导出的工业标准 |
| 前端 | Vue 3 + Vite + ECharts + Pinia + Vue Router | SPA；依赖随前端构建打包，不在运行时访问 CDN |
| 认证 | Django session + X-API-Key 双轨 | 浏览器走 cookie 会话；DC 脚本走 API Key |
| 前端托管 | `FRONTEND_MODE=vue`（默认）Django 直接托管 Vue 构建产物 | 轻量单服务部署；legacy 页面保留在 `/legacy/` 前缀下回滚 |
| 数据库迁移 | Django migrations | `python manage.py migrate` |

**选型原则**：内部工具优先「单进程可跑、易备份、随团队增长可扩展」。SQLite + Django 单进程即可服务一个 10-20 人团队；按项目分库后单项目万级记录性能仍优良；多后端切换满足团队跨规模迁移需求。

## 3. 架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                          浏览器 (前端)                        │
│  frontend-vue/ (Vue 3 SPA: Vue Router + Pinia + ECharts)    │
│  Login / Dashboard / Admin / Review / RecordDetail          │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP/JSON (+ Cookie Session / X-CSRFToken)
┌───────────────────────────▼─────────────────────────────────┐
│                Django 应用 (django_app)                       │
│  ┌───────────┐ ┌───────────┐ ┌───────────────────────────┐   │
│  │ 认证层     │ │ 路由层     │ │ 业务逻辑层                 │   │
│  │ Session   │ │ urls.py   │ │ - 跨库查询 (按项目迭代)      │   │
│  │ API Key   │ │ api/views │ │ - 聚合/对比/Diff            │   │
│  │ CSRF      │ │ api_v2    │ │ - Bus 合并算法              │   │
│  │ 中间件     │ │ core/views│ │ - 周评审/风险评级            │   │
│  └───────────┘ └───────────┘ └─────────────┬─────────────┘   │
│                                             │                 │
│  ┌──────────────────────────────────────────▼───────────────┐ │
│  │ DB 路由层 (django_app/core/db_routing.py)                 │ │
│  │  - ProjectContextMiddleware 提取 project_id              │ │
│  │  - ProjectDBRouter 按模型名路由到项目库 alias             │ │
│  │  - query_records_by_projects() 跨项目迭代查询             │ │
│  └──────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                  数据层 (主库 + 项目库)                        │
│  ┌───────────────────────┐   ┌──────────────────────────┐    │
│  │ 主库 (qor_recorder.db) │   │ 项目库 (qor_p_<id>.db)    │    │
│  │ - users               │   │ - modules                │    │
│  │ - projects            │   │ - qor_records            │    │
│  │ - project_members     │   │ - violation_paths        │    │
│  │ - global_modules      │   │ - run_notes              │    │
│  │ - api_keys            │   │ - tile/group/subsystem    │    │
│  │ - user_dashboards     │   │   _reviews / snapshots    │    │
│  │ - weekly_run_selections│  │ - record_annotations      │    │
│  │ - backup_records ...  │   │ - alert_rules / events    │    │
│  └───────────────────────┘   └──────────────────────────┘    │
│  (DB_TYPE 可切换 MySQL/PostgreSQL/MongoDB)                    │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
qor_recorder_django/
├── QoR_Recorder/                  # Django 后端
│   ├── manage.py                  # Django 管理入口
│   ├── django_app/
│   │   ├── settings.py            # 配置 (DB_TYPE / PERSISTENCE_MODE / FRONTEND_MODE)
│   │   ├── urls.py                # API + Legacy 页面 + Vue SPA 托管
│   │   ├── wsgi.py                # WSGI 入口 (Gunicorn)
│   │   ├── api/
│   │   │   ├── views.py           # 大部分 API 视图 (admin / review / dashboard / v1)
│   │   │   └── apps.py
│   │   ├── api_v2.py              # v2 API (records / violations / notes / annotations)
│   │   ├── repositories.py        # 仓储层 (Mongo hybrid 抽象)
│   │   ├── core/
│   │   │   ├── models.py          # 全部数据模型 (主库 + 项目库)
│   │   │   ├── db_routing.py      # 多库路由 + 项目库生命周期 + 跨库查询
│   │   │   ├── middleware.py      # 自定义中间件 (安全 / 限流)
│   │   │   ├── security.py        # CSRF / 密码强度 / API Key 校验
│   │   │   ├── decorators.py      # 权限装饰器
│   │   │   ├── views.py           # Legacy 页面视图
│   │   │   ├── context_processors.py
│   │   │   ├── errors.py
│   │   │   ├── management/commands/  # init_default_data / restore_backup / sync_review_hierarchy ...
│   │   │   └── migrations/        # Django 迁移 (主库 schema)
│   │   └── services/              # 业务服务
│   │       ├── qor_import.py      # CSV 解析与导入
│   │       ├── json_upload.py     # DC JSON 报告导入
│   │       ├── path_derivation.py # Run 路径推导
│   │       ├── timing_normalization.py
│   │       ├── weekly_review.py   # 周评审领域逻辑
│   │       ├── review_hierarchy.py# YAML 层级同步
│   │       ├── risk_rating.py     # 风险评级
│   │       └── backup_service.py  # 备份/恢复 (manifest + 校验)
│   ├── config/
│   │   └── review_hierarchy.yaml  # 评审层级配置
│   ├── templates/                 # Django 模板 (legacy / FRONTEND_MODE=legacy)
│   ├── static/                    # 静态资源 (legacy JS + vendor echarts)
│   ├── tests/                     # pytest 后端测试
│   ├── docs/                      # 文档
│   ├── scripts/                   # upload_qor.sh / Makefile.example / gvim 协议
│   ├── deploy/                    # nginx / systemd / README
│   ├── data/                      # 主库 + 项目库 .db 文件 (运行时生成)
│   ├── backups/                   # 启动时自动备份的主库历史
│   ├── uploads/                   # 上传文件暂存
│   ├── requirements.txt
│   └── start.sh                   # Gunicorn 启动脚本
└── frontend-vue/                  # Vue 3 前端 (唯一前端源)
    ├── index.html
    ├── vite.config.js
    ├── src/
    │   ├── main.js / App.vue
    │   ├── router/index.js        # 路由 + 守卫 (登录/角色)
    │   ├── stores/                # Pinia (auth / dashboard / filters ...)
    │   ├── api/                   # 各资源 API 客户端 (Fetch)
    │   ├── views/                 # Login / Dashboard / Admin / Review / RecordDetail
    │   ├── components/            # 组件 (charts / dashboard / review / admin / layout ...)
    │   ├── composables/           # useCharts / useGvim / useDialogFocus / useTheme ...
    │   ├── utils/                 # csrf / format / storage / timing
    │   └── styles/                # CSS 变量主题
    └── tests/                     # Vitest 单元测试 + Playwright e2e
```

### 3.3 分层职责
严格遵循「路由薄、业务厚、模型纯」的原则：

- **路由层**：只做参数提取、调用业务函数、返回 JSON
- **业务层**：查询构建、数据清洗、聚合计算、Bus 合并、Diff 算法
- **模型层**：只定义字段与 `to_dict()`，不含业务逻辑
- **解析层**：`services/qor_import.py` 独立负责 CSV → dict 转换，与数据库解耦
- **DB 路由层**：`core/db_routing.py` 负责「当前请求用哪个库」的决策

### 3.4 主库 + 项目库架构（按项目分库）

**为什么按项目分库？**

1. **性能隔离**：项目累计数据量大时，单库查询拖慢整个系统；分库后单项目性能独立
2. **可归档**：项目周期结束后，整项目 DB 文件归档/锁定/删除都不影响其他项目
3. **物理级锁定**：`status=locked` 时将文件设为只读，从文件系统层防止误写
4. **可清理**：硬删除项目只需删一个文件，零牵连
5. **可分团队管理**：未来可按项目分散到不同机器/存储

**模型归属**（[models.py](file:///d:/trae/trace_clock/qor_recorder_django/QoR_Recorder/django_app/core/models.py)）：

```python
# 主库 (default): User / Project / ProjectMember / GlobalModule / ProjectModule /
#   ReviewGroup / WeeklyRunSelection / DataLock / ApiKey / BackupRecord / UserDashboard

# 项目库 (project_<id>): Module / QorRecord / ViolationPath / RunNote /
#   RecordAnnotation / RecordAnnotationImage / DashboardGroup / AlertRule /
#   AlertEvent / DataSnapshot / TileReview / GroupReview / SubsystemReview /
#   ReviewSnapshot / ReviewFile
```

**请求路由**（[db_routing.py](file:///d:/trae/trace_clock/qor_recorder_django/QoR_Recorder/django_app/core/db_routing.py)）：

1. `ProjectContextMiddleware` 从 URL / query / JSON body 提取 `project_id`，存入 `request.project_id` 与线程局部变量
2. `ProjectDBRouter.db_for_read/write` 判断模型名是否在 `PROJECT_MODEL_NAMES` 中，是则动态注册并路由到 `project_<id>` 连接
3. 业务代码中 `QorRecord.objects.all()` 无需感知分库

**跨项目查询**（Dashboard 场景）：

```python
# django_app/core/db_routing.py
def query_records_by_projects(proj_id_list=None, ...):
    """按项目迭代查询 QorRecord, 跨库安全。module_id 过滤时先按项目解析模块归属,
    避免不同项目库中相同 module ID 误匹配。"""
    project_module_map = _map_module_ids_to_projects(mod_id_filter, proj_id_list)
    ...
    for pid in query_proj_list:
        alias = _get_project_db_alias(pid)
        qs = QorRecord.objects.using(alias).select_related('module').all()
        ...
    all_records.sort(key=lambda r: r.released_at or r.recorded_at, reverse=order_desc)
    return all_records[:limit]
```

**关键决策**：

- 跨库 JOIN 不可用（无 FK 约束）→ 用「按项目迭代 + 内存合并」替代
- 项目库表结构由 `create_project_db()` 通过 `migrate --run-syncdb` 或 schema_editor 创建，无独立迁移版本爆炸
- 主库 schema 由 Django migrations 管理（`python manage.py migrate`）
- 项目库文件名：优先 `<项目名>_syn_qor.db`（`_syn_` 标识 sync 分库），兼容历史 `qor_p_<id>.db`

### 3.5 多数据库后端切换（DB_TYPE + PERSISTENCE_MODE）

| DB_TYPE | 含义 | 必填额外配置 | PERSISTENCE_MODE |
|---|---|---|---|
| `sqlite` | SQLite（默认） | 无 | `orm`（默认） |
| `sql` | MySQL/PostgreSQL | `DATABASE_URL` | `orm` |
| `mongodb` | MongoDB | `MONGODB_URI` | `hybrid`（默认）/ `mongo` |

```bash
# SQLite + ORM (默认)
DB_TYPE=sqlite PERSISTENCE_MODE=orm python manage.py runserver

# MySQL / PostgreSQL
DB_TYPE=sql DATABASE_URL='mysql+pymysql://root:pwd@localhost:3306/qor_recorder' \
  python manage.py migrate

# MongoDB (heavy-data repository + relational metadata)
PERSISTENCE_MODE=hybrid MONGODB_URI=mongodb://localhost:27017 \
  python manage.py runserver
```

**MongoDB 模式特殊性**：

- 主库仍走 SQLite（只读回退），Mongo 主要承担业务数据
- 通过 `repositories.py` 抽象层实现 dual-write（同时写 Mongo + SQLite）
- 读优先 Mongo，SQLite 兜底
- 迁移脚本 `manage.py migrate_sqlite_to_mongo` 支持历史数据从 SQLite 迁到 Mongo

### 3.6 前端架构（Vue 3 SPA）

- **路由**（[router/index.js](file:///d:/trae/trace_clock/qor_recorder_django/frontend-vue/src/router/index.js)）：`/login`、`/dashboard`、`/admin`（admin+owner）、`/review/group`、`/review/project`（admin+owner）、`/record/:id`、404
- **路由守卫**：`requiresAuth` 校验登录态，`roles` 校验角色，未登录跳 `/login?redirect=...`
- **状态管理**（Pinia）：`auth`（持久化到 localStorage，key `qor-auth`）、`dashboard`、`filters` 等
- **认证**：登录后保存 `api_key`，请求带 `X-API-Key` 头；同时走 Django Session cookie
- **主题**：`useTheme` composable + CSS 变量，`/api/user/theme` 读写
- **CSRF**：`utils/csrf.js` 读取 `csrftoken` cookie，写请求带 `X-CSRFToken` 头
- **图表**：ECharts（SVG renderer），`useCharts` / `useTimingAnalysis` composable 统一管理实例与销毁
- **约定**：所有动态数据在 `DOMContentLoaded` 后通过原生 Fetch 加载；请求使用 `AbortController` 与请求序号避免竞态

## 4. 数据模型设计

### 4.1 数据库分布

**主库（default）**：

```
User ──< ProjectMember ──> Project
User ──< ApiKey
User ──< UserDashboard
User ──< BackupRecord
Project ──< ProjectModule (many-to-many GlobalModule, owner_id + collaborators)
Project ──< ReviewGroup ──< ReviewGroupModule
Project ──< WeeklyRunSelection (record_id 逻辑外键, 无跨库 FK)
GlobalModule / LegacyModuleMapping / DataLock / ReviewHierarchySyncState
```

**项目库（project_<id>）**：

```
Module ──< QorRecord ──< ViolationPath
                    └─< RunNote
                    └─< RecordAnnotation ──< RecordAnnotationImage
DashboardGroup / AlertRule ──< AlertEvent / DataSnapshot
TileReview / GroupReview / SubsystemReview (snapshot_id + snapshot_data 冻结快照)
ReviewSnapshot ──< ReviewFile (不可变)
```

### 4.2 主库表要点

- **User**（v5.0 三级角色）：`role` ∈ admin / owner / viewer；`must_change_password`、`password_changed_at`、`theme`（JSON 字符串）
- **Project**：`status`（active/locked/archived/hidden）、`db_path`、`hidden_at/hidden_by`（软删除）
- **GlobalModule**：全局规范模块元数据，`normalized_name` 唯一；旧项目库 `Module` 保留直至外键迁移完成
- **ProjectModule**：项目×全局模块关联，`owner_id` + `collaborators`（JSON 数组）支撑 owner 协作
- **WeeklyRunSelection**：项目级官方周 run 的唯一身份记录（主库，仅存 `record_id`，无跨库 FK）
- **ApiKey**：`qor_` 前缀 + SHA-256 哈希存储，`scopes`（read/write）

### 4.3 项目库表要点

- **QorRecord**：核心业务表，`(module_id, version)` 业务唯一键（上传 upsert）
  - 固定列覆盖面积 / 时序 / 功耗 / 单元统计 / 频率 / 物理实现 6 大类 30+ 指标
  - `full_dir`（独立列）+ `extra_fields`（JSON）混合存储；`raw_dc_report` 存原始 DC 报告
  - Release 相关：`is_released`、`released_at/by`、`release_dir`、`version_description`
  - `_compute_tag()`：优先 `extra_fields.tag`，其次 `full_dir` 末段，最后 `version`
- **ViolationPath / RunNote**：违例路径与 Run 备注
- **RecordAnnotation / RecordAnnotationImage**：每条 QoR 记录一份评审批注 + 校验图片（存项目库）
- **Review 模型**：TileReview（单模块）→ GroupReview（模块组）→ SubsystemReview（子系统/项目级）
  - 状态流转：`draft → submitted → approved`，`rejected` 后可修订再提交
  - Group/Subsystem 绑定 `ReviewSnapshot`（`snapshot_id` + `snapshot_data` 校验和），评审只读冻结快照
  - `ReviewSnapshot` 不可变（save 时校验不可变字段）

### 4.4 设计权衡

**为什么固定列 + JSON？**
早期方案曾考虑把所有指标都存 JSON，但这样无法用 SQL 高效过滤/排序。最终采用**混合方案**：高频查询字段（area_total、wns_setup 等）建为固定列，可索引；低频/可变字段（各 clock 细节、comment）存入 `extra_fields` JSON。

**为什么按项目分库？**
1. 累计数据性能问题：单 SQLite 文件在 10w+ 记录后查询明显变慢；分库后每项目独立 IO
2. 数据隔离：项目数据生命周期独立，删除/归档不影响其他项目
3. 物理级保护：锁定项目直接改文件只读权限，无法绕过应用层误写
4. 备份灵活：可单独备份重要项目

**为什么不用一个 MongoDB collection？**
- SQLite 单文件仍是最简单的运维/备份模式
- MongoDB 是可选升级路径（团队规模扩张后）
- 双后端兼容保证老数据可平滑迁移

## 5. 核心模块设计

### 5.1 CSV / DC JSON 解析（services/qor_import.py, services/json_upload.py）

**设计挑战**
DC 导出的数据格式不统一：
- 列名变体多：`area_total` / `total_area` / `Area` / `TOTAL_CELL_AREA`
- 编码不一：UTF-8 BOM / GBK / Latin-1
- 数据脏：空值表示有 `-`、`N/A`、`NULL`、空字符串等多种
- 数值格式杂：科学计数法、千分位逗号、带单位后缀

**解决方案**
1. **列名模糊匹配**：定义 `FIELD_ALIASES` 映射表，标准化时统一转小写、去空格/下划线/连字符
2. **编码自动探测**：按 `utf-8-sig → utf-8 → gbk → latin-1` 顺序尝试解码
3. **安全数值解析**：`_safe_float()` 处理千分位、单位后缀、百分比、空值标记
4. **位置兜底**：若表头完全无法识别，按标准列顺序位置映射
5. **统计返回**：返回 `{records, stats, timing_group}`，便于前端展示解析质量

**违例路径解析的特殊处理**
- `timing_group` 从文件名提取（如 `SRAMCLK_violations.csv` → `SRAMCLK`）
- 处理 `11=-212835712990` 这种异常格式（取 `=` 前的数值）
- 列名别名独立于 QoR 解析器，避免污染

### 5.2 DB 路由层（core/db_routing.py）

让业务代码**不感知分库**：

```python
# 业务代码
def api_get_qor_data(request):
    records = QorRecord.objects.all()  # 自动路由到当前项目库
```

**实现方式**（Django Database Router）：

```python
# settings.py
DATABASE_ROUTERS = ['django_app.core.db_routing.ProjectRouter']

# db_routing.py
class ProjectDBRouter:
    def db_for_read(self, model, **hints):
        if model.__name__ not in PROJECT_MODEL_NAMES:
            return None
        project_id = hints.get('project_id') or get_current_project_id()
        if project_id is None:
            return None
        return _get_project_db_alias(project_id)   # 'project_<id>'
```

`ProjectContextMiddleware` 从请求提取 `project_id`（URL 模式 / query 参数 / JSON body），存入线程局部变量。

### 5.3 项目库生命周期（db_routing.py）

```python
def project_db_path(project_id):
    # 优先 <项目名>_syn_qor.db, 兼容历史 qor_p_<id>.db
    ...

def create_project_db(project_id):
    # 1. 创建空 SQLite 文件 + 启用 WAL / busy_timeout / foreign_keys
    # 2. 动态注册到 Django connections (CONN_HEALTH_CHECKS: False)
    # 3. migrate --run-syncdb 或 schema_editor 创建项目模型表
    ...
```

锁定/解锁/删除通过管理页面或 `admin_lock_project` 等 API 完成。

### 5.4 数据上传与清洗

**四种数据类型**（上传时通过 `data_type` 区分）：
1. **`qor`**：新建 QorRecord（`(module_id, version)` 已存在则更新）
2. **`power`**：按 模块+版本 匹配已有记录，仅更新 `power_*` 字段
3. **`violation`**：关联到已有 QorRecord（违例路径必须先有 QoR 记录），`timing_group` 从文件名提取
4. **`notes`**：按 `(qor_record_id, full_dir)` 删除并重建 RunNote；full_dir 缺失则关联到该 `(module, version)` 第一条记录

**清洗策略**
- **数值范围校验**：超出合理范围的值置为 None（视为脏数据）
- **NaN/Infinity 过滤**
- **字符串截断**：超长字符串截断，防止破坏 DB
- **Upsert**：`(module_id, version)` 已存在则更新，避免重复记录

**API 端点**
- `POST /api/v1/upload`（multipart/form-data，DC 脚本使用）
- `POST /api/v1/qor/upload`（JSON 格式，程序化提交）
- 配套脚本：`scripts/upload_qor.sh`、`scripts/Makefile.example`

### 5.5 违例路径分析

**Bus 合并算法**
一个 64-bit bus 的 64 条违例路径本质上是一个问题，逐条展示噪音太大。

```python
# 正则提取 bus 前缀和后缀
m = re.match(r'^(.+?)(?:_)(\d+)(?=[/_]|$)(.*)$', endpoint)
# data_bus_7_/D → prefix="data_bus", suffix="_/D"
```
- 同一 bus_key 的多条记录合并为一条，`vio_number` 统计合并数量
- 保留 slack 最差的那一条
- **取数优化**：bus 合并时先取 `limit×20` 条再分组，避免分组后条数不足

**跨版本 Diff 算法**
1. 按 `(startpoint, endpoint)` 作为路径唯一键
2. 在两版本中分别建立字典
3. 计算每条路径状态：`both`（算 delta）/ `new`（新增）/ `removed`（已修复）
4. 按 delta 升序排序（恶化最多的在前）
5. 汇总统计：改善数、恶化数、新增数、修复数

### 5.6 Dashboard 可视化

| 图表 | 类型 | 用途 |
|---|---|---|
| 面积趋势 | 柱状图 | 多模块多版本面积对比 |
| 时序趋势 | 折线图 | WNS/TNS 随版本变化 |
| 功耗趋势 | 柱状图 | 功耗分解对比 |
| 单元统计 | 堆叠柱状图 | 组合/时序单元占比 |
| 面积构成 | 饼图 | 多选模块的面积占比 |

**多 clock 时序/违例分析（v5.0）**：开启「按指标聚合」后，每个 clock 渲染一张独立 ECharts 子图（flex 排版），QoR CSV 中 `<CLOCK>_period/_wns/_tns/_path` 列自动识别存入 `extra_fields`。

**前端交互**：Vue 组件通过 `useCharts` / `useTimingAnalysis` composable 管理 ECharts（SVG renderer，先 dispose 再初始化）；数据请求用 `AbortController` + 请求序号避免竞态。

### 5.7 周评审 / 风险评级 / 快照

- **层级配置**：`config/review_hierarchy.yaml` → `manage.py sync_review_hierarchy --check/--apply`，写 `ReviewGroup / ReviewGroupModule / ReviewHierarchySyncState`
- **周域**：Asia/Shanghai 周一开始；`WeeklyRunSelection` 记录官方 run（显式/隐式星标）
- **风险评级**：`services/risk_rating.py` 依据 YAML 阈值，对比上周 star 评级，不会伪造低风险
- **评审读取**：Group/Project Review 只读冻结的 `ReviewSnapshot`（含校验和），保证评审输入可追溯
- **前端**：`/review/group`、`/review/project` 路由；对话框用 `useDialogFocus`（Tab 陷阱 / Escape / 焦点恢复）

### 5.8 备份与恢复

- `backup_service.perform_backup` 写入 `manifest.json`（校验和 + Django 迁移元数据）
- 恢复：`python manage.py restore_backup <path> --dry-run|--verify|--apply`，带维护锁，支持 `*_syn_qor.db`
- Web 请求只做备份创建/校验，真正的恢复必须在维护窗口命令行执行

## 6. 开发流程

### 6.1 环境搭建
```bash
# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 迁移并检查 Django
python manage.py migrate
python manage.py check

# 4. 启动 API（开发）
python manage.py runserver 127.0.0.1:8000

# 5. 另一终端启动 Vue 前端
cd ../frontend-vue
npm ci
npm run dev
# 访问 http://localhost:5173 (Vite dev server)
```

> 生产/单服务模式：`FRONTEND_MODE=vue` 时 Django 直接托管 `frontend-vue/dist` 构建产物，只需 `npm run build` + Django。

### 6.2 数据库后端切换
```bash
# SQLite + ORM (默认)
DB_TYPE=sqlite PERSISTENCE_MODE=orm python manage.py runserver

# SQL 全局库
DB_TYPE=sql DATABASE_URL='mysql+pymysql://root:pwd@localhost:3306/qor_recorder' \
  python manage.py migrate

# Mongo heavy-data repository + relational metadata
PERSISTENCE_MODE=hybrid MONGODB_URI=mongodb://localhost:27017 \
  python manage.py runserver
```

### 6.3 开发迭代节奏
项目采用「需求驱动、小步快跑」的迭代方式：

1. **需求确认**：与用户确认数据格式、查询场景、展示诉求
2. **模型先行**：先在 `django_app/core/models.py` 定义/修改表结构
   - 生成迁移：`python manage.py makemigrations`
   - 应用迁移：`python manage.py migrate`
3. **解析器开发**：在 `services/qor_import.py` 实现新格式解析，用真实 CSV 验证
4. **API 开发**：在 `django_app/api/views.py` / `api_v2.py` 实现路由，补充 pytest
5. **前端开发**：只修改仓库根 `frontend-vue/`
6. **数据验证**：用 demo 数据或真实数据端到端验证

### 6.4 数据库迁移策略

**关系数据库**：
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
```

**跨后端迁移**（SQLite → MongoDB）：
```bash
python manage.py migrate_global_modules --execute
python manage.py migrate_sqlite_to_mongo --execute
```

### 6.5 测试方式

- Django 后端测试：`pytest`（在 `QoR_Recorder/` 下，见 `pytest.ini`）
- Django 配置检查：`python manage.py check`
- Vue 单元测试：在 `frontend-vue/` 运行 `npm run test:unit`（Vitest）
- Vue e2e：在 `frontend-vue/` 运行 Playwright（`npx playwright test`）
- Vue 生产构建：在 `frontend-vue/` 运行 `npm run build`

### 6.6 代码规范
- 中文注释（与用户语言一致）
- 函数文档字符串说明参数、返回值、行为
- 业务辅助函数以 `_` 前缀（如 `_save_records_to_db`）
- 视图函数以 `api_` / `admin_` 前缀区分 API 与管理员路由
- 前端新模块使用 IIFE 模式挂载到 `window.QoRApp`（legacy），Vue 组件遵循现有 composable 模式

### 6.7 前端开发约定（重要）
- 所有动态数据通过 REST API 在 `DOMContentLoaded` 后加载，使用原生 Fetch
- ECharts 必须用 SVG renderer，且重初始化前先 `dispose` 旧实例
- Dashboard 数据请求使用 `AbortController` 和请求序号，防止竞态
- 全局 UI 工具统一暴露到 `window.AppUI`，方法名标准化
- CSS 使用变量（`styles/variables.css`）支持主题自定义，并带 fallback 值
- 输入框（用户名/密码）必须设置 `autocomplete`：username=`off`，password=`new-password`

## 7. 安全设计

### 7.1 认证与授权
- 密码使用 Django 默认 hasher（PBKDF2）存储；`User.check_password` 兼容 Flask scrypt 旧格式（`flask_scrypt$...`）
- 浏览器登录走 Django Session cookie；`login_view` 与 `user_change_own_password` 使用 `@csrf_exempt`
- `CsrfViewMiddleware` 必须在 `MIDDLEWARE` 中保留（移除会与 `{% csrf_token %}` 冲突）
- 角色权限：admin（全部）/ owner（自己 + 协作模块 CRUD + 任何已发布数据）/ viewer（只读已发布）
- API Key 认证：`qor_` 前缀 + SHA-256 哈希，DC 流程自动化使用

### 7.2 CSRF
- Django AJAX 契约：读取 `csrftoken` cookie，写请求带 `X-CSRFToken` 头
- `CSRF_TRUSTED_ORIGINS` 必须包含 Vite 开发源：`http://localhost:5173, http://127.0.0.1:5173`
- 自定义 `SecurityMiddleware` 补充强制改密拦截（非改密/登出端点）

### 7.3 安全增强（已实现）
- `SECRET_KEY` 生产环境（`DEBUG=0`）强制设置，否则启动被拒绝（`ENFORCE_SECRET_KEY=1`）
- SQLite 采用 WAL 模式 + busy_timeout（30s）+ 超时重试缓解写并发
- 登录限流：每 IP 每分钟最多 5 次登录请求（`RateLimitMiddleware`）
- Session Cookie：`HttpOnly=True`、`SameSite=Lax`、`Secure`（HTTPS 时）、12 小时有效期
- 密码强度校验：`>= 8 位 + 字母 + 数字 + 非弱口令黑名单`，改密/重置统一调用
- 项目库物理锁定：`status=locked` 时 DB 文件只读，防止绕过应用层写入

### 7.4 强制改密流程（must_change_password）

**触发场景**：

| 场景 | 设置 `must_change_password=True` 的位置 |
|---|---|
| 系统初始化默认账号 | `init_default_data` 创建 admin / user / release / viewer 时 |
| 管理员重置密码 | `admin_reset_user_password`（未填自定义密码时默认 `Reset@123`） |
| 兜底检查 | `init_default_data` 检测到账号仍用出厂默认密码时 |

**清零场景**：改密成功后更新 `password_changed_at = utcnow()`

**拦截实现**（[core/middleware.py](file:///d:/trae/trace_clock/qor_recorder_django/QoR_Recorder/django_app/core/middleware.py) + `security.py`）：
- 写操作（POST/PUT/DELETE/PATCH）返回 403
- GET 受保护页面重定向到改密页

**前端改密**：`ChangePasswordModal.vue`（Vue）/ `change_password.html`（legacy），实时显示密码强度，必须填旧密码 + 新密码 + 确认，提交带 `X-CSRFToken`。

## 8. 性能考量

### 8.1 查询优化
- 关键字段建索引：`module_id`、`version`、`timing_group`、`qor_record_id`、`full_dir`、`is_released`
- 列表查询限制 5000 条，防止全表扫描；违例查询限制最大 2000 条
- 跨项目查询：按项目迭代 + 内存合并（替代跨库 JOIN）
- module_id 过滤时先按项目解析模块归属，避免不同项目库相同 ID 误匹配

### 8.2 前端优化
- ECharts 本地打包，减少网络依赖
- 大表用 `max-height + overflow:auto` 滚动
- 端点字段超长时 `text-overflow:ellipsis`，hover 显示完整值；表格宽度内容自适应，数值居中
- 项目库文件 `_syn_qor.db` 采用 WAL 模式，读性能与并发优于单文件

### 8.3 Bus 合并的取数策略
```python
# Bus 合并时先取更多数据再分组，避免分组后条数不足
if bus_grouping:
    fetch_limit = min(total, max(limit * 20, 2000))
```

### 8.4 按项目分库的性能优势
- 10w 记录级单项目：单库下查询 > 1s，分库后 < 100ms
- 多项目并发查询：分库后各项目 IO 不互斥
- 大项目归档：直接迁移/备份/锁定单文件，不影响其他项目

## 9. 扩展性与未来方向

### 9.1 当前架构的扩展点
- **数据库后端**：`DB_TYPE` + `PERSISTENCE_MODE` 切换，无需改代码
- **按项目分库**：`ProjectDBRouter` 模式可扩展到任意粒度（如按 tenant 分）
- **解析器**：`FIELD_ALIASES` 可继续扩展，支持更多 DC 版本的列名变体
- **图表**：ECharts 配置化，新增图表只需新增一个 Vue 图表组件

### 9.2 已实现的扩展
- ✅ 项目软删除（`status=hidden`）与两级删除
- ✅ 项目锁定（物理只读 + 状态校验）
- ✅ MongoDB dual-write 抽象层（`repositories.py`）
- ✅ API Key 认证（DC 流程自动化）
- ✅ 主题自定义（CSS 变量 + 服务端注入）
- ✅ 三级 Review 工作流 + 冻结快照 + 风险评级
- ✅ 目录聚合 API（`group_by=run|base_dir|module`）
- ✅ 记录批注（文字 + 校验图片）
- ✅ DC JSON 报告上传（`services/json_upload.py`）
- ✅ gvim 源文件协议打开（`useGvim` / `SourceFileLink`，绝不由服务器拉起 gvim）

### 9.3 潜在改进方向
1. **项目级权限**：基于 ProjectMember 的细粒度权限
2. **跨项目数据汇总**：内置跨项目合并报表
3. **趋势预警**：WNS 突然恶化时自动告警
4. **MongoDB 写入优化**：批量写 + 异步队列

## 10. 经验总结

### 10.1 做对的事
- **SQLite 优先 + 分库扩展**：单文件简单运维起步，按项目分库解决性能瓶颈
- **多后端抽象**：`DB_TYPE` / `PERSISTENCE_MODE` 一键切换，避免团队规模变化时的硬迁移
- **混合存储**：固定列 + JSON 的组合，兼顾性能与灵活性
- **解析器独立**：CSV 解析与业务逻辑解耦，便于单独测试和复用
- **Bus 合并**：这个特性极大提升了违例分析的效率，是核心价值点
- **软删除 + 物理锁定**：既防误操作，又保留恢复可能
- **Vue SPA + Django API**：前后端分离后 UI 迭代效率大幅提升

### 10.2 教训
- **Django 5.2 数据库配置**：动态注册的项目库连接必须包含 `CONN_HEALTH_CHECKS: False`，否则模型查询报 KeyError
- **CsrfViewMiddleware 不可移除**：移除会与 `{% csrf_token %}` 模板标签冲突；不要自定义 CSRF 中间件替换内置
- **module_id 跨项目冲突**：各项目库 ID 独立自增，直接用 `module_id__in` 会误匹配；必须先用 `_map_module_ids_to_projects` 解析
- **跨库 JOIN 不可用**：跨库无 FK 关系，需用 `query_records_by_projects` 显式迭代
- **孤立记录**：访问 `QorRecord.module` 时用 try/except 处理模块已删除的孤立记录（DoesNotExist）
- **Python 3.10 + PyYAML**：`review_hierarchy.py` 依赖 PyYAML，需加入 requirements.txt
- **浏览器自动填充**：密码输入框被浏览器/密码管理器干扰会导致实际设置值与记忆不符，输入框必须配置 `autocomplete`
- **前端线程局部路由**：跨项目循环查询后要保留记录来源项目（`row._qor_project_id`），避免线程局部被后续项目覆盖

### 10.3 关键决策记录

| 决策 | 原因 |
|---|---|
| 主库 + 项目库分库 | 单项目大数据量性能下降；需物理级保护（锁定/删除） |
| `ProjectDBRouter` 动态路由 | 业务代码不感知分库；最小侵入式改造 |
| 项目库 `<name>_syn_qor.db` | 兼容历史 `qor_p_<id>.db`，支持平滑迁移 |
| 跨库无 FK | Django 跨库查询不会自动加 FK 约束；用逻辑外键 + 迭代合并 |
| 项目库 schema_editor 建表 | 项目库表结构简单，无需迁移版本爆炸；主库仍走 Django migrations |
| 跨项目查询用迭代合并 | 跨库 JOIN 不可用；按项目迭代 + 内存排序是当前最简单可靠方案 |
| MongoDB dual-write | 兼容旧代码 + 平滑迁移；SQLite 作为兜底保证系统不会因为 Mongo 故障停机 |
| Vue 3 SPA 重构 | 大 HTML（6000+ 行内联 JS）难以维护且无法浏览器缓存；组件化提升可维护性 |

## 11. 周评审、YAML 层级、gvim、备份恢复（2026 overhaul）

Canonical operational detail lives in [`WEEKLY_REVIEW_AND_RECOVERY.md`](WEEKLY_REVIEW_AND_RECOVERY.md).
Developer checklist:

1. **Hierarchy**: edit `config/review_hierarchy.yaml`, then
   `python manage.py sync_review_hierarchy --check` / `--apply`.
2. **Weekly domain**: Asia/Shanghai Monday windows; star selection via
   `WeeklyRunSelection`; risk ratings from YAML thresholds; Group/Project Review
   reads frozen `ReviewSnapshot` only.
3. **Frontend**: Vue routes `/review/group` and `/review/project`; dialogs use
   `useDialogFocus` (Tab trap, Escape, restore). Source paths use
   `SourceFileLink` / `useGvim` (`gvim://`), never server-launched gvim.
4. **Backup**: `backup_service.perform_backup` writes `manifest.json` with
   checksums + Django migration metadata; restore via
   `python manage.py restore_backup … --dry-run|--verify|--apply` with
   maintenance lock and `*_syn_qor.db` support.

## 12. 参考文档

- 用户指南：[`user_guide.md`](user_guide.md)
- 数据格式与 API：[`DATA_FORMAT.md`](DATA_FORMAT.md)
- 周评审与恢复：[`WEEKLY_REVIEW_AND_RECOVERY.md`](WEEKLY_REVIEW_AND_RECOVERY.md)
- 部署：[`deploy/README.md`](../deploy/README.md)
- 迁移运行手册：[`FINAL_MIGRATION_RUNBOOK.md`](FINAL_MIGRATION_RUNBOOK.md)
- 验证报告：[`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md)

---

*文档版本：6.0 | 最后更新：2026-08-17（对齐 Django + Vue 架构）*
