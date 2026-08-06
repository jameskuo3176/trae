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
>
> **v5.1 更新（2026-08-04）**:
> - **DC 报告直传**: `/api/v1/qor/upload?project_id=N&version=V` 支持原始 DC JSON 直传
>   - `project_id` / `version` 走 URL query, 不进 JSON
>   - `module` = DC.`top_module` (无须指定)
>   - `register_count` = DC.`misc.fgcg.total_flops` (新增字段)
>   - 完整 DC JSON 存 `QorRecord.raw_dc_report` (新增字段)
>   - 1 个 DC 报告 = 1 条 QorRecord (多 scenarios/path_groups 存到 `extra_fields.scenarios`)
> - **Dashboard DC 报告表格视图** (默认): 行=字段路径, 列=选中的 run, 支持多 run 对比 + 变化标注 (≥5% 标红/标绿) + CSV 导出
> - `upload_qor.sh` 自动识别 DC 报告格式, 直接转发, 不再走 `dc_report_to_json.py` 中转

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
综合策略,compile_ultra,/scratch/runs/v1.0/variant_a
综合策略,compile_fast,/scratch/runs/v1.0/variant_b
目标频率,500MHz,/scratch/runs/v1.0/variant_a
目标频率,600MHz,/scratch/runs/v1.0/variant_b
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

## 6.5 JSON 统一上传格式 (v5.0+ 推荐, CSV 超集)

> **设计目标**: 用一个 JSON 文件描述一次综合 run 的**完整快照**——含 QoR / 功耗 / 违例路径 / Run 备注 / Run 元数据, 是 §3~§6 全部 CSV 格式的**超集**, 同时向下兼容 (CSV → JSON 转换器可逆).
>
> **建议**: 长期使用 JSON 替代 CSV (DC 流程 Makefile 端直接生成 JSON, 系统一站式解析). CSV 仍保留 (老 Makefile 兼容), 但新项目/新工具建议直接输出 JSON.

### 6.5.1 设计原则

| 原则                  | 说明                                                                |
|-----------------------|---------------------------------------------------------------------|
| **CSV 超集**           | §3~§6 任何字段都能映射到 JSON 节点, 零信息损失                       |
| **结构化分组**         | 时序/面积/功耗/拥塞按域分组, 而非平铺 30+ 个键                       |
| **多 clock 原生**      | `clocks` 用对象而非列名匹配, 避免 `_` 命名的脆弱解析                  |
| **Schema 版本化**      | 顶层 `schema_version` 字段, 未来加字段向后兼容                       |
| **一次提交, 多种类型** | 单个 JSON 可同时含 `records` + `violation_paths` + `notes`            |
| **审计元数据**         | `metadata` 段记录工具版本、Git commit、运行时长, 便于溯源             |
| **JSON Schema 校验**   | 提供 `schemas/qor_upload.v1.json` (JSON Schema Draft 2020-12)         |
| **CSV 互转**           | `scripts/csv_to_json.py` / `json_to_csv.py` 双向无损                |

### 6.5.2 顶层结构

```jsonc
{
  "schema_version": "1.0",        // 必填, 格式 "MAJOR.MINOR"
  "upload": { ... },              // 上传控制参数 (项目 / 版本 / 标签)
  "records": [ ... ],             // QoR + 功耗记录 (1..N)
  "violation_paths": [ ... ],     // 违例路径 (0..N, 可选)
  "notes": [ ... ],               // Run 备注 (0..N, 可选)
  "metadata": { ... }             // Run 元数据 (工具/Git/运行时, 可选)
}
```

### 6.5.3 完整 Schema (推荐, 一份 JSON = 一次完整 run)

