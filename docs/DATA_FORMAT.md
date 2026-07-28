# QoR Recorder 数据提交规范 v4.0

> 本文档定义每次 "run"（综合运行）需要提交的数据格式、提交方式（脚本 / API / Makefile / Demo 脚本）以及覆盖与关联策略。
> 适用于：CSV 文件作者、Makefile 集成者、API 调用方、Demo 数据生成者。

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
- 同一 module 可有多个 run（不同时期、不同版本），用于趋势对比

---

## 2. 提交方式

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

### 19.3 权限

| 角色     | 权限                                  |
|----------|---------------------------------------|
| admin    | 所有项目所有操作                      |
| owner    | 项目内所有操作                        |
| editor   | 提交 / 修订                            |
| viewer   | 只读                                  |
| release  | 仅查看已发布数据（看不到未审核 run）   |

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

**文档版本**: 4.0
**最后更新**: 2026-07-28（v4.0: 按项目分库 + 多后端切换 + MongoDB dual-write）
**维护**: QoR Recorder Team
