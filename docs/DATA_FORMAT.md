# QoR Recorder 数据提交规范 v5.0

> 本文档定义每次 "run"（综合运行）需要提交的数据格式、提交方式（脚本 / API / Makefile / Demo 脚本）以及覆盖与关联策略。
> 适用于：CSV 文件作者、Makefile 集成者、API 调用方、Demo 数据生成者、生产环境部署。

> **v5.0 更新（2026-07-30）**:
> - 角色模型升级为 `admin / owner / viewer` 三级（v4.x 的 `user / release` 自动迁移为 `owner`）
> - 默认 `viewer` 账户自动创建（`viewer / viewer@2026`），强制首登改密
> - 模块级协作（`Module.owner_id` + `Module.collaborators`）：支持 owner 间数据共享
> - Dashboard 违例分析页：时钟多选（每个 clock 并排渲染一张子图）
> - `release_dir` 字段作为独立列，与 `full_dir` 类似用于按目录发布管理
> - 字段兼容：`tag` 仍可作为 `version` 别名；`module_name` 也支持 `module` 别名

> **v4.0 更新（2026-07-28）**:
> - 引入**按项目分库**架构：每个项目独立 DB 文件 (`qor_p_<id>.db`)，主库只存系统级数据
> - 引入**多数据库后端**支持：通过 `DB_TYPE` 环境变量一键切换 sqlite / sql (MySQL/PostgreSQL) / mongodb
> - 引入**MongoDB dual-write** 抽象层：业务库走 Mongo，主库走 SQLite 兜底
> - 提供 `migrate_to_per_project_db.py` 历史数据迁移工具
> - 提供 `migrate_sqlite_to_mongo.py` SQLite → MongoDB 迁移工具
> - `db_init.py --check` 验证配置；`db_init.py --seed` 初始化+demo 数据
> - 项目软删除（`status=hidden`）+ 已隐藏项目恢复

> **v3.0 更新（2026-07-28）**:
> - 增补 `full_dir` 作为独立列（不只是 `extra_fields`），用于按目录聚合
> - 统一时序指标方向为"越小越好"（WNS/TNS/NVP 全部 `min`），与面积/功耗/拥塞一致
> - 新增 `seed_demo_data.py` 脚本用于生成多项目/多模块/多 base_dir 的演示数据
> - 新增 `qor_record_detail.html` 详情页与 `record_id` 跳转
> - 新增 Review 流程（TileReview / GroupReview / SubsystemReview）
> - 新增目录聚合 API（`/api/qor/aggregate?group_by=run|base_dir|module`）


---

## 0. 数据类型总览

系统支持 4 类 CSV 数据，按 `data_type` 区分：

| data_type    | 用途                       | 一行含义         | 主键 / 关联                              | 重复上传行为                       |
|--------------|----------------------------|------------------|------------------------------------------|------------------------------------|
| `qor`        | QoR 综合指标（面积/时序/功耗/单元等） | 一个 run         | `(module_name, version)`                 | **覆盖** 同 module+version 的记录  |
| `power`      | 功耗数据（可独立于 QoR 上传）     | 一个 run 的功耗 | `(module_name, version)`                 | **合并** 到已有 QorRecord，仅更新功耗字段 |
| `violation`  | 违例路径（每个 timing group 一个文件） | 一条违例路径     | `(module, version)` + 文件名中的 timing_group | **覆盖** 同 (record, timing_group) 的旧路径 |
| `notes`      | Run 备注 / 参数（item + description） | 一条备注项       | `(qor_record_id, full_dir)`              | **覆盖** 同 (record, full_dir) 的旧备注 |

---

## 0.5 角色与默认账户（v5.0）

实际部署后, 上传 / 查看 / 管理操作都受角色约束. 数据提交前请确认调用方角色.

### 0.5.1 角色模型

| 角色     | 能力                                                                 | 典型场景                          |
|----------|----------------------------------------------------------------------|-----------------------------------|
| `admin`  | 全部权限：项目管理、用户管理、所有数据 CRUD、发布/撤回、锁定/解锁     | 系统管理员                        |
| `owner`  | 上传/管理**自己创建**的模块数据 + 授权其他 owner 协管 + 发布/撤回      | 综合工程师 / 数据 owner           |
| `viewer` | 只读 + 仅能查看**已发布**数据（`is_released=True`），不能上传/管理     | 客户 / 跨团队 / 跨部门只读        |

> v4.x 的 `user` / `release` 角色已在启动时自动迁移为 `owner`. 历史 `release` 账户的可访问性不变（owner 默认可见所有数据）.

### 0.5.2 默认账户（生产环境**必须**修改默认密码）

| 用户名     | 默认密码       | 角色     | 用途                          |
|------------|----------------|----------|-------------------------------|
| `admin`    | `admin@2026`   | admin    | 全功能管理                    |
| `release`  | `release@2026` | owner    | 历史发布账户, 自动迁移为 owner |
| `viewer`   | `viewer@2026`  | viewer   | v5.0 新增, 只读               |

**强制改密机制**:

- admin / release / viewer 三个账户首次登录后, 系统会**强制跳转到 `/change_password`**
- 改密之前, 任何上传/管理操作都会被 403 拦截（即使 API Key 也无法绕过）
- 弱密码黑名单：`12345678` / `password` / `password1` / `admin123` / `qwerty123` / `11111111` / `00000000`

### 0.5.3 数据可见性矩阵

| 数据状态           | admin | owner | viewer |
|--------------------|-------|-------|--------|
| 自己 owner 的数据  | ✅    | ✅    | ❌     |
| 协作者 owner 的数据 | ✅    | ✅    | ❌     |
| 任何已发布数据     | ✅    | ✅    | ✅     |
| 未发布的他人数据   | ✅    | ❌    | ❌     |
| 软删除项目 (hidden) | ✅ (在已隐藏页可见) | ❌ | ❌ |

> Dashboard 的 "scope" 切换 (mine / all) 仅 owner 可见, 默认 `mine` 强制只显示自己 owner 的数据; admin 始终看全部, viewer 已被后端限制.

### 0.5.4 模块级协作（v5.0 新增）

Module 表新增 `owner_id` + `collaborators` 字段:

- `owner_id`: 模块创建者, **唯一**, 可管理模块和模块下所有数据
- `collaborators`: JSON 数组 `[user_id, ...]`, 被授权的同 `owner` 角色用户, 可管理该模块下数据
- **只能授权其他 `owner` 角色用户** (团队内部协作, viewer 不能成为协作者)
- 跨项目场景: Module 在项目 DB, URL 不携带 project_id, 后端用 `_resolve_module_across_projects()` 跨库查找

API:

```bash
# 列出模块协作者
GET /api/modules/<id>/collaborators

# 添加协作者
POST /api/modules/<id>/collaborators
Body: {"user_id": 7}

# 删除协作者
DELETE /api/modules/<id>/collaborators/<user_id>
```

---

## 1. 概念层级

```
Project（项目）
  └─ Module（模块, 例: cpu_top, sram_ctrl）
       └─ QorRecord（一次综合运行的结果, 即"一个 run"）
              ├─ ViolationPath[]（违例路径, 0..N 条, 按 timing_group 分组）
              └─ RunNote[]（备注/参数, 0..N 条, 按 full_dir 分组）
```

- 一个 **run** = 一条 `QorRecord` 记录
- 一个 run 关联到一个 module 和一个 version（版本/commit/日期标签）
- **full_dir**：run 的工作目录绝对路径，用于区分同一 module+version 下的不同子目录 run（多 corner / 多 sub-run）
- **release_dir**（v5.0 新增）：发布目录，对外公开数据时使用的相对路径；若为空则使用 `full_dir`
- 同一 module 可有多个 run（不同时期、不同版本），用于趋势对比