```json
{
  "schema_version": "1.0",

  "upload": {
    "project_id": 1,
    "project_name": "ChipA",                  // 备用, project_id 优先
    "version": "v1.0",
    "module_name": "cpu_top",                 // 主模块 (用于快速路由, 也可放在 records[0])
    "module_id": 5,                           // 已知 module_id 时显式传入
    "mark_released": false,                   // 上传后立即发布
    "full_dir": "/scratch/runs/cpu/v1.0",     // notes 默认目录
    "release_dir": "v1.0/main/cpu",          // v5.0 发布目录
    "uploader_note": "baseline before MBFF refactor"
  },

  "records": [
    {
      "module_name": "cpu_top",
      "version": "v1.0",
      "version_description": "baseline, no MBFF",  // v5.0 (与 upload.version 区别: 这是描述)
      "full_dir": "/scratch/runs/cpu/v1.0",
      "release_dir": "v1.0/main/cpu",
      "source_file": "reports/cpu_top/qor.rpt",    // 原始报告路径, 留痕
      "comment": "baseline",

      "area": {
        "total": 12345.6,
        "combinational": 5678.9,
        "sequential": 3456.7,
        "black_box": 0.0,
        "macro": 1110.0
      },
      "timing": {
        "setup": { "wns": -0.123, "tns": -0.456, "nvp": 12 },
        "hold":  { "wns":  0.012, "tns":  0.034, "nvp":  3 }
      },
      "power": {
        "internal":   5.6,
        "switching":  3.2,
        "leakage":    1.1,
        "total":      9.9
      },
      "cells": {
        "cell_count":           8500,
        "instance_count":       9000,
        "net_count":            12000,
        "sequential_cell_count": 2100
      },
      "frequency": {
        "target":    500.0,
        "achieved":  476.2
      },
      "ratios": {                                // 一律 0-1 小数
        "mbb_ratio":          0.85,
        "clock_gating_ratio": 0.92,
        "utilization":        0.75
      },
      "congestion": {
        "h": 0.16,
        "v": 0.20,
        "b": 0.20,
        "max": 0.20                              // = max(h, v), 旧字段兼容
      },

      "clocks": {                                // 多 clock 原生 (CSV 用列名模式匹配)
        "SRAMCLK": {
          "period": 2.50,
          "wns":   -0.123,
          "tns":   -0.456,
          "path":  "/clk_div/SRAMCLK/end_reg"
        },
        "CLK_CPU": {
          "period": 1.00,
          "wns":   -0.050,
          "tns":   -0.200,
          "path":  "/reg/.../cpu_core/reg1"
        }
      },

      "extra": {                                 // 任意自定义字段
        "density": 0.78,
        "DRC_violations": 23,
        "scan_chain_count": 8,
        "tag": "baseline"
      }
    }
  ],

  "violation_paths": [
    {
      "module_name": "cpu_top",
      "timing_group": "SRAMCLK",
      "type": "setup",                           // "setup" | "hold"
      "slack": -0.020,
      "startpoint": "a_reg/CK",
      "endpoint":   "b_refg_0_/D",
      "depth": 27,
      "pure_depth": 23,
      "cell_delay": 500.0,
      "net_delay": 77.0,
      "et_slack": 9.0,
      "st_slack": -10.0,
      "st_fanin":  1, "st_fanout": 122,
      "et_fanin": 122, "et_fanout": 11,
      "clock_domain": "SRAMCLK",
      "extra": { "fanout": 3, "cell_type": "NAND2X1" }
    }
  ],

  "notes": [
    {
      "module_name": "cpu_top",
      "full_dir": "/scratch/runs/cpu/v1.0",
      "items": [
        { "category": "constraint", "item": "max_transition",  "value": "0.150",  "unit": "ns" },
        { "category": "flow",        "item": "compile_strategy", "value": "compile_ultra" },
        { "category": "result",      "item": "WNS_slack",       "value": "-0.123",  "unit": "ns" },
        { "category": "modification", "item": "关键路径优化",     "description": "retiming + 插入 buffer 解决 hold" }
      ]
    }
  ],

  "metadata": {
    "tool": {
      "name":    "Design Compiler",
      "version": "2026.03-SP4",
      "host":    "syn-server-01",
      "user":    "james.kuo"
    },
    "git": {
      "commit":  "a1b2c3d4e5f6",
      "branch":  "main",
      "tag":     "v1.0-rc1"
    },
    "runtime": {
      "wall_clock_seconds": 4523,
      "peak_memory_mb":    32768
    },
    "uploaded_at": "2026-07-30T14:23:11+08:00",
    "uploader_ip":  "10.0.0.123",
    "uploader_note": "release after MCM sign-off"
  }
}
```

### 6.5.4 字段映射 (CSV ↔ JSON)

| CSV (§3)            | JSON 路径                                    | 类型   | 单位 |
|---------------------|----------------------------------------------|--------|------|
| `module_name`       | `records[].module_name` (顶层 `upload.module_name` 也可) | string | -    |
| `version`           | `upload.version` (或 `records[].version`)     | string | -    |
| `full_dir`          | `upload.full_dir` / `records[].full_dir`     | string | -    |
| `tag`               | `records[].extra.tag`                        | string | -    |
| `area_total`        | `records[].area.total`                       | float  | um²  |
| `area_combinational`| `records[].area.combinational`               | float  | um²  |
| `area_sequential`   | `records[].area.sequential`                  | float  | um²  |
| `area_black_box`    | `records[].area.black_box`                   | float  | um²  |
| `area_macro`        | `records[].area.macro`                       | float  | um²  |
| `wns_setup`         | `records[].timing.setup.wns`                 | float  | ns   |
| `tns_setup`         | `records[].timing.setup.tns`                 | float  | ns   |
| `nvp_setup`         | `records[].timing.setup.nvp`                 | int    | 条   |
| `wns_hold`          | `records[].timing.hold.wns`                  | float  | ns   |
| `tns_hold`          | `records[].timing.hold.tns`                  | float  | ns   |
| `nvp_hold`          | `records[].timing.hold.nvp`                  | int    | 条   |
| `power_internal`    | `records[].power.internal`                   | float  | mW   |
| `power_switching`   | `records[].power.switching`                  | float  | mW   |
| `power_leakage`     | `records[].power.leakage`                    | float  | mW   |
| `power_total`       | `records[].power.total`                      | float  | mW   |
| `cell_count`        | `records[].cells.cell_count`                 | int    | -    |
| `instance_count`    | `records[].cells.instance_count`             | int    | -    |
| `net_count`         | `records[].cells.net_count`                  | int    | -    |
| `sequential_cell_count` | `records[].cells.sequential_cell_count`  | int    | -    |
| `target_frequency`  | `records[].frequency.target`                 | float  | MHz  |
| `achieved_frequency`| `records[].frequency.achieved`               | float  | MHz  |
| `mbb_ratio`         | `records[].ratios.mbb_ratio`                 | float  | 0-1  |
| `clock_gating_ratio`| `records[].ratios.clock_gating_ratio`        | float  | 0-1  |
| `utilization`       | `records[].ratios.utilization`               | float  | 0-1  |
| `congestion_h`      | `records[].congestion.h`                     | float  | 0-1  |
| `congestion_v`      | `records[].congestion.v`                     | float  | 0-1  |
| `congestion_b`      | `records[].congestion.b`                     | float  | 0-1  |
| `congestion`        | `records[].congestion.max` (旧字段)          | float  | 0-1  |
| `SRAMCLK_period`    | `records[].clocks.SRAMCLK.period`            | float  | ns   |
| `SRAMCLK_wns`       | `records[].clocks.SRAMCLK.wns`               | float  | ns   |
| `SRAMCLK_tns`       | `records[].clocks.SRAMCLK.tns`               | float  | ns   |
| `SRAMCLK_path`      | `records[].clocks.SRAMCLK.path`              | string | -    |
| `comment`           | `records[].comment`                          | string | -    |
| `source_file`       | `records[].source_file`                      | string | -    |
| 任意额外列           | `records[].extra.<key>`                      | any    | -    |

