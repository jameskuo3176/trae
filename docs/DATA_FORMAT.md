# QoR Recorder 数据格式规范 v1.0

> 本文档定义每次 "run"（综合运行）必须遵循的标准数据格式。
> 所有上传的 CSV、API 提交的 JSON、命令行工具输入均应遵循此规范。

---

## 1. 概念层级

```
Project（项目）
  └─ Module（模块, 例: cpu_top, sram_ctrl）
       └─ QorRecord（一次综合运行的结果, 即"一个 run"）
              └─ ViolationPath[]（违例路径列表, 0..N 条）
```

- 一个 **run** = 一条 `QorRecord` 记录
- 一个 run 关联到一个 module 和一个 version（版本/commit/日期标签）
- 同一 module 可有多个 run（不同时期、不同版本的综合结果），用于趋势对比

---

## 2. 上传文件结构（推荐）

每次综合结束后上传一个 CSV 即可：

```
<run_name>.csv      # QoR 指标（必需）
violations/*.csv    # 违例路径文件（可选, 0..N 个）
```

CSV 文件使用**宽表**格式：一行 = 一个 run 的所有指标。

### 2.1 QoR 指标 CSV 列定义

| 字段 | 类型 | 单位 | 必填 | 说明 |
|------|------|------|------|------|
| **module_name** | string | - | ✅ | 模块名, 必须在项目中已存在 |
| **version** | string | - | ✅ | 版本标识, 例: `v1` / `20260301_1430` / `commit_a1b2c3` |
| **area_total** | float | um² | ⭕ | 总面积 |
| **area_combinational** | float | um² | ⭕ | 组合逻辑面积 |
| **area_sequential** | float | um² | ⭕ | 寄存器面积 |
| **area_black_box** | float | um² | ⭕ | 黑盒面积 |
| **area_macro** | float | um² | ⭕ | 宏单元面积 |
| **wns_setup** | float | ns | ⭕ | Setup Worst Negative Slack, **负值=违例** |
| **tns_setup** | float | ns | ⭕ | Setup Total Negative Slack, **负值=违例** |
| **nvp_setup** | int | 条 | ⭕ | Setup 违例路径数 |
| **wns_hold** | float | ns | ⭕ | Hold WNS, **负值=违例** |
| **tns_hold** | float | ns | ⭕ | Hold TNS, **负值=违例** |
| **nvp_hold** | int | 条 | ⭕ | Hold 违例路径数 |
| **power_internal** | float | mW | ⭕ | 内部功耗 |
| **power_switching** | float | mW | ⭕ | 翻转功耗 |
| **power_leakage** | float | mW | ⭕ | 漏电功耗 |
| **power_total** | float | mW | ⭕ | 总功耗 = internal + switching + leakage |
| **cell_count** | int | - | ⭕ | 标准单元数 |
| **instance_count** | int | - | ⭕ | 实例数（含宏） |
| **net_count** | int | - | ⭕ | 线网数 |
| **sequential_cell_count** | int | - | ⭕ | 寄存器数量 |
| **target_frequency** | float | MHz | ⭕ | 目标频率 |
| **achieved_frequency** | float | MHz | ⭕ | 实际频率 = 1000 / (\|wns_setup\| + 1/period) |
| **mbb_ratio** | float | 0-1 | ⭕ | Multi-Bit Flip-Flop 合并率, 上传 0.85 表示 85% |
| **clock_gating_ratio** | float | 0-1 | ⭕ | 时钟门控覆盖率, 上传 0.92 表示 92% |
| **utilization** | float | 0-1 | ⭕ | 布局利用率, 上传 0.75 表示 75% |
| **congestion** | float | 0-1 | ⭕ | 拥塞指数, 越接近 1 越拥塞 |
| **source_file** | string | - | ❌ | 原始报告路径, 便于溯源 |
| **comment** | string | - | ❌ | 备注, 例: "baseline after APR fix" |

> **比例字段说明**: `mbb_ratio` / `clock_gating_ratio` / `utilization` / `congestion` 一律以 **0-1 之间的小数** 上传, 系统会自动乘 100 显示为百分比。

> **违例路径** 不在此 CSV 中, 通过单独上传违例路径 CSV 自动关联到对应 run（按 module + version 匹配）。