---

## 1.5 存储架构（v4.0+ 按项目分库）

实际部署中, 性能与隔离都和存储架构强相关. 提交数据前请理解:

### 1.5.1 主库 + 项目库

| 库              | 文件                          | 内容                                                                  |
|-----------------|-------------------------------|-----------------------------------------------------------------------|
| **主库**        | `qor_recorder.db` (或 MySQL/Mongo) | 用户、API Key、项目元数据、ProjectMember、DashboardGroup、ReviewSnapshot 等**系统级**数据 |
| **项目库**      | `qor_p_<id>.db`（每个项目一个） | 该项目的模块、QorRecord、ViolationPath、RunNote、Review 等**业务**数据 |

### 1.5.2 性能隔离

- 每个项目独立文件, 单项目大数据量不会拖慢其他项目
- 业务查询通过 `switch_to_project(pid)` 切换 bind, 主库不受影响
- 跨库查询（如 Dashboard 拉多项目）通过 `query_records_by_projects()` 迭代各项目库合并

### 1.5.3 备份与归档

```bash
# 单项目备份 (推荐, 项目结束后归档)
cp data/qor_p_3.db backups/qor_p_3_$(date +%Y%m%d).db

# 单项目迁移 (拷走即可, 含全部数据)
scp data/qor_p_3.db newserver:/opt/qor_recorder/data/

# 主库备份
python -c "
from app import app, db
from sqlalchemy import text
with app.app_context():
    with db.engine.connect() as conn:
        conn.execute(text('VACUUM INTO :path'), {'path': 'backups/main_$(date +%Y%m%d).db'})
"
```

### 1.5.4 多后端切换

通过 `DB_TYPE` 环境变量切换:

| DB_TYPE  | 含义           | 必填                | 适用规模          |
|----------|----------------|---------------------|-------------------|
| `sqlite` | SQLite (默认)  | 无                  | < 20 人, < 10 万记录 |
| `sql`    | MySQL/PostgreSQL | `DATABASE_URL`    | 20+ 人, 大数据量    |
| `mongodb`| MongoDB        | `MONGODB_URI`      | 已有 Mongo 基础设施  |

> SQLite 模式下, `data/` 下会同时存在主库 `qor_recorder.db` 和若干 `qor_p_<id>.db`.
> 切换到 `sql` / `mongodb` 后, 这些业务表合并到对应后端, `qor_p_<id>.db` 不再生成.

---

## 2. 提交方式

### 2.0 API Key 准备（必读, 实际部署第一步）

`upload_qor.sh` / curl / Makefile 都依赖 API Key 认证. 部署完成后:

1. 用 admin 登录 Web 界面
2. 进入「管理 → API Key 管理」或访问 `/admin#apikeys`
3. 点击「创建 API Key」, 输入名称 (如 `dc-bot`), 选择 scope:
   - `upload`: 可调用 `/api/v1/upload`, `/api/v1/qor/upload`
   - `read`: 只能查询, 不能上传
4. **保存生成的 key**（格式 `qor_xxxxxxxx`）, 仅显示一次
5. 写入 CI / Makefile 环境:

```bash
# 方式 A: 环境变量
export QOR_API_KEY=qor_xxxxxxxxxxxxxxxx

# 方式 B: 文件 (推荐, 避免泄漏到 shell history)
echo "qor_xxxxxxxxxxxxxxxx" > ~/.qor_api_key
chmod 600 ~/.qor_api_key
```

**API Key 与 CSRF**:

- 带 `X-API-Key` 的请求**跳过 CSRF 校验**, 适合 DC 流程后台调用
- 仅 session 认证 (浏览器) 的请求**仍需 CSRF token** (前端 `AppUI.api()` 自动注入)
- 若 `user.must_change_password=True`, 即使 API Key 也被 403 拒绝, 必须先改密

### 2.1 方式 A：脚本（推荐用于 Makefile / CI）

```bash
# 通用格式
./scripts/upload_qor.sh <project_id> <version> <csv_file> [data_type] [options]

# data_type: qor (默认) / power / violation / notes
# options:
#   --release          上传后立即标记为已发布（对 release 账号可见）
#   --full-dir <DIR>   Run 目录路径（用于 notes，区分多目录 run）
#   --module-id <ID>   模块 ID（覆盖 QOR_MODULE_ID 环境变量）
#   --server <URL>     服务器地址（覆盖 QOR_SERVER 环境变量）
```

环境变量：

| 变量            | 必填 | 默认值                  | 说明                                   |
|-----------------|------|-------------------------|----------------------------------------|
| `QOR_API_KEY`   | ✅   | -                       | API Key（格式 `qor_xxxxxxxx`）         |
| `QOR_SERVER`    | -    | `http://localhost:5000` | 服务器地址                             |
| `QOR_MODULE_ID` | -    | -                       | 模块 ID（不传则从 CSV 的 module_name 识别） |
| `QOR_RELEASE`   | -    | `0`                     | 设为 `1` 等同 `--release`              |
| `QOR_FULL_DIR`  | -    | -                       | 等同 `--full-dir`                      |

### 2.2 方式 B：Makefile 集成

将 `scripts/Makefile.example` 复制到 run 目录，按需修改变量后：

```bash
make upload           # 上传 QoR 数据
make upload-all       # 上传 QoR + 功耗 + 违例 + 备注
make release          # 上传并标记为已发布
make help             # 查看所有目标
```

### 2.3 方式 C：直接 curl（适合调试 / 非 Makefile 场景）

```bash
curl -X POST http://localhost:5000/api/v1/upload \
  -H "X-API-Key: qor_xxxxxxxx" \
  -F "project_id=1" \
  -F "module_id=5" \
  -F "version=v1.0" \
  -F "data_type=qor" \
  -F "files=@qor_report.csv" \
  -F "mark_released=0"          # 可选
  -F "full_dir=/scratch/runs/v1.0"  # 可选，仅 notes 类型有效
```

### 2.4 方式 D：管理员 Web 界面

登录管理员账号 → 管理页 → 上传数据区。可选数据类型与脚本一致，notes 类型额外提供 `full_dir` 输入框。

---

## 3. QoR 数据 CSV（data_type=qor）

宽表格式：一行 = 一个 run 的所有指标。

### 3.1 列定义