| CSV (§4 power)        | JSON 路径                              |
|-----------------------|----------------------------------------|
| `module_name`         | `records[].module_name`                |
| `version`             | `upload.version`                       |
| `power_*`             | `records[].power.*`                    |

| CSV (§5 violation)    | JSON 路径                              |
|-----------------------|----------------------------------------|
| `STARTPOINT`          | `violation_paths[].startpoint`         |
| `ENDPOINT`            | `violation_paths[].endpoint`           |
| `SLACK`               | `violation_paths[].slack`              |
| `DEPTH`               | `violation_paths[].depth`              |
| `PURE_DEPTH`          | `violation_paths[].pure_depth`         |
| `CELL_DELAY`          | `violation_paths[].cell_delay`         |
| `NET_DELAY`           | `violation_paths[].net_delay`          |
| `ET_SLACK`            | `violation_paths[].et_slack`           |
| `ST_SLACK`            | `violation_paths[].st_slack`           |
| `ST_FANIN`            | `violation_paths[].st_fanin`           |
| `ST_FANOUT`           | `violation_paths[].st_fanout`          |
| `ET_FANIN`            | `violation_paths[].et_fanin`           |
| `ET_FANOUT`           | `violation_paths[].et_fanout`          |
| (timing_group 来自文件名) | `violation_paths[].timing_group`   |
| (type 来自 metadata)  | `violation_paths[].type` (setup/hold)  |

| CSV (§6 notes)         | JSON 路径                            |
|------------------------|--------------------------------------|
| `item`                 | `notes[].items[].item`               |
| `description`          | `notes[].items[].description` (或 `value`) |
| `full_dir`             | `notes[].full_dir` (或顶层 `upload.full_dir`) |

### 6.5.5 约束与校验

#### (1) JSON Schema 校验

`schemas/qor_upload.v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://qor-recorder/schemas/qor_upload.v1.json",
  "title": "QoR Upload",
  "type": "object",
  "required": ["schema_version", "upload", "records"],
  "properties": {
    "schema_version": { "type": "string", "pattern": "^[0-9]+\\.[0-9]+$" },
    "upload": {
      "type": "object",
      "required": ["project_id", "version"],
      "properties": {
        "project_id":     { "type": "integer", "minimum": 1 },
        "project_name":   { "type": "string" },
        "version":        { "type": "string", "minLength": 1, "maxLength": 64 },
        "module_name":    { "type": "string" },
        "module_id":      { "type": "integer", "minimum": 1 },
        "mark_released":  { "type": "boolean" },
        "full_dir":       { "type": "string", "maxLength": 1024 },
        "release_dir":    { "type": "string", "maxLength": 1024 },
        "uploader_note":  { "type": "string", "maxLength": 1024 }
      }
    },
    "records": {
      "type": "array", "minItems": 1,
      "items": {
        "type": "object",
        "required": ["module_name"],
        "properties": {
          "module_name":          { "type": "string" },
          "version":              { "type": "string" },
          "version_description":  { "type": "string", "maxLength": 1024 },
          "full_dir":             { "type": "string" },
          "release_dir":          { "type": "string" },
          "source_file":          { "type": "string" },
          "comment":              { "type": "string" },
          "area":                 { "$ref": "#/$defs/area" },
          "timing":               { "$ref": "#/$defs/timing" },
          "power":                { "$ref": "#/$defs/power" },
          "cells":                { "$ref": "#/$defs/cells" },
          "frequency":            { "$ref": "#/$defs/frequency" },
          "ratios":               { "$ref": "#/$defs/ratios" },
          "congestion":           { "$ref": "#/$defs/congestion" },
          "clocks":               { "type": "object", "additionalProperties": { "$ref": "#/$defs/clock" } },
          "extra":                { "type": "object", "additionalProperties": true }
        }
      }
    },
    "violation_paths": { "type": "array" },
    "notes":           { "type": "array" },
    "metadata":        { "type": "object" }
  },
  "$defs": {
    "area": {
      "type": "object",
      "properties": {
        "total":          { "type": "number", "minimum": 0, "maximum": 1e9 },
        "combinational":  { "type": "number", "minimum": 0, "maximum": 1e9 },
        "sequential":     { "type": "number", "minimum": 0, "maximum": 1e9 },
        "black_box":      { "type": "number", "minimum": 0, "maximum": 1e9 },
        "macro":          { "type": "number", "minimum": 0, "maximum": 1e9 }
      }
    },
    "timing": {
      "type": "object",
      "properties": {
        "setup": { "$ref": "#/$defs/timing_endpoint" },
        "hold":  { "$ref": "#/$defs/timing_endpoint" }
      }
    },
    "timing_endpoint": {
      "type": "object",
      "properties": {
        "wns": { "type": "number", "minimum": -1e6, "maximum": 1e6 },
        "tns": { "type": "number", "minimum": -1e9, "maximum": 1e9 },
        "nvp": { "type": "integer", "minimum": 0, "maximum": 1e9 }
      }
    },
    "power": {
      "type": "object",
      "properties": {
        "internal":  { "type": "number", "minimum": 0, "maximum": 1e6 },
        "switching": { "type": "number", "minimum": 0, "maximum": 1e6 },
        "leakage":   { "type": "number", "minimum": 0, "maximum": 1e6 },
        "total":     { "type": "number", "minimum": 0, "maximum": 1e6 }
      }
    },
    "cells": {
      "type": "object",
      "properties": {
        "cell_count":            { "type": "integer", "minimum": 0 },
        "instance_count":        { "type": "integer", "minimum": 0 },
        "net_count":             { "type": "integer", "minimum": 0 },
        "sequential_cell_count": { "type": "integer", "minimum": 0 }
      }
    },
    "frequency": {
      "type": "object",
      "properties": {
        "target":   { "type": "number", "minimum": 0, "maximum": 1e6 },
        "achieved": { "type": "number", "minimum": 0, "maximum": 1e6 }
      }
    },
    "ratios": {
      "type": "object",
      "properties": {
        "mbb_ratio":          { "type": "number", "minimum": 0, "maximum": 1 },
        "clock_gating_ratio": { "type": "number", "minimum": 0, "maximum": 1 },
        "utilization":        { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "congestion": {
      "type": "object",
      "properties": {
        "h":   { "type": "number", "minimum": 0, "maximum": 1 },
        "v":   { "type": "number", "minimum": 0, "maximum": 1 },
        "b":   { "type": "number", "minimum": 0, "maximum": 1 },
        "max": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "clock": {
      "type": "object",
      "properties": {
        "period": { "type": "number", "minimum": 0, "maximum": 1e3 },
        "wns":    { "type": "number", "minimum": -1e3, "maximum": 1e3 },
        "tns":    { "type": "number", "minimum": -1e3, "maximum": 1e3 },
        "path":   { "type": "string", "maxLength": 1024 }
      }
    }
  }
}
```

