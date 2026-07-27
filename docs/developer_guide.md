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

### 1.3 非目标
- 不替代综合工具，只做数据消费与分析
- 不做大规模数据流处理，定位为团队级（万条记录量级）工具
- 不做权限细粒度管理（仅区分 admin / user 两类角色）

## 2. 技术选型

| 层 | 选型 | 选型理由 |
|---|---|---|
| Web 框架 | Flask 3.1 | 轻量、灵活，适合中小型内部工具；生态成熟 |
| ORM | Flask-SQLAlchemy | 与 Flask 无缝集成；支持多数据库后端 |
| 数据库 | SQLite | 零部署成本，单文件便于备份迁移；万条记录量级性能足够 |
| 数据处理 | pandas + openpyxl | CSV 解析与 Excel 导出的工业标准 |
| 前端图表 | ECharts (CDN) | 功能强大、交互丰富；通过 CDN 引入无需构建 |
| 认证 | Flask-Login + Werkzeug | 会话管理 + 密码哈希，够用且不臃肿 |
| 模板 | Jinja2 (Flask 内置) | 服务端渲染，无前端构建依赖 |

**选型原则**：内部工具优先「单进程可跑、零外部依赖、易备份」。SQLite + Flask 单进程即可服务一个 10-20 人团队。

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
│  │ Flask-   │  │ 页面路由  │  │  - 数据查询/过滤      │  │
│  │ Login    │  │ API 路由  │  │  - 对比聚合           │  │
│  │          │  │ 导出路由  │  │  - Bus 合并算法       │  │
│  └──────────┘  └──────────┘  │  - Diff 计算          │  │
│                              └──────────┬───────────┘  │
└─────────────────────────────────────────┼──────────────┘
                                          │
┌─────────────────────────────────────────▼──────────────┐
│              数据访问层 (SQLAlchemy ORM)                 │
│   models.py: User / Project / Module / QorRecord /      │
│              ViolationPath / UserDashboard              │
└─────────────────────────────────────────┬──────────────┘
                                          │
┌─────────────────────────────────────────▼──────────────┐
│                  SQLite (qor_recorder.db)               │
│              每次启动自动备份至 backups/                  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
QoR_Recorder/
├── app.py              # 主应用：所有路由与业务逻辑
├── models.py           # 数据模型（6 张表）
├── qor_parser.py       # CSV 解析器（QoR + 违例路径）
├── init_db.py          # 数据库初始化与 demo 数据生成
├── config.py           # 配置（DB URI、密钥、上传限制）
├── requirements.txt    # 依赖清单
├── qor_recorder.db     # SQLite 数据库文件
├── backups/            # 启动时自动备份的 DB 历史版本
├── uploads/            # 上传的 CSV 文件暂存
└── templates/          # Jinja2 模板
    ├── base.html       # 布局骨架（导航栏、CSS 引入）
    ├── login.html      # 登录页
    ├── dashboard.html  # 主 Dashboard（图表 + 违例面板）
    ├── compare.html    # 对比页
    ├── admin.html      # 管理页（数据上传、项目管理）
    └── error.html      # 错误页
```

### 3.3 分层职责
严格遵循「路由薄、业务厚、模型纯」的原则：

- **路由层**：只做参数提取、调用业务函数、返回 JSON/模板
- **业务层**：查询构建、数据清洗、聚合计算、Bus 合并、Diff 算法
- **模型层**：只定义字段与 `to_dict()`，不含业务逻辑
- **解析层**：`qor_parser.py` 独立负责 CSV → dict 的转换，与数据库解耦

## 4. 数据模型设计

### 4.1 ER 关系

```
User ──< UserDashboard
Project ──< Module ──< QorRecord ──< ViolationPath
```

### 4.2 表设计要点

#### Project / Module
- `Module` 有 `(project_id, name)` 唯一约束，防止同名模块
- 级联删除：删 Project 自动删其下 Module 与 Record

#### QorRecord
- 核心表，存储一次综合运行的全部 QoR 指标
- **固定列**：覆盖面积、时序、功耗、单元统计、频率 5 大类共 20+ 指标
- **extra_fields (JSON)**：存储未映射到固定列的字段（如 `comment`、`full_dir`、各 clock 的 period/wns/tns/path）。这样既保证核心字段可索引查询，又能保留原始 CSV 的完整信息
- `(module_id, version)` 作为业务唯一键，上传时做 upsert（已存在则更新）

#### ViolationPath
- 多对一关联 QorRecord（一条 QorRecord 可有 0~多条违例路径）
- 按 `timing_group` 分类（如 SRAMCLK、CLK_CPU）
- `source_file` 保留来源 CSV 文件名，便于回溯

#### UserDashboard
- 每用户可保存多份 Dashboard 配置（JSON），支持 `is_default`
- 配置内容包括选中的项目、模块、图表类型、指标等

#### User.theme (JSON)
- 每用户独立的界面主题，存储为 JSON 字符串于 `users.theme` 字段
- 字段包括 `primary / primary_gradient_end / background / surface / surface_hover / text / text_secondary / border / navbar_text / navbar_text_active`
- `get_theme()` 自动与 `DEFAULT_THEME` 合并，保证字段完整性，兼容历史数据
- 通过 `THEME_PRESETS` 提供 classic / dark / green / purple / orange 5 套预设
- 颜色值在后端用正则校验（`#hex` / `rgb()` / `rgba()` / `hsl()` / `hsla()`），写入前经 `_validate_theme` 清洗