| 字段                      | 类型   | 单位  | 必填 | 说明                                            |
|---------------------------|--------|-------|------|-------------------------------------------------|
| **module_name**           | string | -     | ✅   | 模块名，必须在项目中已存在                       |
| **version**               | string | -     | ✅   | 版本标识，例 `v1` / `20260301_1430` / `a1b2c3` |
| **full_dir**              | string | -     | ⭕   | **v3.0 独立列**。Run 工作目录，格式 `<base_dir>/<sub_path>/<run_name>`，用于按目录聚合。详见 §15 |
| area_total                | float  | um²   | ⭕   | 总面积                                          |
| area_combinational        | float  | um²   | ⭕   | 组合逻辑面积                                    |
| area_sequential           | float  | um²   | ⭕   | 寄存器面积                                      |
| area_black_box            | float  | um²   | ⭕   | 黑盒面积                                        |
| area_macro                | float  | um²   | ⭕   | 宏单元面积                                      |
| wns_setup                 | float  | ns    | ⭕   | Setup WNS，**负值=违例**                         |
| tns_setup                 | float  | ns    | ⭕   | Setup TNS，**负值=违例**                         |
| nvp_setup                 | int    | 条    | ⭕   | Setup 违例路径数                                |
| wns_hold                  | float  | ns    | ⭕   | Hold WNS                                        |
| tns_hold                  | float  | ns    | ⭕   | Hold TNS                                        |
| nvp_hold                  | int    | 条    | ⭕   | Hold 违例路径数                                 |
| power_internal            | float  | mW    | ⭕   | 内部功耗                                        |
| power_switching           | float  | mW    | ⭕   | 翻转功耗                                        |
| power_leakage             | float  | mW    | ⭕   | 漏电功耗                                        |
| power_total               | float  | mW    | ⭕   | 总功耗 = internal + switching + leakage         |
| cell_count                | int    | -     | ⭕   | 标准单元数                                      |
| instance_count            | int    | -     | ⭕   | 实例数（含宏）                                  |
| net_count                 | int    | -     | ⭕   | 线网数                                          |
| sequential_cell_count     | int    | -     | ⭕   | 寄存器数量                                      |
| target_frequency          | float  | MHz   | ⭕   | 目标频率                                        |
| achieved_frequency        | float  | MHz   | ⭕   | 实际频率                                        |
| mbb_ratio                 | float  | 0-1   | ⭕   | MBFF 合并率，0.85 = 85%                         |
| clock_gating_ratio        | float  | 0-1   | ⭕   | 时钟门控覆盖率，0.92 = 92%                      |
| utilization               | float  | 0-1   | ⭕   | 布局利用率，0.75 = 75%                          |
| congestion_h              | float  | 0-1   | ⭕   | 水平拥塞指数                                    |
| congestion_v              | float  | 0-1   | ⭕   | 垂直拥塞指数                                    |
| congestion_b              | float  | 0-1   | ⭕   | 综合拥塞指数（通常 max(H,V)）                   |
| congestion                | float  | 0-1   | ⭕   | 旧字段，等同于 congestion_b（向后兼容）          |
| source_file               | string | -     | ❌   | 原始报告路径，便于溯源                          |
| comment                   | string | -     | ❌   | 备注                                            |

**多时钟列**：以 `<CLOCKNAME>_period` / `<CLOCKNAME>_wns` / `<CLOCKNAME>_tns` / `<CLOCKNAME>_path` 命名的列会自动识别为多时钟字段，存入 `extra_fields`。例：`SRAMCLK_wns`、`CLK_CPU_tns`。

**额外列**：不在上表的列（如 `full_dir`、`tag`、`density`、`DRC_violations`）会自动存入 `extra_fields` JSON，在详情中可见。

**比例字段**：`mbb_ratio` / `clock_gating_ratio` / `utilization` / `congestion*` 一律以 **0-1 小数** 上传，系统会自动乘 100 显示为百分比。也接受 0-100 整数（视为百分比）。

### 3.2 CSV 示例

```csv
module_name,version,full_dir,tag,comment,area_total,area_combinational,area_sequential,area_macro,wns_setup,tns_setup,nvp_setup,wns_hold,tns_hold,nvp_hold,power_internal,power_switching,power_leakage,power_total,cell_count,instance_count,net_count,sequential_cell_count,target_frequency,achieved_frequency,mbb_ratio,clock_gating_ratio,utilization,congestion_h,congestion_v,congestion_b,SRAMCLK_period,SRAMCLK_wns,SRAMCLK_tns,SRAMCLK_path
cpu_top,v1.0,/proj/runs/cpu/v1.0,v1.0,baseline,12345.6,5678.9,3456.7,1110.0,-0.123,-0.456,12,0.012,0.034,3,5.6,3.2,1.1,9.9,8500,9000,12000,2100,500.0,476.2,0.85,0.92,0.75,0.16,0.20,0.20,2.50,-0.123,-0.456,/clk_div/SRAMCLK/end_reg
```

### 3.3 字段约束

| 约束                  | 规则                                                                 |
|-----------------------|----------------------------------------------------------------------|
| 必填字段缺失          | 整行拒绝，返回错误信息                                               |
| 模块不存在            | 自动按 module_name 创建（若用户有权限），失败则拒绝                   |
| 数值类型              | 接受 int/float 字符串，自动转换，失败置 null                          |
| `power_total` 缺失    | 自动 = `internal + switching + leakage`                              |
| 时序违例判定          | `wns_setup < 0` 或 `nvp_setup > 0` → 自动触发 setup 告警             |
| 版本号重复            | (module_name, version) 重复时 **覆盖更新**                           |
| `extra_fields`        | 未列出的自定义字段进入 `extra_fields` JSON                           |

---

## 4. 功耗数据 CSV（data_type=power）

可独立上传，按 `(module_name, version)` 合并到已有 QorRecord，仅更新功耗字段，不覆盖其他指标。

### 4.1 列定义

| 字段              | 类型   | 单位 | 必填 | 说明 |
|-------------------|--------|------|------|------|
| **module_name**   | string | -    | ✅   | 必须已存在 |
| **version**       | string | -    | ✅   | 与 QoR 记录的 version 一致 |
| power_internal    | float  | mW   | ⭕   | 内部功耗 |
| power_switching   | float  | mW   | ⭕   | 翻转功耗 |
| power_leakage     | float  | mW   | ⭕   | 漏电功耗 |
| power_total       | float  | mW   | ⭕   | 总功耗 |

### 4.2 CSV 示例

```csv
module_name,version,power_internal,power_switching,power_leakage,power_total
cpu_top,v1.0,5.234,2.891,0.156,8.281
sram_ctrl,v1.0,2.100,1.000,0.400,3.500
```

### 4.3 合并行为

- 若 (module, version) 已有 QorRecord → 仅更新功耗字段，保留其他指标
- 若无匹配 → 跳过该行（建议先上传 QoR 数据）
- 多次上传 → 功耗字段被最新值覆盖

---

## 5. 违例路径 CSV（data_type=violation）

每个 timing group 一个 CSV 文件，文件名建议包含 timing_group 名称（如 `SRAMCLK_violations.csv`）。一个 run 可上传多个文件。

### 5.1 列定义

| 字段        | 类型   | 必填 | 说明                          |
|-------------|--------|------|-------------------------------|
| STARTPOINT  | string | ✅   | 路径起点，如 `a_reg/CK`       |
| ENDPOINT    | string | ✅   | 路径终点，如 `b_refg_0_/D`    |
| SLACK       | float  | ✅   | slack（ns，负值为违例）       |
| DEPTH       | int    | ⭕   | 路径深度                      |
| PURE_DEPTH  | int    | ⭕   | 纯逻辑深度                    |
| CELL_DELAY  | float  | ⭕   | 单元延迟                      |
| NET_DELAY   | float  | ⭕   | 网络延迟                      |
| ET_SLACK    | float  | ⭕   | ET slack                      |
| ST_SLACK    | float  | ⭕   | ST slack                      |
| ST_FANIN    | int    | ⭕   | ST 扇入                       |
| ST_FANOUT   | int    | ⭕   | ST 扇出                       |
| ET_FANIN    | int    | ⭕   | ET 扇入                       |
| ET_FANOUT   | int    | ⭕   | ET 扇出                       |

列名不区分大小写、空格、下划线；表头无法识别时按上述顺序位置映射。

### 5.2 CSV 示例

```csv
STARTPOINT,ENDPOINT,SLACK,DEPTH,PURE_DEPTH,CELL_DELAY,NET_DELAY,ET_SLACK,ST_SLACK,ST_FANIN,ST_FANOUT,ET_FANIN,ET_FANOUT
a_reg/CK,b_refg_0_/D,-0.020,27,23,500,77,9,-10,1,122,122,11
clk_div/U1/Z,foo_reg/D,-0.045,15,12,320,55,5,-8,1,80,80,5
```