#### (2) 服务端校验流程

服务端使用自实现的轻量校验器 ([`services/json_upload.py`](../services/json_upload.py) 的
`validate_upload_json()`), **不依赖 `jsonschema` 第三方包**, 避免给部署环境增加
新依赖. 校验逻辑与上面的 schema 语义等价, 但错误路径用 JSONPath 字符串
(如 `$.records[3].module_name`) 返回.

```
1. 收到 JSON
2. 校验顶层结构: 必须是对象, 且 schema_version / upload 必填
3. 校验 schema_version: 必须是 1.x 格式, 不支持则 400
4. 校验 upload 必填字段 (project_id 整数 >= 1, version 非空字符串 <= 64 字符)
5. 校验 records[] / violation_paths[] / notes[] 结构 (若提供)
   - 每条 record.module_name 必填
   - violation_paths 必须有 startpoint/endpoint/slack/timing_group
   - notes[].items 不能为空
6. 业务校验 (在路由层):
   - can_edit_project(user, project_id) - 权限
   - check_project_writable() - 项目级数据锁
   - check_data_lock() - 模块级数据锁
7. 写入数据库 (复用 save_records_to_db / save_violations_to_db / save_notes_to_db)
8. 触发告警 (wns_setup < 0 → setup 告警)
9. 返回 {ok, saved, updated, skipped, record_ids, alerts_triggered, ...}
```

校验失败示例 (400):
```json
{
  "error": "必填, 字符串",
  "path": "$.records[0].module_name"
}
```

#### (3) 与 CSV 的互转

`scripts/csv_to_json.py` (示例, 反向也类似):

```python
import csv, json, sys, argparse
from pathlib import Path

CLOCK_PATTERN_RE = __import__('re').compile(
    r'^(.+?)_(hold_wns|hold_tns|hold_path|period|wns|tns|path)$',
    __import__('re').IGNORECASE,
)

def csv_to_json(csv_path: Path, project_id: int, version: str,
                full_dir: str = None, release_dir: str = None) -> dict:
    """CSV §3 (qor 宽表) → JSON §6.5"""
    with open(csv_path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    records = []
    for row in rows:
        rec = {
            "module_name": row["module_name"],
            "version":     version,
            "full_dir":    full_dir or row.get("full_dir"),
            "release_dir": release_dir or row.get("release_dir"),
            "comment":     row.get("comment"),
            "source_file": str(csv_path),
            "area": {}, "timing": {"setup": {}, "hold": {}}, "power": {},
            "cells": {}, "frequency": {}, "ratios": {}, "congestion": {},
            "clocks": {}, "extra": {},
        }
        for k, v in row.items():
            if v == "" or v is None: continue
            lk = k.lower().replace(" ", "_")
            m = CLOCK_PATTERN_RE.match(k)
            if m:
                clk, suf = m.group(1), m.group(2).lower()
                rec["clocks"].setdefault(clk, {})[suf] = float(v) if "path" not in suf else v
                continue
            # area
            if lk.startswith("area_"):
                rec["area"][lk[5:]] = float(v)
            # timing
            elif lk.endswith("_setup") and lk.startswith(("wns_","tns_","nvp_")):
                rec["timing"]["setup"][lk[:-6]] = float(v) if "wns" in lk or "tns" in lk else int(v)
            elif lk.endswith("_hold") and lk.startswith(("wns_","tns_","nvp_")):
                rec["timing"]["hold"][lk[:-5]] = float(v) if "wns" in lk or "tns" in lk else int(v)
            # power
            elif lk.startswith("power_"):
                rec["power"][lk[6:]] = float(v)
            # cells
            elif lk in ("cell_count","instance_count","net_count","sequential_cell_count"):
                rec["cells"][lk] = int(v)
            # frequency
            elif lk in ("target_frequency","achieved_frequency"):
                rec["frequency"][lk] = float(v)
            # ratios
            elif lk in ("mbb_ratio","clock_gating_ratio","utilization"):
                v2 = float(v);  rec["ratios"][lk] = v2/100 if v2 > 1 else v2
            # congestion
            elif lk in ("congestion_h","congestion_v","congestion_b","congestion"):
                v2 = float(v);  rec["congestion"][lk[11:] or "max"] = v2/100 if v2 > 1 else v2
            else:
                rec["extra"][k] = v
        records.append(rec)
    return {
        "schema_version": "1.0",
        "upload": {
            "project_id":  project_id,
            "version":     version,
            "full_dir":    full_dir,
            "release_dir": release_dir,
        },
        "records": records,
    }

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--full-dir")
    p.add_argument("--release-dir")
    p.add_argument("--output", default="-")
    args = p.parse_args()
    data = csv_to_json(Path(args.csv), args.project_id, args.version,
                      args.full_dir, args.release_dir)
    out = sys.stdout if args.output == "-" else open(args.output, "w", encoding="utf-8")
    json.dump(data, out, ensure_ascii=False, indent=2)
    out.write("\n")
```