### 2.2 CSV 示例

```csv
module_name,version,area_total,area_combinational,area_sequential,area_black_box,area_macro,wns_setup,tns_setup,nvp_setup,wns_hold,tns_hold,nvp_hold,power_internal,power_switching,power_leakage,power_total,cell_count,instance_count,net_count,sequential_cell_count,target_frequency,achieved_frequency,mbb_ratio,clock_gating_ratio,utilization,congestion,source_file,comment
cpu_top,v1,12345.6,5678.9,3456.7,2100.0,1110.0,-0.123,-0.456,12,0.012,0.034,3,5.6,3.2,1.1,9.9,8500,9000,12000,2100,500.0,476.2,0.85,0.92,0.75,0.18,/proj/cpu/reports/syn/20260301.rpt,baseline
cpu_top,v2,12100.3,5500.2,3400.1,2100.0,1100.0,-0.05,-0.1,2,0.015,0.04,4,5.5,3.1,1.0,9.6,8400,8900,11800,2050,500.0,526.3,0.87,0.93,0.76,0.15,/proj/cpu/reports/syn/20260315.rpt,after RTL opt
sram_ctrl,v1,5678.9,2345.6,1890.3,1000.0,443.0,0.05,0,0,0.01,0,0,2.1,1.0,0.4,3.5,3200,3500,4500,890,200.0,200.0,0.78,0.88,0.65,0.12,/proj/sram/reports/syn/20260301.rpt,first run
```

---

## 3. API JSON 格式（程序化提交）

调用 `POST /api/v1/qor/upload` 时, Body 格式：

```json
{
  "project_id": 1,
  "module_id": 5,
  "data": [
    {
      "module_name": "cpu_top",
      "version": "v1",
      "area_total": 12345.6,
      "area_combinational": 5678.9,
      "area_sequential": 3456.7,
      "area_black_box": 2100.0,
      "area_macro": 1110.0,
      "wns_setup": -0.123,
      "tns_setup": -0.456,
      "nvp_setup": 12,
      "wns_hold": 0.012,
      "tns_hold": 0.034,
      "nvp_hold": 3,
      "power_internal": 5.6,
      "power_switching": 3.2,
      "power_leakage": 1.1,
      "power_total": 9.9,
      "cell_count": 8500,
      "instance_count": 9000,
      "net_count": 12000,
      "sequential_cell_count": 2100,
      "target_frequency": 500.0,
      "achieved_frequency": 476.2,
      "mbb_ratio": 0.85,
      "clock_gating_ratio": 0.92,
      "utilization": 0.75,
      "congestion": 0.18,
      "source_file": "/proj/cpu/reports/syn/20260301.rpt",
      "comment": "baseline"
    }
  ]
}
```

支持多 run 一次性提交（同 module 不同 version）：

```json
{
  "project_id": 1,
  "data": [
    { "module_name": "cpu_top", "version": "v1", "wns_setup": -0.123, ... },
    { "module_name": "cpu_top", "version": "v2", "wns_setup": -0.05,  ... }
  ]
}
```

---

## 4. 字段约束与校验

| 约束 | 规则 |
|------|------|
| 必填字段缺失 | 整行拒绝, 返回错误信息 |
| 模块不存在 | 自动尝试按 module_name 创建（若当前用户有权限）, 失败则拒绝 |
| 数值类型 | 接受 int/float 字符串, 自动 `parseFloat`, 失败置 null |
| 比例字段 | 接受 0-100 的整数(视为百分比) 或 0-1 的小数, 系统内部统一存为小数 |
| `power_total` | 若未提供, 自动 `internal + switching + leakage` 填充 |
| 时序违例判定 | `wns_setup < 0` 或 `tns_setup < 0` 或 `nvp_setup > 0` → 自动触发违例事件 |
| **版本号相同** | (module_name, version) 重复时, **覆盖更新**已有记录 |
| `extra_fields` | CSV 中未列出的自定义字段会进入 `extra_fields` JSON |

---

## 5. 违例路径文件格式