### 5.3 关联与覆盖

- 文件名（去 `.csv` 后缀，去 `_violations` 后缀）作为 `timing_group`
- 关联到 (module, version) 对应的 QorRecord
- 同一 (record, timing_group) 重复上传 → 覆盖旧路径，不累积

### 5.4 时钟多列数据 → Dashboard 违例分析 (v5.0)

Dashboard 违例分析页 (`#chartTiming`) 支持两种模式：

| 模式             | 切换                 | metric 选择  | clock 选择   | 渲染方式              |
|------------------|----------------------|--------------|--------------|-----------------------|
| **时序分析模式** | 关闭"按指标聚合"开关  | 单选         | 单选         | 一张图                 |
| **违例分析模式** | 开启"按指标聚合"开关  | 多选         | **多选**     | **每个 clock 并排一张子图**（v5.0 新增） |

> v4.x 仅支持 clock 单选, v5.0 升级为多选, 选中的每个 clock 都会独立渲染一张折线/柱状图, 容器使用 flex 横向排版.

**子图布局规则**:

| 选中的 clock 数 | 子图宽度                  | 子图高度 |
|-----------------|---------------------------|----------|
| 1               | 100%                      | 500px    |
| 2               | 50% - 6px                 | 460px    |
| 3               | 33.33% - 8px              | 400px    |
| ≥ 4             | 50% - 6px (自动换行)      | 380px    |

**多 clock 数据来源**:

- 单条 `QorRecord` 的 `extra_fields` 中以 `<CLOCK>_wns / <CLOCK>_tns / <CLOCK>_period` 存储
- 或上传 `data_type=qor` 时, CSV 含 `<CLOCK>_period / <CLOCK>_wns / <CLOCK>_tns / <CLOCK>_path` 列
- 多 clock 列名示例如：`SRAMCLK_wns`、`CLK_CPU_tns`、`SYS_CLK_period`

**JSON 解析层** (`qor_parser.py`):

```python
CLOCK_FIELD_PATTERN = re.compile(
    r'^(.+?)_(hold_wns|hold_tns|hold_path|period|wns|tns|path)$',
    re.IGNORECASE,
)
```

- 第一个下划线前的部分作为 clock 名（可含下划线, 非贪婪匹配）
- 字段后缀仅识别 `period / wns / tns / path / hold_wns / hold_tns / hold_path`

---

## 6. Run 备注 CSV（data_type=notes）

记录本次 run 的重要修改、参数、策略，在 Dashboard 以表格形式展示。

### 6.1 列定义

| 字段          | 类型   | 必填 | 说明                                              |
|---------------|--------|------|---------------------------------------------------|
| **item**      | string | ✅   | 项目名（如 "综合策略"、"目标频率"、"修改内容"）   |
| **description** | string | ⭕   | 描述/值（如 "compile_ultra"、"500MHz"、"优化关键路径"） |
| full_dir      | string | ⭕   | Run 目录路径，用于区分同 module+version 下不同 run |

列名不区分大小写、空格、下划线、连字符。常见别名：

- `item` → `name` / `key` / `parameter` / `param` / `参数` / `项目`
- `description` → `desc` / `value` / `val` / `note` / `comment` / `说明` / `描述` / `备注` / `值`
- `full_dir` → `fulldir` / `dir` / `directory` / `path` / `目录` / `路径` / `run_dir`

### 6.2 两种 CSV 格式

**格式 A：2 列（item, description），通过参数传入 full_dir**

```csv
item,description
综合策略,compile_ultra
目标频率,500MHz
修改内容,优化了关键路径 retiming, 插入 buffer 解决 hold 违例
```

**格式 B：3 列（item, description, full_dir），每行可指定不同 full_dir**

```csv
item,description,full_dir
综合策略,compile_ultra,/scratch/runs/v1.0_corner_ss
综合策略,compile_fast,/scratch/runs/v1.0_corner_ff
目标频率,500MHz,/scratch/runs/v1.0_corner_ss
目标频率,600MHz,/scratch/runs/v1.0_corner_ff
```

### 6.3 full_dir 来源优先级

1. CSV 行内的 `full_dir` 列（格式 B）
2. 上传时通过 `--full-dir` 参数 / `QOR_FULL_DIR` 环境变量 / 表单 `full_dir` 字段传入的值
3. 若都没有 → `full_dir = null`，作为该 module+version 的通用备注（兼容老数据）

### 6.4 关联与覆盖（核心策略）

**关联 QorRecord**：

1. 按 (module_id, version) 查找候选 QorRecord
2. 若 full_dir 非空 → 在候选中按 `QorRecord.extra_fields.full_dir` 精确匹配
3. 找不到精确匹配 → 回退到第一条候选（兼容老数据）

**覆盖旧备注**（再次 `make upload-notes` 不会累积）：

- 按 `(qor_record_id, full_dir)` 删除该 (record, 目录) 的所有旧备注
- 然后写入本次 CSV 的新备注
- 其他 full_dir 的备注不受影响

**示例**：

```
# 第一次 make: 写入 /scratch/runs/v1.0 的 3 条备注
make upload-notes  # CSV 含 3 行

# 第二次 make: 覆盖 /scratch/runs/v1.0 的备注 (新 CSV 2 行)
make upload-notes  # 数据库中该目录的备注变为 2 条, 不是 5 条

# 另一个目录 make: /scratch/runs/v2.0 的备注独立写入, 不影响 v1.0
cd /scratch/runs/v2.0 && make upload-notes
```

---

## 7. API 端点参考

### 7.1 上传 CSV（推荐）

```
POST /api/v1/upload
Header: X-API-Key: qor_xxxxxxxx
Content-Type: multipart/form-data
```

表单字段：

| 字段           | 必填 | 说明                                                |
|----------------|------|-----------------------------------------------------|
| project_id     | ✅   | 项目 ID                                             |
| version        | ✅   | 版本标签                                            |
| files          | ✅   | CSV 文件（支持多文件，violation 类型一次可多个）    |
| data_type      | -    | `qor` / `power` / `violation` / `notes`，默认 `qor` |
| module_id      | -    | 模块 ID（不传则从 CSV 的 module_name 识别）         |
| mark_released  | -    | `1` 则上传后标记为已发布                            |
| full_dir       | -    | Run 目录路径（仅 notes 类型有效）                   |
| release_dir    | -    | 发布目录（v5.0，仅 qor 类型有效，整批覆盖）         |

### 7.2 程序化提交 QoR JSON

```
POST /api/v1/qor/upload
Header: X-API-Key: qor_xxxxxxxx
Content-Type: application/json
```

```json
{
  "project_id": 1,
  "module_id": 5,
  "data": [
    {
      "module_name": "cpu_top",
      "version": "v1.0",
      "full_dir": "/proj/runs/cpu/v1.0",
      "release_dir": "/proj/runs/cpu/v1.0",
      "area_total": 12345.6,
      "wns_setup": -0.123,
      "congestion_h": 0.16,
      "extra_fields": { "density": 0.78 }
    }
  ]
}
```

### 7.3 获取 Run 备注

```
GET /api/run_notes?module_id=5&version=v1.0&full_dir=/scratch/runs/v1.0
```

返回该 (module, version, full_dir) 的所有备注项。`full_dir` 可选，不传则返回所有目录的备注。

### 7.4 模块协作 API（v5.0 新增）