#### (4) 命令行转换

```bash
# CSV → JSON
python scripts/csv_to_json.py qor.csv --project-id 1 --version v1.0 \
    --full-dir /scratch/runs/v1.0 --release-dir v1.0/main/cpu \
    -o run.json

# JSON → CSV (宽表, 仅 records[0])
python scripts/json_to_csv.py run.json -o qor.csv

# JSON → 多 CSV (records/violation_paths/notes 各一个)
python scripts/json_to_csv.py run.json --split
# 产出: run.qor.csv  run.violations.csv  run.notes.csv
```

### 6.5.6 提交方式

#### (1) API: `POST /api/v1/qor/upload` (JSON body)

**请求**:
```bash
curl -X POST http://localhost:5000/api/v1/qor/upload \
    -H "X-API-Key: qor_xxxxxxxx" \
    -H "Content-Type: application/json" \
    -d @run.json
```

**请求头**:
| 头 | 必填 | 说明 |
|----|------|------|
| `X-API-Key` | 是 | API Key, scope 必须含 `upload` |
| `Content-Type` | 是 | `application/json` |

**请求体**: 见 §6.5.3 (一个 JSON 对象, 含 `schema_version` / `upload` / `records` / `violation_paths` / `notes` / `metadata`).

**响应 200**:
```json
{
  "ok": true,
  "schema_version": "1.0",
  "saved": 1,
  "updated": 0,
  "skipped": 0,
  "violation_paths_saved": 150,
  "violation_paths_skipped": 0,
  "notes_saved": 4,
  "notes_skipped": 0,
  "record_ids": [23],
  "alerts_triggered": 2,
  "alerts": [...],
  "metadata_recorded": true,
  "uploaded_by": "james.kuo"
}
```

| 字段 | 含义 |
|------|------|
| `saved` | 新建 QorRecord 数 |
| `updated` | 覆盖已有 QorRecord 数 (按 `module_id+version` 匹配) |
| `skipped` | 字段缺失/数值越界导致跳过 |
| `violation_paths_saved` / `violation_paths_skipped` | 违例路径保存/跳过计数 |
| `notes_saved` / `notes_skipped` | Run 备注保存/跳过计数 |
| `record_ids` | 受影响 QorRecord 的 id 列表 (按 record 顺序) |
| `alerts_triggered` | 触发的告警规则数 |
| `metadata_recorded` | `metadata` 段是否被解析 (当前仅解析, 不入库) |

**错误响应**:

| 状态码 | 含义 | 响应字段 |
|--------|------|----------|
| 400 | JSON 校验失败 | `{"error": "...", "path": "$.records[3].module_name"}` |
| 401 | 缺/无效 X-API-Key 或 session | `{"error": "..."}` |
| 403 | 无项目编辑权限 / 项目已锁 (`must_change_password=True`) | `{"error": "..."}` |
| 404 | `project_id` 不存在 | `{"error": "..."}` |
| 409 | 模块/项目被他人锁定 | `{"error": "...", "lock": {...}}` |
| 500 | 服务端异常 (DB 错误等) | `{"error": "...", "stage": "records\|violation_paths\|notes"}` |

`path` 字段使用 JSONPath 语法 (`$.records[3].module_name`), 客户端可直接定位出错的字段.

**幂等性**: 同一份 JSON 重复提交, 第 1 次 `saved=1`, 后续 `updated=1` (按 `module_id+version` 匹配更新). `record_ids` 始终返回受影响 QorRecord 的最新 id.

#### (2) upload_qor.sh --json 模式 (推荐 DC 流程)

[`scripts/upload_qor.sh`](../scripts/upload_qor.sh) 已支持 `--json` 模式, 内部自动调用 `csv_to_json.py` 转 JSON 后发到新端点:

```bash
# QoR 数据
./upload_qor.sh 1 v1.0 qor_report.csv --json

# QoR + 立即发布
./upload_qor.sh 1 v1.0 qor_report.csv qor --json --release

# QoR + 指定 release_dir
./upload_qor.sh 1 v1.0 qor_report.csv --json --release-dir v1.0/main/cpu

# Violation paths (文件名建议 SRAMCLK_violations.csv, 自动提取 timing_group)
./upload_qor.sh 1 v1.0 SRAMCLK_violations.csv violation --json

# Notes (必须 --module-name)
./upload_qor.sh 1 v1.0 run_notes.csv notes --json --module-name cpu_top --full-dir "$PWD"

# 调试: 保留转换后的 JSON 文件
./upload_qor.sh 1 v1.0 qor.csv --json --keep-json /tmp/run.json
```

底层流程:
1. `csv_to_json.py` 把 CSV 转换为 §6.5 JSON
2. `upload_qor.sh` 注入 `upload.project_id` / `mark_released` / `module_id` / `full_dir` / `release_dir`
3. POST `/api/v1/qor/upload` (Content-Type: application/json)
4. 解析响应, 输出 `saved/updated/notes/violations/record_ids/alerts` 摘要

> **推荐**: DC 流程默认使用 `--json`. 旧 multipart 入口 (`/api/v1/upload`) 保持兼容, 旧 Makefile 无需修改.

#### (3) Makefile 集成 (推荐)