每个违例路径 CSV 文件代表一个 timing group（如 SRAMCLK）的违例路径列表。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| timing_group | string | ✅ | 从文件名提取（去掉 `.csv`） |
| startpoint | string | ✅ | 起始点（寄存器/端口） |
| endpoint | string | ✅ | 终止点（寄存器/端口） |
| slack | float | ✅ | 该路径 slack (ns) |
| clock | string | ⭕ | 时钟域 |
| path_group | string | ⭕ | path group 名 |

文件名约定: `<timing_group>.csv`（如 `SRAMCLK.csv`），文件名即 `timing_group` 值。

---

## 6. 完整 Run 对象（API 返回格式）

```json
{
  "id": 123,
  "module_id": 5,
  "module_name": "cpu_top",
  "project_name": "MyChip",
  "version": "v1",
  "tag": "v1",
  "comment": "baseline after APR fix",
  "full_dir": "/proj/cpu/runs/20260301",
  "area_total": 12345.6,
  "area_combinational": 5678.9,
  "area_sequential": 3456.7,
  "area_black_box": 2100.0,
  "area_macro": 1110.0,
  "wns_setup": -0.123,
  "tns_setup": -0.456,
  "nvp_setup": 12,
  "wns_hold": 0.012,
  "tns_hold": 0.034,
  "nvp_hold": 3,
  "power_internal": 5.6,
  "power_switching": 3.2,
  "power_leakage": 1.1,
  "power_total": 9.9,
  "cell_count": 8500,
  "instance_count": 9000,
  "net_count": 12000,
  "sequential_cell_count": 2100,
  "target_frequency": 500.0,
  "achieved_frequency": 476.2,
  "mbb_ratio": 0.85,
  "clock_gating_ratio": 0.92,
  "utilization": 0.75,
  "congestion": 0.18,
  "source_file": "/proj/cpu/reports/syn/20260301.rpt",
  "recorded_at": "2026-03-01T14:30:00",
  "extra_fields": { "density": 0.78, "DRC_violations": 0 }
}
```

---

## 7. 命名与版本规范建议

| 项 | 建议 | 示例 |
|----|------|------|
| module_name | 与综合脚本中 top module 名严格一致, 大小写敏感 | `cpu_top`, `SRAM_CTRL` |
| version | 推荐格式 `<branch>_<date>_<short_hash>` 或语义版本 | `main_20260301_a1b2c3`<br>`v1.0.0-rc1` |
| 同一 module 多次上传 | 用 `version` 区分, **不要**用 module_name 加后缀 | `cpu_top/v1`, `cpu_top/v2` |
| 违例路径文件名 | `<timing_group>.csv`, 大小写需与报告一致 | `SRAMCLK.csv` |

---

## 8. 常见错误示例

| 错误 | 现象 | 修正 |
|------|------|------|
| `wns_setup = 0.123` | 负值丢失, 系统认为无违例 | 综合 slack 始终是**带符号**的, 应为 `-0.123` |
| `mbb_ratio = 85` | 比例字段被存为 8500% | 比例字段传 `0.85` 或 `85` 均可, 系统识别 |
| `version = ""` | 重复上传覆盖默认 v1, 数据混乱 | 每次 run 必须带唯一 version |
| `module_name = "CPU_top"` | 与系统中的 `cpu_top` 不匹配 | 大小写必须一致 |
| 单位混用 (ps 与 ns) | 指标尺度错乱 | 全系统统一 **ns / mW / um² / MHz** |

---

## 9. 校验与告警触发

系统会在导入时自动执行：

1. **类型校验**：所有数值字段, 字符串数字自动转换, 转换失败置 null
2. **必填校验**：`module_name` + `version` 缺失时整行拒绝
3. **单位归一化**：所有指标单位已在字段定义中固定
4. **自动告警**：
   - `wns_setup < 0` 或 `nvp_setup > 0` → 触发 `timing_setup` 告警
   - `wns_hold < 0` → 触发 `timing_hold` 告警
   - `congestion > 0.8` → 触发 `congestion` 告警
   - `achieved_frequency < target_frequency` → 触发 `frequency` 告警
5. **覆盖更新**：相同 `(module_name, version)` 的新 run **覆盖**旧记录, 不会创建重复

---

**文档版本**: 1.0
**最后更新**: 2026-07-16
**维护**: QoR Recorder Team