```
GET    /api/modules/<id>/collaborators
POST   /api/modules/<id>/collaborators       # Body: {"user_id": 7}
DELETE /api/modules/<id>/collaborators/<user_id>
```

- 仅模块 owner / admin 可管理协作者
- 只能授权 `owner` 角色用户（viewer 不能成为协作者）
- 协作者可上传/管理该模块下数据；其他 owner 仍可见该模块的"已发布"数据，但不可写

### 7.5 部署后的健康检查与连通性

```bash
# 1. 健康检查
curl -s http://<host>:5000/health   # 应返回 200

# 2. 验证 API Key 有效
curl -s -H "X-API-Key: qor_xxx" http://<host>:5000/api/v1/projects

# 3. 检查数据库连通 (使用 db_init.py 内置校验)
python db_init.py --check
# 期望输出: DB_TYPE + DATABASE_URL + 各项目 DB 文件存在性

# 4. 检查项目库生成情况
ls -la data/qor_p_*.db   # 应有 1 个主库 + N 个项目库
```

### 7.6 完整 API 索引

| 端点                                       | 方法 | 认证    | 说明                              |
|--------------------------------------------|------|---------|-----------------------------------|
| `/api/v1/upload`                           | POST | upload  | CSV 批量上传                      |
| `/api/v1/qor/upload`                       | POST | upload  | JSON 形式 QoR 上传                |
| `/api/v1/qor/record/<id>`                  | GET  | read    | 单条 QoR 记录详情                 |
| `/api/v1/qor/aggregate`                    | GET  | read    | 目录/模块/版本聚合                |
| `/api/v1/projects`                         | GET  | read    | 项目列表                          |
| `/api/v1/projects`                         | POST | upload  | 创建项目                          |
| `/api/v1/projects/<id>`                    | GET  | read    | 项目详情                          |
| `/api/v1/projects/<id>/members`            | GET/POST/DELETE | upload | 项目成员管理        |
| `/api/v1/modules`                          | GET  | read    | 模块列表                          |
| `/api/v1/modules/<id>`                     | GET  | read    | 模块详情                          |
| `/api/v1/modules/<id>/collaborators`       | GET/POST/DELETE | upload | 模块协作（v5.0）       |
| `/api/v1/admin/records/<id>/release`       | POST | admin   | 发布/撤回 QoR 记录                |
| `/api/v1/admin/qor/<id>/release`           | POST | admin   | 发布/撤回 QoR 记录（短路径）      |
| `/api/v1/admin/projects/<id>`              | DELETE | admin | 软删除项目                       |
| `/api/v1/admin/projects/<id>/hard_delete`  | POST | admin   | 硬删除项目（confirm=true）        |
| `/api/v1/admin/projects/<id>/restore`      | POST | admin   | 恢复软删除项目                    |
| `/api/v1/locks`                            | GET/POST/DELETE | upload | 数据锁管理                |
| `/api/v1/apikeys`                          | GET/POST/DELETE | read | API Key 管理                 |
| `/api/v1/alerts/rules`                     | GET/POST/DELETE | upload | 告警规则管理               |
| `/api/v1/alerts/events`                    | GET  | read    | 告警事件                          |
| `/api/run_notes`                           | GET  | read    | 获取 Run 备注                     |
| `/api/qor_data`                            | GET  | read    | QoR 数据查询                      |
| `/api/v1/user/theme`                       | GET/POST | session | 用户主题                  |

> 短路径与蓝图路径同时存在（如 `/api/admin/qor/<id>/release` 与 `/api/admin/records/<id>/release`），前者是历史兼容路径，后者是 v3.x 起的标准。

---

## 8. 命名与版本规范建议

| 项                    | 建议                                                  | 示例                          |
|-----------------------|-------------------------------------------------------|-------------------------------|
| module_name           | 与综合脚本中 top module 名严格一致，大小写敏感        | `cpu_top`, `SRAM_CTRL`        |
| version               | 推荐格式 `<branch>_<date>_<short_hash>` 或语义版本    | `main_20260301_a1b2c3`        |
| 同 module 多次上传    | 用 `version` 区分，不要用 module_name 加后缀          | `cpu_top/v1`, `cpu_top/v2`    |
| 违例路径文件名        | `<timing_group>_violations.csv`                       | `SRAMCLK_violations.csv`      |
| full_dir              | 用绝对路径，建议传 Makefile 的 `$(PWD)`               | `/scratch/runs/cpu/v1.0`      |

---

## 9. 单位约定（全系统统一）

| 维度   | 单位 |
|--------|------|
| 面积   | um²  |
| 时序   | ns   |
| 功耗   | mW   |
| 频率   | MHz  |
| 比例   | 0-1 小数（系统自动转百分比显示） |
| 数量   | 整数 |

---

## 10. 编码与容错

- CSV 编码支持：UTF-8 BOM / UTF-8 / GBK / Latin-1（自动检测）
- 空值可用 `-`、`N/A`、`NULL`、空字符串表示
- 列名标准化：小写 + 去除空格/下划线/连字符后匹配别名表
- 多时钟列 `<CLOCK>_{period,wns,tns,path}` 自动识别
- 表头无法识别的列进入 `extra_fields`

---

## 11. 常见错误示例

| 错误                          | 现象                                   | 修正                                              |
|-------------------------------|----------------------------------------|---------------------------------------------------|
| `wns_setup = 0.123`           | 负值丢失，系统认为无违例               | slack 始终带符号，应为 `-0.123`                   |
| `mbb_ratio = 85`              | -                                      | 可接受，系统识别为 85%；推荐用 `0.85`             |
| `version = ""`                | 重复上传覆盖默认 v1，数据混乱          | 每次 run 必须带唯一 version                       |
| `module_name = "CPU_top"`     | 与系统中的 `cpu_top` 不匹配            | 大小写必须一致                                    |
| 单位混用 (ps 与 ns)           | 指标尺度错乱                           | 全系统统一 ns / mW / um² / MHz                    |
| notes 未传 full_dir           | 多目录 run 备注互相覆盖                | Makefile 中用 `--full-dir $(PWD)` 或 `QOR_FULL_DIR` |
| notes 多次 make 数据累积      | 同目录备注越积越多                     | 系统已按 (record, full_dir) 自动覆盖，确认 full_dir 一致 |

---

## 12. 校验与告警触发

系统会在导入时自动执行：

1. **类型校验**：数值字段字符串自动转换，失败置 null
2. **必填校验**：`module_name` + `version` 缺失时整行拒绝
3. **单位归一化**：所有指标单位已在字段定义中固定
4. **自动告警**：
   - `wns_setup < 0` 或 `nvp_setup > 0` → 触发 `timing_setup` 告警
   - `wns_hold < 0` → 触发 `timing_hold` 告警
   - `congestion_b > 0.8`（或旧字段 `congestion > 0.8`）→ 触发 `congestion` 告警
   - `achieved_frequency < target_frequency` → 触发 `frequency` 告警
5. **覆盖更新**：
   - QoR：相同 `(module_name, version)` 覆盖旧记录
   - Power：相同 `(module_name, version)` 合并到已有记录
   - Violation：相同 `(record, timing_group)` 覆盖旧路径
   - Notes：相同 `(qor_record_id, full_dir)` 覆盖旧备注

---

## 13. 完整 Run 对象（API 返回格式）