```makefile
# DC 综合流程结束: 一份 run.json 搞定全部数据
UPLOAD_URL = https://qor.example.com/api/v1/qor/upload
UPLOAD_AUTH = X-API-Key:$(shell cat ~/.qor_api_key)

upload-run:
	@echo "[INFO] 上传 run.json → $(UPLOAD_URL)"
	@curl -fsS -X POST $(UPLOAD_URL) \
	    -H "$(UPLOAD_AUTH)" \
	    -H "Content-Type: application/json" \
	    -d @run.json
	@echo "[OK] run 上传完成"

upload-run-release:
	@jq '.upload.mark_released = true' run.json > run.release.json
	@curl -fsS -X POST $(UPLOAD_URL) \
	    -H "$(UPLOAD_AUTH)" \
	    -H "Content-Type: application/json" \
	    -d @run.release.json
	@rm -f run.release.json
```

#### (4) 兼容 CSV 入口 (旧 Makefile 仍可工作)

```bash
# 单文件: CSV → multipart/form-data → /api/v1/upload (旧入口)
# 多类型: 4 个 CSV → 4 次 form 上传 (旧入口)
# 新 Makefile 建议: CSV → csv_to_json.py → run.json → JSON 上传
```

### 6.5.7 优点 vs CSV

| 维度       | CSV (旧)                       | JSON (新, §6.5)                       |
|------------|--------------------------------|---------------------------------------|
| **多 clock** | 列名 `_` 模式匹配, 脆弱           | `clocks` 对象, 原生支持, 任意字段       |
| **结构化**   | 平铺 30+ 列, 难读                | 按域分组 (area/timing/power/...), 自文档 |
| **多类型**   | 4 个文件 + 4 次上传               | 1 个文件, 1 次上传, 事务一致            |
| **元数据**   | 只能在 CSV 旁附 README            | `metadata` 段结构化, Git/工具/运行时    |
| **校验**     | 服务端按列名容错                  | JSON Schema 强校验, 错误带字段路径      |
| **扩展性**   | 加列 (需改 schema)                | 加 `extra.*` 任意嵌套, 不改 schema      |
| **审计**     | 文件名 + uploader 备注            | `metadata` + `uploader_note` + 原始 JSON 留档 |
| **互转**     | 难                               | `csv_to_json.py` / `json_to_csv.py` 无损 |
| **CI 友好**  | 中等 (需要 base64 等)             | 强 (直接 `curl -d @run.json`)          |
| **人类可读** | 高                                | 高 (配合 `jq` 工具)                     |

### 6.5.8 迁移路径 (CSV → JSON)

#### 阶段 1: 双轨并行 (1-2 周)
- 上传接口同时接受 CSV (`/api/v1/upload`) 和 JSON (`/api/v1/qor/upload`)
- Makefile 默认 CSV, 提供 `make convert-and-upload` 走 JSON
- 工具: `csv_to_json.py` 已实现

#### 阶段 2: 切换默认 (2-4 周)
- 新项目/新模块默认用 JSON (`make upload-run`)
- 旧项目保留 CSV 路径, 1:1 兼容

#### 阶段 3: 弃用 CSV (4 周后, 可选)
- 文档标记 CSV 弃用
- 服务端仍接受 CSV 但日志 warning
- 长期计划: CSV 接口进入 maintenance mode

### 6.5.9 完整示例文件

完整样本: [`examples/qor_run.v1.json`](../examples/qor_run.v1.json) (随项目发布).
Schema 文件: [`schemas/qor_upload.v1.json`](../schemas/qor_upload.v1.json).

### 6.5.10 FAQ

**Q: 现有 CSV 数据会自动转换吗?**
A: 不会自动. 但提供 `csv_to_json.py` 工具, 一行命令 `python csv_to_json.py xxx.csv --project-id 1 --version v1.0 > run.json` 即可. 历史 CSV 上传路径保持不变.

**Q: JSON 比 CSV 大很多, 慢吗?**
A: 单 run JSON ≈ 5-10 KB (无 violation_paths), 加违例后 50-500 KB. 仍远小于 1 MB, 远低于 `multipart/form-data` 上传极限. JSON 解析 < 50ms.

**Q: 必须把 clocks 重组成对象吗?**
A: 推荐. 也可以平铺为 `extra_fields.SRAMCLK_wns` 等 (沿用 CSV 兼容), 但失去结构化优势.

**Q: extra.* 的键名有约束吗?**
A: 无. 任意 JSON 值. 服务端会存入 `extra_fields` JSON 字段, 详情页可查看.

**Q: 多模块 (一次提交多条 records) 会创建多个 run 吗?**
A: 会的. 数组中每条 record 创建一个独立的 QorRecord, 但共享 `upload.version` (若 record 自带 version, 则以 record 为准).

**Q: 缺省时 version / full_dir 取哪个?**
A: 优先级: `record.version` > `upload.version`, `record.full_dir` > `upload.full_dir`. 顶层 `upload` 提供"批次默认值", 降低重复.

---

## 6.6 DC 综合报告 JSON 格式 (v5.0+, 直传模式)

> 上游工具 (DC/Genus/Tempus 等) 直接产出的结构化 JSON, 端点 `/api/v1/qor/upload`
> 自动识别 + 转换 + 入库. **不再需要 `dc_report_to_json.py` 作为中间步骤**.
> upload_qor.sh 在 `--json` 模式下自动识别该格式 (顶层含 `top_module` + `timing`/`area`/`misc`).
>
> 关键设计:
> - `project_id` / `version` **走 URL query**, 不进入 JSON, 与 §6.5 CSV 上传保持一致
> - `module` 来自 DC 报告的 `top_module` (无须指定)
> - `register_count` 来自 `misc.fgcg.total_flops`
> - 完整 DC 报告 JSON 存到 `QorRecord.raw_dc_report`, Dashboard 表格视图直接渲染
> - 1 个 DC 报告 = 1 条 QorRecord, 多 scenarios / path_groups 存到 `extra.scenarios` 审计

### 6.6.1 顶层结构