### 4.3 设计权衡：固定列 vs JSON
早期方案曾考虑把所有指标都存 JSON，但这样无法用 SQL 高效过滤/排序。最终采用**混合方案**：
- 高频查询字段（area_total、wns_setup 等）建为固定列，可索引
- 低频/可变字段（各 clock 的细节、comment）存入 `extra_fields` JSON

这保证了 95% 的查询走固定列，性能与灵活性兼顾。

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

### 5.2 数据上传与清洗 (app.py `_save_records_to_db`)

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
- **Upsert**：`(module_id, version)` 已存在则更新，避免重复记录

#### 三种数据类型
上传时通过 `data_type` 参数区分：
1. `qor`：新建 QorRecord（若已存在则更新）
2. `power`：合并到已有 QorRecord（按 模块+版本 匹配）
3. `violation`：关联到已有 QorRecord（违例路径必须先有 QoR 记录）

### 5.3 违例路径分析

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

### 5.4 Dashboard 可视化

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

# 3. 初始化数据库（含 demo 数据）
python init_db.py --demo

# 4. 启动
python app.py
# 访问 http://localhost:5000，admin/admin@2026
```

### 6.2 开发迭代节奏
项目采用「需求驱动、小步快跑」的迭代方式：

1. **需求确认**：与用户确认数据格式、查询场景、展示诉求
2. **模型先行**：先在 `models.py` 定义/修改表结构，`db.create_all()` 建表
3. **解析器开发**：在 `qor_parser.py` 实现新格式的解析，用真实 CSV 验证
4. **API 开发**：在 `app.py` 实现路由，用脚本或 Postman 测试
5. **前端开发**：在 `templates/` 实现页面，浏览器验证
6. **数据验证**：用 demo 数据或真实数据端到端验证

### 6.3 数据库迁移策略
- 开发期：直接 `db.create_all()`（SQLite 自动建新表，已有表不动）
- 字段变更：手动执行 ALTER 或重建数据库（数据量小，可接受）
- **自动备份**：每次启动 app 自动备份 DB 到 `backups/`，防止误操作丢数据

### 6.4 测试方式
由于是内部工具，未引入正式测试框架，采用脚本式验证：
- 编写临时 Python 脚本调用 API，断言返回字段
- 用 demo 数据（`init_db.py --demo`）覆盖各种边界场景
- 浏览器手动验证交互流程

### 6.5 代码规范
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

## 8. 性能考量

### 8.1 查询优化
- 关键字段建索引：`module_id`、`version`、`timing_group`、`qor_record_id`
- 列表查询限制 5000 条，防止全表扫描
- 违例查询限制最大 2000 条

### 8.2 前端优化
- ECharts 按 CDN 引入，减少服务器压力
- 大表用 `max-height + overflow:auto` 虚拟滚动
- 端点字段超长时 `text-overflow:ellipsis`，hover 显示完整值

### 8.3 Bus 合并的取数策略
```python
# Bus 合并时先取更多数据再分组，避免分组后条数不足
if bus_grouping:
    fetch_limit = min(total, max(limit * 20, 2000))
```
这是一个重要的设计决策：直接 `limit(N)` 再分组会导致分组后不足 N 条。改为先取 `limit×20` 再分组再截断，保证了用户体验。

## 9. 扩展性与未来方向

### 9.1 当前架构的扩展点
- **数据库**：切换 `SQLALCHEMY_DATABASE_URI` 即可迁移到 PostgreSQL/MySQL
- **解析器**：`FIELD_ALIASES` 可继续扩展，支持更多 DC 版本的列名变体
- **图表**：ECharts 配置化，新增图表只需加一个 `render*Chart()` 函数

### 9.2 潜在改进方向
1. **API 化**：将模板渲染改为纯 API，前端用 React/Vue 重构
2. **多用户协作**：支持项目级权限、数据锁定
3. **自动化集成**：提供 API Key，让 DC 流程自动上传数据
4. **趋势预警**：WNS 突然恶化时自动告警
5. **数据库迁移**：引入 Flask-Migrate 做 schema 版本管理

## 10. 经验总结

### 10.1 做对的事
- **SQLite 优先**：内部工具零运维，单文件备份比数据库集群省心
- **混合存储**：固定列 + JSON 的组合，兼顾性能与灵活性
- **解析器独立**：CSV 解析与业务逻辑解耦，便于单独测试和复用
- **Bus 合并**：这个特性极大提升了违例分析的效率，是核心价值点

### 10.2 教训
- **f-string 转义**：在 shell 中用 `python -c` 执行含双引号的 f-string 会出错，应改用脚本文件
- **Flask debug 模式**：修改文件会自动重载，但有时不生效，需手动重启
- **正则贪婪性**：bus 合并的正则用了 `(.+?)` 非贪婪匹配，避免误匹配

---

*文档版本：2.0 | 最后更新：2026-07-23*