```json
{
  "id": 123,
  "module_id": 5,
  "module_name": "cpu_top",
  "project_name": "MyChip",
  "version": "v1.0",
  "tag": "v1.0",
  "comment": "baseline after APR fix",
  "full_dir": "/proj/cpu/runs/v1.0",
  "area_total": 12345.6,
  "wns_setup": -0.123,
  "tns_setup": -0.456,
  "nvp_setup": 12,
  "power_total": 9.9,
  "cell_count": 8500,
  "target_frequency": 500.0,
  "achieved_frequency": 476.2,
  "congestion_h": 0.16,
  "congestion_v": 0.20,
  "congestion_b": 0.20,
  "source_file": "/proj/cpu/reports/syn/20260301.rpt",
  "recorded_at": "2026-03-01T14:30:00",
  "extra_fields": {
    "density": 0.78,
    "SRAMCLK_wns": -0.123,
    "SRAMCLK_path": "/clk_div/SRAMCLK/end_reg"
  },
  "notes": [
    { "item": "综合策略", "description": "compile_ultra", "full_dir": "/proj/cpu/runs/v1.0" }
  ]
}
```

---

## 14. 指标方向约定（v3.0 统一）

> 本节说明每个指标在系统中的"评价方向"，用于差分对比、聚合排序、阈值告警等。

| 指标族        | 字段                                            | 方向 (`min` / `max`) | 说明                                                |
|---------------|-------------------------------------------------|----------------------|-----------------------------------------------------|
| 面积          | `area_total` / `area_combinational` / `area_sequential` / `area_black_box` / `area_macro` | `min` | 越小越好                                  |
| 单元数        | `cell_count` / `instance_count` / `net_count` / `sequential_cell_count` | `min` | 越小越好                                  |
| **时序**      | `wns_setup` / `wns_hold`                        | **`min`**            | v3.0 统一：负值=违例，越小(更负)=越差，越大=越好   |
|               | `tns_setup` / `tns_hold`                        | **`min`**            | v3.0 统一：累计违例，越小(更负)=越差                |
|               | `nvp_setup` / `nvp_hold`                        | `min`                | 违例路径数越少越好                                  |
| 功耗          | `power_total` / `power_internal` / `power_switching` / `power_leakage` | `min` | 越小越好                                  |
| 物理          | `mbb_ratio` / `clock_gating_ratio`              | `max`                | 合并率/覆盖率越高越好                               |
|               | `utilization`                                   | `mid`                | 适中最好（前端默认按 `min` 处理，业务可覆盖）       |
| 拥塞          | `congestion` / `congestion_h` / `congestion_v` / `congestion_b` | `min` | 越小越好                                  |
| 频率          | `target_frequency` / `achieved_frequency`      | `max`                | 越高越好                                            |

**v3.0 关键变更**：
- `wns_setup` / `tns_setup` / `wns_hold` / `tns_hold` 从 v2.0 的 `max` 改为 **`min`**
- 理由：与用户约定保持一致（违例方向统一为"越小越差"），前端不再显示"方向"列以避免概念混淆
- 业务影响：Dashboard 同比/环比计算时，WNS 减小(更负) 视为恶化（红色），增大(更接近 0 或正) 视为改善（绿色）

API 返回时会同时给出 `metric_directions` 字段：

```json
GET /api/qor/aggregate?group_by=module
{
  "metric_directions": {
    "area_total":      "min",
    "wns_setup":       "min",
    "tns_setup":       "min",
    "nvp_setup":       "min",
    "wns_hold":        "min",
    "tns_hold":        "min",
    "nvp_hold":        "min",
    "mbb_ratio":       "max",
    "achieved_frequency": "max"
  }
}
```

---

## 15. `full_dir` 字段规范（v3.0 升级）

> 自 v3.0 起，`QorRecord.full_dir` 从 `extra_fields` JSON 字段提升为**独立列**，支持按目录索引与聚合。

### 15.1 字段定义

| 属性     | 值                                                          |
|----------|-------------------------------------------------------------|
| 列名     | `full_dir`                                                  |
| 类型     | `String(512)`                                               |
| 必填     | 否（推荐填写，特别是多 corner / 多 sub-run 场景）           |
| 索引     | 普通索引（用于按目录过滤）                                  |
| 唯一性   | 不唯一——同一 module + version 可有多个不同 `full_dir` 的 run |

### 15.2 路径格式

```
<base_dir>/<sub_path>/<run_name>
```

| 段         | 含义                                            | 示例                                  |
|------------|-------------------------------------------------|---------------------------------------|
| `base_dir` | 综合器 run 的根目录（一次完整 DC run）          | `v1.0` / `2026Q3_w1` / `2026_0728_weekly` |
| `sub_path` | 子目录（多 corner / 多 sub-run 区分）           | `main` / `corner_ss` / `corner_ff`    |
| `run_name` | 本次 run 的具体名称（一个 base_dir 内唯一）     | `cpu_core_baseline` / `cpu_core_cfg1` |

**示例**：
```
v1.0/main/cpu_core_baseline
v1.0/corner_ss/cpu_core_baseline
v1.0/corner_ff/cpu_core_cfg1
2026Q3_w2/corner_tt/lsu_opt_speed
```

### 15.3 用途

- **避免歧义**：同一 module 下不同 base_dir 可能有同名 run（如 `cpu_core_baseline`），用 `full_dir` 作为唯一标识
- **目录聚合**：按 `base_dir` 跨模块汇总，或按 `module` 跨 base_dir 汇总（见 §16）
- **Run 备注关联**：notes 的 `full_dir` 字段用于精确匹配到某条具体 QorRecord
- **Dashboard 跳转**：URL `/qor_record/<id>` 直接展示该 full_dir 下的所有指标详情

### 15.4 兼容老数据

v2.0 数据原本将 `full_dir` 存于 `extra_fields` JSON 中。v3.0 提供数据库迁移：

```bash
flask db upgrade    # 自动迁移 + 回填
# 或手动回填:
python -c "
from app import app, db
from models import QorRecord
import json
with app.app_context():
    for r in QorRecord.query.filter(QorRecord.full_dir.is_(None)).all():
        ef = json.loads(r.extra_fields or '{}')
        if 'full_dir' in ef:
            r.full_dir = ef['full_dir']
    db.session.commit()
"
```

---

## 16. 目录聚合 API（v3.0 新增）

> `GET /api/qor/aggregate` 支持按 `run` / `base_dir` / `module` 三种维度聚合 QoR 数据，解决同名 run 在不同 base_dir 下的歧义问题。

### 16.1 接口

```
GET /api/qor/aggregate
```

| 参数            | 必填 | 说明                                                            |
|-----------------|------|-----------------------------------------------------------------|
| `project_ids`   | ✅   | 项目 ID（逗号分隔，支持多项目）                                 |
| `group_by`      | -    | `run`（默认）/ `base_dir` / `module`                            |
| `metric`        | -    | 指标名（默认 `area_total`）；支持多次调用取不同指标             |
| `modules`       | -    | 模块 ID 过滤（可选）                                            |
| `versions`      | -    | 版本过滤（可选）                                                |
| `base_dirs`     | -    | base_dir 过滤（可选，仅 `group_by=run` 时有效）                 |

### 16.2 三种 group_by 示例

**group_by=run**（默认）：每条 QorRecord 一行
```json
{
  "rows": [
    {
      "key": "v1.0/main/cpu_core_baseline",
      "module": "cpu_core",
      "base_dir": "v1.0",
      "sub_path": "main",
      "run_name": "cpu_core_baseline",
      "version": "v1.0_baseline",
      "count": 1,
      "area_total_avg": 12345.6
    }
  ]
}
```

**group_by=base_dir**：跨模块跨 run 汇总
```json
{
  "rows": [
    {
      "key": "v1.0",
      "count": 8,
      "modules": ["cpu_core", "lsu", "ifu"],
      "area_total_avg": 10500.2
    }
  ]
}
```