```json
{
  "scheme_version": 1,            // 整数 (上游固定)
  "generated_at": "ISO 8601",
  "stage": "Synthesis",           // 或 PnR / STA / Route
  "top_module": "modulea_t",      // → module (自动)
  "run": {"directory": "cfg1_rundir"},   // → full_dir

  "timing": {
    "default": {                  // mandatory
      "scenarios": {
        "<scenario>": {           // 如 "tt0p6v_tt"
          "path_groups": {
            "<path_group>": {     // 如 "FUNCCLK" / "SRAMCLK"
              "WNS": -10, "TNS": 0, "NVP": 0,
              "Clk_Period": 1000, "LoL": 40
            }
          }
        }
      }
    },
    "final": {...}                // optional, 优化后
  },

  "area": {
    "tile": {
      "cell_count": {total, sequential, combinational, ram, macro},
      "area":       {total, total_cell, sequential, ...}
    },
    "block": {"<block_name>": {...}}
  },

  "misc": {
    "fgcg": {gated_flops, not_gated_flops, total_flops, clock_gating_cells},
    "mbb_ratio": "0.00%",
    "utilization": 0.4254,
    "vt_ratio": {...},
    "flop_count": {...},
    "congestion": {summary_lines[], both_dirs_percentage},
    "no_clock": {count}
  }
}
```

### 6.6.2 字段映射 (DC 报告 → QorRecord)

**核心原则: 1 个 DC 报告 = 1 个 run = 1 条 QorRecord.** run 内的多个 scenarios × path_groups
全部进 `record.extra.scenarios` 审计; QorRecord 扁平字段 (wns/tns/nvp) 取 `timing.default` 的
worst-case 聚合.

| DC 上游字段 | QorRecord 字段 | 说明 |
|-------------|----------------|------|
| `top_module` | `module.name` (自动创建/查找) | **无须 `--module-name` 覆盖** |
| `run.directory` | `qor_records.full_dir` | run 目录, 1 run = 1 record |
| `area.tile.area.total` | `qor_records.area_total` | tile 视角整 chip 面积 |
| `area.tile.area.sequential` | `area_sequential` | |
| `area.tile.area.macro` | `area_macro` + `area_black_box` | DC 的 macro 等价 §6.5 black_box |
| `area.tile.cell_count.total` | `cell_count` | |
| `area.tile.cell_count.sequential` | `sequential_cell_count` | |
| `area.tile.cell_count.combinational` | `instance_count` | |
| `timing.default.scenarios[*].path_groups[*].WNS` | `wns_setup` (QorRecord) | **min of all (scenario, path_group)** |
| `timing.default.scenarios[*].path_groups[*].TNS` | `tns_setup` | **min of all** |
| `timing.default.scenarios[*].path_groups[*].NVP` | `nvp_setup` | **sum of all** |
| `misc.utilization` | `utilization` | 0-1 小数 |
| `misc.mbb_ratio` | `mbb_ratio` | 0-1 小数 |
| `misc.fgcg.gated_flops.percentage` | `clock_gating_ratio` | 0-1 小数 |
| `misc.congestion.both_dirs_percentage` | `congestion_b` | 0-1 小数 |
| `misc.congestion.summary_lines` (H/V) | `congestion_h` / `congestion_v` | 正则解析 "H/V routing: ... (X%)" |
| **`misc.fgcg.total_flops`** | **`register_count`** | **寄存器数** (DC 原始值, 无折算) |
| 完整 DC JSON 字符串 | `qor_records.raw_dc_report` | 透传, Dashboard 表格视图渲染用 |
| `timing.default.scenarios[*].path_groups[*]` | `extra_fields.scenarios` | 全量审计 |
| `timing.final` / `area.block` / `misc.*` | `extra_fields.timing_final/blocks/misc_*` | 摘要 + 全量 |

### 6.6.3 上传协议

```
POST /api/v1/qor/upload?project_id=<id>&version=<v>
Header: X-API-Key: qor_xxxxxxxx
Content-Type: application/json
Body:    { 完整 DC 报告 JSON 对象, 顶层含 top_module/timing/area/misc ... }
```

**示例**:

```bash
curl -X POST "http://localhost:5000/api/v1/qor/upload?project_id=1&version=v1.0" \
     -H "X-API-Key: qor_xxxxxxxx" \
     -H "Content-Type: application/json" \
     --data @examples/dc_report.v1.json
```

**响应** (200 OK):

```json
{
  "ok": true,
  "format": "dc_report",
  "module_name": "modulea_t",
  "schema_version": "1.0",
  "record_ids": [42],
  "saved": 1,
  "updated": 0,
  "skipped": 0,
  "alerts_triggered": 0,
  "uploaded_by": "admin"
}
```

**错误**:

| HTTP | 场景 | 错误消息示例 |
|------|------|--------------|
| 400 | 缺 `project_id` query 参数 | `缺少 project_id (通过 ?project_id=N 或 DC 报告内嵌 upload.project_id 提供)` |
| 400 | 缺 `version` query 参数 | `缺少 version` |
| 400 | 顶层不含 `top_module` | `DC 报告缺 top_module 顶层字段` |
| 401 | API Key 无效/撤销 | `API Key 无效或已撤销` |
| 403 | 无项目访问权限 | `无项目访问权限` |
| 404 | project_id 不存在 | `项目 999 不存在` |

### 6.6.4 record 生成粒度 (1 run = 1 record)

```yaml
# 输入: 1 个 DC 报告 (1 个 run)
scenarios:
  tt0p6v_tt:           # scenario #1
    path_groups:
      FUNCCLK:  {WNS: -10, TNS:   0, NVP:  0, period: 1000, lol: 40}
      SRAMCLK:  {WNS: -25, TNS: -120, NVP: 14, period:  800, lol: 38}
  ss0p81v_ss:          # scenario #2
    path_groups:
      FUNCCLK:  {WNS: -50, TNS: -800, NVP: 50, period: 1200, lol: 42}
```