**group_by=module**：跨 base_dir 跨 run 汇总
```json
{
  "rows": [
    {
      "key": "cpu_core",
      "count": 7,
      "base_dirs": ["v1.0", "v1.1", "v2.0"],
      "area_total_avg": 11200.4
    }
  ]
}
```

### 16.3 配合 `metric_directions` 做同比

```javascript
const data = await fetch('/api/qor/aggregate?project_ids=1&group_by=module&metric=area_total').then(r => r.json());
const dirs = data.metric_directions;  // { area_total: 'min', wns_setup: 'min', ... }
for (const row of data.rows) {
    // 行内比较 (vs 上一行): 用 row.area_total_avg 的差值
    // 用 dirs.area_total ('min') 决定恶化方向
}
```

---

## 17. Demo 数据生成脚本（`seed_demo_data.py`，v3.0 新增）

> 用于一键生成符合演示需求的多项目/多模块/多 base_dir QoR 数据，覆盖 Dashboard/对比/Review 等功能。

### 17.1 用法

```bash
# 完整重置 + 重新生成 (推荐, 干净状态)
python seed_demo_data.py --clean-all

# 仅清空 demo 命名空间的数据
python seed_demo_data.py --clean

# 增量补充 (项目已存在则跳过)
python seed_demo_data.py

# 仅打印计划, 不写库
python seed_demo_data.py --preview

# 指定随机种子, 便于复现
python seed_demo_data.py --seed 12345
```

### 17.2 生成规则

| 维度        | 数量                                | 命名方式                                          |
|-------------|-------------------------------------|---------------------------------------------------|
| 项目        | **5 个**                            | `demo_riscv_soc` / `demo_dsp_engine` / `demo_video_codec` / `demo_eth_mac` / `demo_ai_accel` |
| 模块/项目   | **5 ~ 10 个**（随机）               | 见 `DEMO_PROJECTS` 表，模块名贴近真实 IP（cpu_core / lsu / fft_core ...） |
| base_dir/模块 | **2 ~ 3 个**（随机）              | 按项目类型选 `v1.0/v1.1/v2.0` 或 `2026Q3_w1/w2/w3` 等 |
| run/base_dir | **2 ~ 3 个**（随机）               | 后缀 `baseline` / `cfg1` / `cfg2` / `opt_speed` / `opt_area` / `mbb_aggr` |
| 总记录数    | 约 **200+ 条**                      | 默认 seed 20260728 约生成 227 条                  |

### 17.3 数据特性

- **方向一致**：优秀 base_dir 在"越小越好"指标上数值更小（乘以 factor），"越大越好"指标上数值更大（除以 factor）
- **趋势平滑**：同一 base_dir 内的 run 趋势一致（`base_seed = hash(base_dir) & 0xFFFF`）
- **时序合理**：WNS 在 -1.0~0.5ns 之间，TNS 在 -50~5ns 之间，NVP 0~500 之间
- **覆盖所有指标族**：面积/时序/功耗/单元/MBB/CG/拥塞全有数据
- **时序方向统一为 min**：v3.0 之后 WNS/TNS/NVP 全部按"越小越好"生成

### 17.4 配套的清理逻辑

`--clean-all` 会按以下顺序删除（修复外键约束错误）：

```
TileReview / GroupReview / SubsystemReview / ReviewSnapshot / ReviewFile
  → ProjectMember / DashboardGroup
    → 非系统项目 (排除 _system / system / admin / default)
      → 模块/记录 (级联)
```

### 17.5 配合迁移 / 测试

- 第一次部署：先 `flask db upgrade`，再 `python seed_demo_data.py --clean-all`
- 测试新功能：随时 `python seed_demo_data.py --clean-all` 重置到干净 demo 状态
- 性能压测：调整 `DEMO_PROJECTS` / `RUN_SUFFIXES` 扩大规模

---

## 18. QoR 记录详情页（v3.0 新增）

> 每条 QorRecord 都有独立详情页，展示完整指标、状态、与同 module+version 横向对比。

### 18.1 访问

```
GET /qor_record/<record_id>
GET /qor_record/<record_id>?from=dashboard   # 跳转回 Dashboard
```

### 18.2 页面内容

| 区块         | 说明                                              |
|--------------|---------------------------------------------------|
| 元信息卡     | 模块 / 项目 / 版本 / full_dir / 记录时间 / source_file |
| 核心指标卡   | 总面积 / 总功耗 / 总违例数 / 频率 / 良率         |
| 全部指标表   | 27+ 指标 + 状态（满足/边缘/违例）                |
| 横向对比     | 同 module+version 下其他 full_dir 的指标         |
| 跳转按钮     | → Dashboard（按 full_dir 定位） / → 记录管理     |

### 18.3 API

```
GET /api/qor/record/<record_id>
```

返回：
```json
{
  "record": { "id": 123, "module_name": "cpu_core", "full_dir": "v1.0/main/...", "area_total": 12345.6, ... },
  "siblings": [
    { "id": 124, "full_dir": "v1.0/corner_ss/...", "area_total": 12400.1 },
    { "id": 125, "full_dir": "v1.0/corner_ff/...", "area_total": 12200.5 }
  ],
  "metric_directions": { "area_total": "min", "wns_setup": "min", ... }
}
```

### 18.4 入口

- **记录管理页** (`/admin#records`)：点击记录 ID 即跳转
- **Dashboard 顶部 banner**：跳转链接附在该 run 的 Banner 上

---

## 19. Review 工作流（v3.0 新增）

> 三级审核模型：Tile → Group → Subsystem，每级自动汇总下级指标。

### 19.1 模型层级

```
SubsystemReview (子系统级, e.g. CPU 整体)
  └─ GroupReview (模块组, e.g. CPU 子模块集合)
       └─ TileReview (单个 tile/module)
```

### 19.2 状态流转

```
Draft → Submitted → Approved
                 ↘ Rejected → (修订后) → Re-Submitted → Approved
```

### 19.3 权限（v5.0 更新）

| 角色     | 权限                                  |
|----------|---------------------------------------|
| admin    | 所有项目所有操作                      |
| owner    | 自己/协作模块的所有操作 + 授权协作者  |
| viewer   | 只读 + 仅看已发布数据                 |

> v4.x 的 `editor` 角色已合并入 `owner`. v4.x 的 `release` 角色已自动迁移为 `owner`. 现有 release 用户的发布/撤回权限保留.

### 19.4 页面

```
GET /review
```

支持：
- 项目筛选
- Tile / Group / Subsystem 切换
- 卡片式 Review 列表（折叠面板）
- 提交 / 批准 / 驳回 操作
- 关联 QorRecord 的指标对比

---

## 20. 实际环境部署清单（v5.0）

> 本节是 IC 团队在生产环境部署时必须完成的检查清单. 部署顺序: IT 部署服务 → 应用管理员初始化数据 → 业务用户提交数据.

### 20.1 部署前确认

| 项                                          | 说明                                                                | 必填 |
|---------------------------------------------|---------------------------------------------------------------------|------|
| 服务器 IP / 域名                            | 反代后用户访问的地址                                                | ✅   |
| Linux 发行版                                | Ubuntu 20.04+ / Debian 11+ / CentOS 8+ / Rocky 8+                  | ✅   |
| Python 3.9+ 与 venv                        | 避免污染系统 Python                                                 | ✅   |
| 数据库后端                                  | SQLite (默认) / MySQL / MongoDB, 选定后写入 `.env` 的 `DB_TYPE`     | ✅   |
| Nginx + Let's Encrypt / 自签证书           | HTTPS 终止 + 静态资源加速                                          | ⭕   |
| SECRET_KEY 强随机值                         | `openssl rand -hex 32`, 必须非默认                                  | ✅   |
| `.env` 权限                                | `chmod 640`, `chown qor:qor`                                        | ✅   |

### 20.2 部署步骤（精简版）

```bash
# 1. 创建用户与目录
sudo useradd -r -s /sbin/nologin -M -d /opt/qor_recorder qor
sudo mkdir -p /opt/qor_recorder && sudo chown qor:qor /opt/qor_recorder

# 2. 部署代码
cd /opt/qor_recorder
sudo -u qor git clone <your-repo-url> .

# 3. 安装依赖
sudo -u qor python3 -m venv venv
sudo -u qor bash -c 'source venv/bin/activate && pip install -r requirements.txt'

# 4. 写 .env (关键 4 项)
sudo -u qor cp .env.example .env
SECRET=$(openssl rand -hex 32)
sudo -u qor bash -c "cat >> .env <<EOF
SECRET_KEY=$SECRET
HOST=127.0.0.1
DEBUG=0
SESSION_COOKIE_SECURE=1
DB_TYPE=sqlite
EOF"

# 5. 创建数据/上传/备份目录
sudo -u qor mkdir -p data uploads backups logs

# 6. 初始化数据库 (含 admin/release/viewer 默认账户)
sudo -u qor bash -c 'source venv/bin/activate && python db_init.py'

# 7. 安装 systemd 单元
sudo cp deploy/qor_recorder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qor_recorder

# 8. 配置 Nginx 反代 (参考 deploy/README.md §7)
sudo cp deploy/nginx/qor_recorder.conf /etc/nginx/conf.d/
sudo nginx -t && sudo systemctl reload nginx

# 9. (可选) 配置 HTTPS 证书
sudo certbot --nginx -d qor.example.com

# 10. 验证
curl -s http://localhost/health
curl -s -H "X-API-Key: $(cat /home/qor/.qor_api_key)" http://localhost/api/v1/projects
```

### 20.3 应用管理员（IC 团队）首次使用

部署完成, IT 移交后, 应用管理员需执行:

```bash
# 1. 登录 Web, 修改默认密码
#    admin  / admin@2026   → 强密码
#    release / release@2026 → 强密码
#    viewer  / viewer@2026  → 强密码
#    (首次登录强制跳转 /change_password)

# 2. 创建 API Key (用于 DC 流程自动化上传)
#    管理 → API Key → 创建 → name=dc-bot, scope=upload
#    保存到:
#    echo "qor_xxx" > /home/dc/.qor_api_key && chmod 600 /home/dc/.qor_api_key

# 3. 创建项目 (与 IC 项目代号一致)
#    管理 → 项目 → 新建
#    自动生成 qor_p_<id>.db

# 4. 创建模块 (与 RTL 顶层模块名一致)
#    管理 → 项目 → 进入 → 模块 → 新建
#    填写 owner_id (数据归属人) + collaborators (协作者)

# 5. 邀请协作者 / 客户
#    协作者: 创建 owner 角色用户, 在模块中授权
#    客户:   创建 viewer 角色用户, 推已发布数据后, 仅 viewer 可见
```

### 20.4 业务用户（综合工程师）集成

将 `scripts/Makefile.example` 复制到 DC run 目录, 修改 `PROJECT_ID` / `API_KEY_FILE`:

```makefile
# Makefile (简化)
PROJECT_ID = 1
API_KEY_FILE = /home/dc/.qor_api_key
UPLOAD_SCRIPT = /opt/qor_recorder/scripts/upload_qor.sh
QOR_CSV = $(PWD)/qor_report.csv
VIOLATION_CSVS = $(wildcard $(PWD)/violations/*_violations.csv)
RUN_DIR = $(PWD)
```

```bash
# DC 综合流程结束后
make upload-all   # 上传 QoR + 功耗 + 违例 + 备注
make release      # 上传并标记为已发布 (对外可见)
```

### 20.5 部署后常见错误速查

| 错误现象                                                    | 原因                                          | 解决                                                            |
|------------------------------------------------------------|-----------------------------------------------|-----------------------------------------------------------------|
| 启动报错 `SECRET_KEY is not set`                          | `.env` 未配置或仍为默认值                    | 编辑 `.env`, `SECRET_KEY=$(openssl rand -hex 32)`               |
| 首次登录后所有写操作返回 403                               | `must_change_password=True`                  | 走 `/change_password` 改密后自动清除                           |
| 上传 400 `data not allowed`                                | CSRF 校验失败                                 | 用 API Key 认证 (`X-API-Key: ...`)                              |
| 违例分析页 clock 列表为空                                  | CSV 没有 `<CLOCK>_*` 列                       | 添加多时钟列, 或在 QoR 上传后使用页面再确认                    |
| 客户 viewer 登录后看到空白                                  | 数据未发布                                    | admin / owner 在管理 → 记录管理 → 批量发布                     |
| 切换 `DB_TYPE=mongodb` 后启动失败                          | `MONGODB_URI` 未配置                          | 编辑 `.env`, `MONGODB_URI=mongodb://...`                       |
| 项目库 `qor_p_<id>.db` 损坏                                | Windows 文件锁 / 异常中断                     | 关闭所有连接, 用 `backups/` 恢复                                |
| Docker 部署后 502 Bad Gateway                              | 应用未启动 / 端口错                           | `docker logs qor_recorder` 排查                                |
| Nginx 502 + SELinux 阻止                                   | RHEL 系常见                                   | `sudo setsebool -P httpd_can_network_connect 1`                |

### 20.6 升级到 v5.0 的迁移

从 v4.x 升级时, 启动会自动完成:

1. **角色迁移**: `user` / `release` → `owner` (启动时 SQL 一行)
2. **默认账户创建**: 若不存在 `viewer / viewer@2026`, 自动创建
3. **字段补全**: `modules.owner_id` / `modules.collaborators` 字段新增 (Alembic 迁移)
4. **API Key 表**: 已存在, 无需迁移
5. **历史数据**: 完全保留, 无破坏性变更

回滚方案:

```bash
# 1. 停止应用
sudo systemctl stop qor_recorder

# 2. 恢复 v4.x 代码
cd /opt/qor_recorder
sudo -u qor git checkout v4.x

# 3. 恢复数据库 (迁移前已备份)
sudo -u qor cp backups/main_<date>.db data/qor_recorder.db
sudo -u qor cp backups/qor_p_*.db data/

# 4. 启动
sudo systemctl start qor_recorder
```

### 20.7 客户/只读用户（viewer）交付清单

实际部署常需要给客户/跨团队开 viewer 账号:

```bash
# 1. 管理员创建 viewer 用户
#    管理 → 用户管理 → 新建 → role=viewer

# 2. (可选) 限制 viewer 可见项目: 用 DashboardGroup + is_public=True
#    只有 is_public=True 的组对所有登录用户可见

# 3. 推已发布数据: admin / owner 在管理 → 记录管理批量发布
#    viewer 仅能看到 is_released=True 的记录

# 4. 提供给客户:
#    URL: https://qor.example.com/login
#    账号: viewer_xxx
#    密码: 强密码 (强制首登改密)
#    可见: 仅已发布数据, 无上传/管理权限
```

---

**文档版本**: 5.0
**最后更新**: 2026-07-30（v5.0: 三级角色模型 + 模块协作 + 时钟多选）
**维护**: QoR Recorder Team