→ **1 条 record 入库**:
- `module.name` = `modulea_t` (DC.top_module)
- `full_dir` = `cfg1_rundir` (DC.run.directory)
- `register_count` = `1218349` (DC.misc.fgcg.total_flops)
- `wns_setup` = `min(-10, -25, -50)` = **-50** (worst-case)
- `tns_setup` = `min(0, -120, -800)` = **-800**
- `nvp_setup` = `sum(0, 14, 50)` = **64**
- `raw_dc_report` = 完整 DC 报告 JSON 字符串 (Dashboard 表格视图用)
- `extra_fields.scenarios` = 全量审计 (scenario × path_group)

**为什么这样设计:**
- QorRecord 主键 `(module_id, version, full_dir)` 一个 run 只占一行, 避免 dashboard 出现
  同一 run 的 N 条"伪重复"行
- QoR 工程师关注的是"这个 run 在所有 corner/clock 下最差多少" → 扁平字段直接给答案
- 想看完整 DC 报告内容 → 走 `raw_dc_report` (Dashboard 表格视图默认呈现)
- 想看单一 scenario / clock 细节 → 走 `extra_fields.scenarios[scenario][path_group]`

### 6.6.5 CLI 一键上传

```bash
export QOR_API_KEY=qor_xxxxxxxx

# 1) 直接上传 (推荐, 一条命令完成)
./scripts/upload_qor.sh 1 v1.0 examples/dc_report.v1.json --json

# 2) 上传并立即标记为已发布
./scripts/upload_qor.sh 1 v1.0 examples/dc_report.v1.json --json --release

# 3) 覆盖 release_dir (默认 = full_dir = run.directory)
./scripts/upload_qor.sh 1 v1.0 examples/dc_report.v1.json --json \
    --release --release-dir v1.0/main/cpu_core

# 4) 调试: --keep-json 保留转换后的 §6.5 JSON
./scripts/upload_qor.sh 1 v1.0 examples/dc_report.v1.json --json \
    --keep-json /tmp/converted.json
```

`upload_qor.sh` 在 `--json` 模式下自动检测:
- 顶层含 `top_module` + `timing` + `area` + `misc` → DC 报告, 直接转发
- 顶层含 `schema_version` + `records` → §6.5 JSON, 直接转发
- 其它 `.csv` → 调 `csv_to_json.py` 转换

### 6.6.6 Dashboard 表格视图 (v5.0+ 默认)

Dashboard 在原"图表区域"之前默认展示 **DC 报告表格视图**:

**① DC 报告内容** (顶部对比表, 行=字段路径, 列=选中的 run):
- 行按 `JSON 路径` 排序: `$.top_module`, `$.timing.default.scenarios.tt0p6v_tt.path_groups.FUNCCLK.WNS` ...
- 列是用户在底部勾选要对比的 run
- 单元格值: 数字按科学计数 / 4位有效数字格式化; 字符串 > 80 字符截断
- 与基准 run 比较, **变化 ≥5% 标红/标绿** (WNS/TNS/NVP/area/power 上升=变差, frequency/clock_gating 上升=变好)

**② 数据集** (底部 run 列表, 多选):
- 列: 选择 / ID / 项目 / 模块 / 版本 / 目录 / **寄存器数** / WNS / TNS / 总面积 / 总 cell / 操作
- 复选框直接控制顶部对比表列
- "全选当前列表" / "清空选择" 按钮
- "设为基准" 按钮: 选定后, 顶部表格的变化标注以此为基准
- 表格列头点击排序 (复用 TBLX 排序器)

**导出**: "下载 CSV" 按钮把当前选中的 run × 所有字段路径导出为 Excel 友好的 CSV (含 BOM).

### 6.6.7 端到端测试

[`test_e2e_raw_dc_upload.py`](../test_e2e_raw_dc_upload.py) 覆盖:
- converter 校验/转换 (1 DC 报告 → 1 record, 聚合自 2 scenarios × 3 path_groups)
- `register_count = misc.fgcg.total_flops` 字段精确断言
- `raw_dc_report` 字段存储完整 DC JSON (含 top_module/timing/area/misc)
- `Module` 按 `top_module` 自动创建
- 聚合正确性 (WNS=min, TNS=min, NVP=sum)
- clocks 字段正确性 (取第一个 scenario 的 path_groups)
- extra.scenarios 全量审计 (2 scenarios × 3 path_groups)
- 幂等性 (re-upload: saved=0, updated=1)
- 错误处理: 缺 project_id / version / top_module 全部 400

[`test_e2e_dc_upload.py`](../test_e2e_dc_upload.py) — 旧版走 `dc_report_to_json.py` 的端到端测试, 保留作为参考.

### 6.6.8 完整示例

[`examples/dc_report.v1.json`](../examples/dc_report.v1.json) — 一个完整的 DC 综合报告
(含 2 scenarios × 3 path_groups, 含 timing.final, area.block 2 个子模块, misc 全字段).
直传 + Dashboard 表格视图后入库为 **1 条** QorRecord, `raw_dc_report` 字段保存完整 DC JSON.

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
| `sub_path` | 子目录（多 variant / 多 sub-run 区分）           | `main` / `variant_a` / `variant_b`    |
| `run_name` | 本次 run 的具体名称（一个 base_dir 内唯一）     | `cpu_core_baseline` / `cpu_core_cfg1` |

**示例**：
```
v1.0/main/cpu_core_baseline
v1.0/variant_a/cpu_core_baseline
v1.0/variant_b/cpu_core_cfg1
2026Q3_w2/variant_c/lsu_opt_speed
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
    { "id": 124, "full_dir": "v1.0/variant_a/...", "area_total": 12400.1 },
    { "id": 125, "full_dir": "v1.0/variant_b/...", "area_total": 12200.5 }
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
