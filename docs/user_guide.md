# QoR Recorder 用户使用指南

## 1. 系统简介

QoR Recorder 是一款面向 IC 设计团队的综合质量数据管理系统。它能帮您：

- 集中管理多个芯片项目、多个模块、多个版本的综合 QoR 数据
- 通过交互式图表直观对比面积、时序、功耗等指标
- 下钻分析违例路径，支持 Bus 合并和跨版本 diff
- 一键导出对比结果为 Excel/CSV

## 2. 快速开始

### 2.1 访问系统

1. 打开浏览器，访问 `http://<服务器IP>:5000`
2. 使用管理员分配的账号登录

**默认账号**（仅演示，生产环境请修改）：

| 角色   | 用户名   | 初始密码       | 权限                 |
| ---- | ----- | -------- | ------------------ |
| 管理员  | admin | admin@2026 | 所有功能，含数据上传/管理      |
| 普通用户 | user  | user@2026  | 只能查看 Dashboard 和导出 |
| 发布用户 | release | release@2026 | 查看所有数据 (含未发布) + 访问对比页 + 在管理页面管理自己 release 的记录 (撤回) |

> 首次登录后请立即修改默认密码。

### 2.2 首页概览

登录后进入 Dashboard 页面，从上到下依次为：

1. **筛选器**：选择项目、模块、版本
2. **图表区**：面积、时序、功耗、单元统计、饼图
3. **违例路径分析面板**：违例路径表格与对比

## 3. 数据准备

### 3.1 QoR 数据 CSV 格式（v3.0）

QoR Recorder 支持解析 Design Compiler 导出的 CSV 文件。系统会自动识别列名变体（不区分大小写、空格、下划线、连字符），但建议使用以下标准列名。

**核心字段**：

```
module_name, version, full_dir,
area_total, area_combinational, area_sequential, area_macro,
wns_setup, tns_setup, nvp_setup,
wns_hold, tns_hold, nvp_hold,
power_internal, power_switching, power_leakage, power_total,
cell_count, instance_count, net_count, sequential_cell_count,
target_frequency, achieved_frequency,
mbb_ratio, clock_gating_ratio, utilization,
congestion, congestion_h, congestion_v, congestion_b
```

**v3.0 关键变更**：
- `version` 是主键列（不再使用 `tag`，仍兼容）
- `full_dir` 是新增的独立列（v2.0 在 `extra_fields` JSON 中，v3.0 提升为独立列）
- 所有时序指标（`wns_setup` / `tns_setup` / `nvp_setup` / `wns_hold` / `tns_hold` / `nvp_hold`）**统一为"越小越好"**

**实际使用的 CSV 格式示例**（含 full_dir 与多时钟列）：

```csv
module_name,version,full_dir,comment,area_total,area_combinational,area_sequential,area_macro,wns_setup,tns_setup,nvp_setup,wns_hold,tns_hold,nvp_hold,power_total,cell_count,target_frequency,achieved_frequency,SRAMCLK_period,SRAMCLK_wns,SRAMCLK_tns,SRAMCLK_path,CLK_CPU_period,CLK_CPU_wns
cpu_top,v1.0,v1.0/main/cpu_core_baseline,cpu v1.0 baseline,12345.6,5678.9,3456.7,1110.0,-0.123,-0.456,12,0.012,0.034,3,9.9,8500,500.0,476.2,2.50,-0.123,-0.456,/clk_div/SRAMCLK/end_reg,1.25,-0.045
```

**字段说明**：

- `module_name`：模块名，必须与系统中已有模块一致（大小写敏感）
- `version`：版本标签（必填，业务主键之一）
- `full_dir`：Run 目录路径（推荐），格式 `<base_dir>/<sub_path>/<run_name>`，用于按目录聚合
- `tag`：仍兼容，作为 `version` 的别名
- `comment`：自由备注
- 未在标准字段列表中的列（如 `density`、`DRC_violations`、各 clock 的 period/wns/tns/path）会自动存入 `extra_fields`
- 编码支持 UTF-8 BOM / UTF-8 / GBK / Latin-1
- 空值可用 `-`、`N/A`、`NULL`、空字符串表示
- 比例字段（`mbb_ratio` / `clock_gating_ratio` / `utilization` / `congestion*`）可传 0-1 小数（推荐）或 0-100 整数

### 3.2 功耗数据 CSV 格式

功耗数据可单独上传，按 `(模块 + 版本)` 合并到已有 QoR 记录：

```csv
tag,power_internal,power_switching,power_leakage,power_total
v1.0,5.234,2.891,0.156,8.281
```

### 3.3 违例路径 CSV 格式

每个 timing group 一个 CSV 文件，文件名建议包含 timing group 名称（如 `SRAMCLK_violations.csv`）：

```csv
STARTPOINT,ENDPOINT,SLACK,DEPTH,PURE_DEPTH,CELL_DELAY,NET_DELAY,ET_SLACK,ST_SLACK,ST_FANIN,ST_FANOUT,ET_FANIN,ET_FANOUT
a_reg/CK,b_Refg_0_/D,-0.020,27,23,500,77,9,-10,1,122,122,11
```

**字段说明**：

| 字段                     | 含义          | 单位/类型           |
| ---------------------- | ----------- | --------------- |
| STARTPOINT             | 路径起点        | 如 `a_reg/CK`    |
| ENDPOINT               | 路径终点        | 如 `b_Refg_0_/D` |
| SLACK                  | 违例 slack    | ns（负值为违例）       |
| DEPTH                  | 路径深度        | 整数              |
| PURE\_DEPTH            | 纯逻辑深度       | 整数              |
| CELL\_DELAY            | 单元延迟        | ps 或 ns         |
| NET\_DELAY             | 网络延迟        | ps 或 ns         |
| ET\_SLACK / ST\_SLACK  | ET/ST slack | ns              |
| ST\_FANIN / ST\_FANOUT | ST 扇入/扇出    | 整数              |
| ET\_FANIN / ET\_FANOUT | ET 扇入/扇出    | 整数              |

**注意事项**：

- 列名不区分大小写、空格、下划线
- 若表头无法识别，按上述标准顺序位置映射
- 异常数据（如 `11=-212835712990`）会自动提取 `=` 前的数值
- 一个 run 版本可以有 0 个或多个 CSV 文件（每个 timing group 一个）

## 4. 数据上传（管理员）

### 4.1 上传入口

1. 登录管理员账号（admin）
2. 点击导航栏「管理」进入管理页面
3. 在「上传数据」区域操作

### 4.2 上传 QoR 数据

1. **项目**：选择已有项目，或输入新项目名称
2. **模块**：选择已有模块，或输入新模块名称
3. **版本**：输入版本标签（如 v1.0），留空则用 CSV 中的 `tag` 列
4. **数据类型**：选择「QoR 数据」
5. **选择文件**：可多选 CSV 文件
6. 点击「上传」

**行为**：

- 若 (模块 + 版本) 已存在，更新该记录
- 否则新建记录

### 4.3 上传功耗数据

1. 数据类型选择「功耗数据」
2. 其余步骤同上

**行为**：

- 按 (模块 + 版本) 匹配已有 QoR 记录，合并功耗字段
- 若 QoR 记录不存在，该行跳过

### 4.4 上传违例路径

1. 数据类型选择「违例路径」
2. 选择模块和版本（必须与已有 QoR 记录匹配）
3. 上传一个或多个 CSV 文件（每个文件对应一个 timing group）

**行为**：

- 按 (模块 + 版本) 关联到已有 QoR 记录
- timing group 从文件名提取（如 `SRAMCLK_vio.csv` → `SRAMCLK`）
- 若 QoR 记录不存在，该文件跳过

### 4.5 上传 Run 备注（v3.0 新增 notes 数据类型）

1. 数据类型选择「Run 备注」
2. 选择模块和版本
3. （可选）填写 `full_dir`：Run 目录路径，用于区分同 module+version 下的不同子目录 run
4. 选择 CSV 文件（2~3 列：`item, description[, full_dir]`）

**CSV 格式 A：2 列（item, description），通过参数传入 full_dir**：

```csv
item,description
综合策略,compile_ultra
目标频率,500MHz
修改内容,优化了关键路径 retiming
```

**CSV 格式 B：3 列（item, description, full_dir）**，每行可指定不同 full_dir：

```csv
item,description,full_dir
综合策略,compile_ultra,v1.0/corner_ss/cpu_core_baseline
综合策略,compile_fast,v1.0/corner_ff/cpu_core_baseline
目标频率,500MHz,v1.0/corner_ss/cpu_core_baseline
```

**行为**：

- 关联到 (模块 + 版本) 对应的 QorRecord
- 若 `full_dir` 非空，进一步按 `QorRecord.full_dir` 精确匹配（v3.0 起为独立列）
- 找不到精确匹配 → 回退到该 (module, version) 的第一条记录（兼容老数据）
- **重复上传同 (record, full_dir) 的备注会覆盖旧备注**，不会累积
- 其他 `full_dir` 的备注不受影响

### 4.6 项目与模块管理

在管理页面可：

- 新建/删除项目
- 新建/删除模块
- 删除数据会级联删除其下所有记录

### 4.7 命令行 / Makefile 自动化上传

适合 DC 综合流程结束后自动上传，无需登录 Web。详细格式见 [DATA_FORMAT.md](DATA_FORMAT.md)。

**脚本方式**：

```bash
export QOR_API_KEY=qor_xxxxxxxx
./scripts/upload_qor.sh <project_id> <version> <csv> [data_type] [options]

# data_type: qor (默认) / power / violation / notes
# --release: 标记为已发布
# --full-dir <DIR>: Run 目录路径 (notes 类型, 默认 $PWD)
```

**Makefile 方式**（推荐用于 DC flow）：

将 `scripts/Makefile.example` 复制到 run 目录，配置变量后：

```bash
make upload           # 仅上传 QoR
make upload-all       # 上传 QoR + 功耗 + 违例 + 备注
make release          # 上传并标记为已发布
```

Makefile 自动用 `$(PWD)` 作为 notes 的 `full_dir`，再次 `make` 会覆盖同目录的旧备注。

### 4.7.1 release 角色管理页操作（v4.x 新增）

`release` 角色可访问 `/admin` 页面（仅显示「记录管理」标签），用于管理**自己发布**的记录：

- **查看所有记录**：包括未发布记录（不再过滤 `is_released`）
- **批量撤回**：选中自己发布（`released_by=当前用户`）的记录后可一键撤回
- **不可执行**：发布他人未发布的记录、撤回他人发布的记录、删除记录、上传数据、管理项目/用户

### 4.8 一键生成 Demo 数据（v3.0 新增）

需要快速体验 Dashboard / 对比 / Review 等功能时，可使用 demo 数据生成脚本：

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

**生成规模**：

| 维度          | 数量                                       |
|---------------|--------------------------------------------|
| 项目          | 5 个（demo_riscv_soc / demo_dsp_engine / demo_video_codec / demo_eth_mac / demo_ai_accel）|
| 模块/项目     | 5~10 个                                    |
| base_dir/模块 | 2~3 个（日期/周次/语义版本号）              |
| run/base_dir  | 2~3 个（baseline / cfg1 / cfg2 / opt_speed / opt_area / mbb_aggr）|
| 总记录数      | 约 200+ 条（默认 seed 约 227 条）           |

**`--clean-all` 清理顺序**（修复外键约束错误）：

```
TileReview / GroupReview / SubsystemReview / ReviewSnapshot / ReviewFile
  → ProjectMember / DashboardGroup
    → 非系统项目 (排除 _system / system / admin / default)
      → 模块/记录 (级联)
```

详细字段与指标方向约定见 [DATA_FORMAT.md](DATA_FORMAT.md) §14~19。

## 5. Dashboard 使用

### 5.1 筛选数据

页面顶部的筛选器控制所有图表的数据范围：

1. **项目**：多选，选择要查看的项目
2. **模块**：多选，选择要对比的模块
3. **版本**：多选，选择要查看的版本
4. 点击「刷新数据」生效

### 5.2 图表说明

#### 面积趋势图（柱状图）

- 展示各模块各版本的总面积
- 可切换指标：总面积、组合面积、时序面积、黑盒面积、宏单元面积

#### 时序趋势图（折线图）

- 展示 WNS/TNS 随版本的变化趋势
- 可切换 Setup / Hold 指标

#### 功耗趋势图（柱状图）

- 展示功耗分解（内部/翻转/漏电）
- 可切换总功耗或分项

#### 单元统计图（堆叠柱状图）

- 展示组合/时序单元占比

#### 面积构成饼图

- 多选模块，展示各模块面积占比
- 适合看模块间的面积分布

### 5.3 图表交互

- **悬停**：显示详细数值
- **图例点击**：显示/隐藏某系列
- **数据缩放**：柱状图底部可拖动选区
- **标签模式**：切换横轴显示为 tag / 模块名 / 模块+版本

### 5.4 保存 Dashboard 配置

1. 调整好筛选器和图表设置后
2. 点击「保存配置」按钮
3. 输入配置名称，可设为默认
4. 下次登录自动加载默认配置

## 6. 违例路径分析

违例路径面板位于 Dashboard 下方，有两种模式可切换。

### 6.1 单 run 查看模式

用于查看某一个 run 的违例详情，有独立的 4 级联动筛选器：

1. **模块**：选择要查看的模块
2. **版本**：选择该模块的某个版本
3. **Timing Group**：选择特定时钟组（如 SRAMCLK），或「全部」
4. **CSV 文件**：选择具体的源文件，或「全部」

**其他控制**：

- **排序**：按 Slack / Depth / Cell Delay / Net Delay，升序（最差优先）或降序
- **条数**：100 / 500 / 1000 / 2000
- **Bus 合并**：勾选后，ENDPOINT 只有末尾编号不同的路径会合并为一条

**VIO\_NUMBER 列**：

- 显示该行代表的合并路径数量
- 若 >1，背景高亮（黄色）
- 例如 `data_out_0_/D` \~ `data_out_63_/D` 合并为 1 条，VIO\_NUMBER=64

### 6.2 两 run 对比模式

用于对比同一模块两个版本的违例差异，判断时序变好还是变差。

**操作步骤**：

1. 切换模式到「两 run 对比」
2. 选择模块
3. 选择 Timing Group（或「全部」）
4. 选择版本 A 和版本 B（不能相同）
5. 点击「对比」

**汇总卡片**：

- **版本 A / B**：各自的违例数、最差 slack、平均 slack
- **改善**：slack 变正（变大）的路径数
- **恶化**：slack 变负（变小）的路径数
- **新增**：B 版本新增的违例
- **修复**：B 版本已消除的违例

**表格列**：

| 列                              | 含义                              |
| ------------------------------ | ------------------------------- |
| VIO\_NUMBER                    | Bus 合并后的数量                      |
| 状态                             | 改善（绿）/ 恶化（红）/ 新增（橙）/ 已修复（蓝）/ 持平 |
| Startpoint / Endpoint          | 路径端点                            |
| Slack A / Slack B              | 两版本的 slack                      |
| Δ Slack                        | 变化值（正=改善，负=恶化）                  |
| Depth / Cell Delay / Net Delay | A/B 两版的对应值                      |

**排序**：默认按 Δ Slack 升序，恶化最多的路径在最上方，便于优先关注。

### 6.3 Bus 合并说明

**为什么需要 Bus 合并**？
一个 64-bit 数据总线的 64 条违例路径，本质上是一个时序问题。逐条展示会产生大量噪音，合并后只看最差的一条，效率更高。

**合并规则**：

- ENDPOINT 形如 `data_bus_0_/D`、`data_bus_1_/D`、... `data_bus_63_/D` 的路径视为一组
- 只保留 slack 最差的那一条
- VIO\_NUMBER 列显示合并的路径数

**开关**：单 run 和对比模式都有独立的 Bus 合并复选框。

## 7. 数据对比与导出

### 7.1 对比页面

点击导航栏「对比」进入对比页面，可：

- 选择多个模块和多个指标
- 生成对比表格
- 查看各模块在各指标上的排名

### 7.2 导出数据

在对比页面或 Dashboard 点击「导出」按钮：

1. 选择模块（可多选）
2. 选择指标（可多选）
3. 选择版本范围
4. 选择格式：Excel (.xlsx) 或 CSV
5. 点击导出，浏览器下载文件

**导出内容**：项目、模块、版本、记录时间 + 选中的指标列。

## 8. 个人主题设置

每个登录用户可以定义自己的界面主题，主题设置会保存在当前用户账户下，刷新或重新登录后仍然生效。

### 8.1 打开主题设置

在导航栏右上角（用户名左侧）点击 ◐ 形状的主题按钮，即可打开主题设置弹窗。

### 8.2 预设主题

系统内置 5 套预设主题，点击任一预设卡片即可立即预览效果：

| 预设      | 主色           | 适用场景         |
| ------- | ------------ | ------------ |
| classic | 深蓝 (#1a237e) | 默认主题，与历史版本一致 |
| dark    | 深蓝 + 深色背景    | 弱光环境、长时间盯屏   |
| green   | 深绿           | 偏好绿色系        |
| purple  | 深紫           | 偏好紫色系        |
| orange  | 深橙           | 偏好暖色系        |

### 8.3 自定义颜色

在「自定义颜色」区可直接编辑以下字段（颜色选择器与文本框同步）：

- 主色 / 主色(渐变终点)：导航栏渐变两端
- 页面背景 / 卡片背景 / 卡片悬停：背景层
- 主文字 / 次要文字 / 边框：内容层
- 导航文字 / 导航激活文字：导航栏文字层

颜色格式支持 `#hex`、`#rrggbb`、`#rrggbbaa`、`rgb(...)`、`rgba(...)`、`hsl(...)`、`hsla(...)`。任一字段被修改后，主题名自动改为 `custom`。

### 8.4 保存与重置

- **保存**：点击「保存」按钮，主题写入数据库，对所有页面持久生效
- **取消**：点击「取消」恢复到打开弹窗前的主题
- **重置为默认**：点击「重置为默认」恢复 classic 主题

### 8.5 注意事项

- 主题仅影响 UI 框架颜色，**不影响 ECharts 图表的配色**
- 主题按用户存储，不同用户互不影响
- 主题数据存储在 `users.theme` 字段（JSON 字符串），可通过 API 读取/写入

### 8.6 主题 API

```
GET  /api/user/theme                 # 获取当前主题 + 所有预设 + 默认主题
POST /api/user/theme                 # 保存主题
     Body: {"theme": {...}}          # 自定义主题 (字段经校验)
     Body: {"preset": "dark"}        # 应用预设
     Body: {"reset": true}           # 重置为默认
```

所有主题接口需登录访问，仅能操作当前登录用户的主题。

### 8.6 强制改密提示

- 首次登录 / 密码被管理员重置后, 系统会强制跳转到 `/change_password` 改密页
- 改密成功之前, 所有其他页面 (Dashboard / Admin / 上传等) 都会被拦截并跳转回改密页
- 改密成功后自动跳回首页

## 9. 常见问题

### Q1: 上传 CSV 提示「未识别到任何列」？

**A**: 请检查 CSV 第一行是否为列名。若列名与标准字段不匹配，系统会尝试按位置映射。确保 CSV 使用逗号分隔，编码为 UTF-8 或 GBK。

### Q2: 违例路径上传后看不到数据？

**A**: 违例路径必须关联到已有的 QoR 记录。请先上传该 (模块 + 版本) 的 QoR 数据，再上传违例路径。在违例面板选择正确的模块和版本即可看到。

### Q3: Bus 合并后为什么条数变少了？

**A**: 这是正常行为。Bus 合并将 ENDPOINT 只有末尾编号不同的路径合并为一条。例如 64 条 bus 违例会合并为 1 条，VIO\_NUMBER 显示 64。如需查看全部，取消勾选「Bus 合并」。

### Q4: 对比模式中「新增」和「修复」是什么意思？

**A**:

- **新增**：版本 B 中出现了版本 A 没有的违例路径（时序变差）
- **修复**：版本 A 的某条违例在版本 B 中已不存在（时序变好）

### Q5: 忘记管理员密码怎么办？

**A**: 联系系统管理员。若需重置，可在服务器上执行：

```python
from app import app, db
from models import User
app.app_context().push()
admin = User.query.filter_by(username='admin').first()
admin.set_password('new_password')
admin.must_change_password = True   # 强制用户下次登录必须改密
db.session.commit()
```

### Q6: 密码强度要求是什么？

**A**: 改密和重置密码时, 系统会校验:

| 要求     | 说明                            |
|----------|---------------------------------|
| 最少 8 位 | 长度 < 8 直接拒绝               |
| 含字母   | 至少 1 个 a-z / A-Z             |
| 含数字   | 至少 1 个 0-9                   |
| 非弱口令 | 拒绝 `12345678` / `password` / `admin123` / `qwerty123` / `11111111` / `00000000` 等 |

弱密码会被前端实时显示, 改密按钮会提交但被后端拒绝。

### Q7: 数据库多大算太大？性能会下降吗？

**A**: SQLite 在万条记录量级性能良好。若记录超过 10 万条，建议迁移到 PostgreSQL/MySQL。系统启动时会自动备份数据库到 `backups/` 目录，防止数据丢失。

### Q8: 如何查看某条记录的完整 extra\_fields？

**A**: 在 Dashboard 的图表上悬停，或通过 API `/api/qor_data` 查询，返回的 JSON 中包含 `extra_fields` 字段（含 comment、full\_dir、各 clock 的详细信息）。

### Q9: 多人能同时使用吗？

**A**: 可以。Flask 支持多线程并发，多用户可同时查看。但建议避免多人同时上传大量数据，SQLite 的写入并发有限。

## 10. 最佳实践

### 10.1 命名规范

- **项目名**：使用芯片代号（如 ChipA、ChipB）
- **模块名**：与 RTL 模块名一致（如 top\_alu、mem\_ctrl）
- **版本号**：建议用 `v主版本.次版本`（如 v1.0、v2.1），或 commit hash 短码

### 10.2 上传节奏

- 每次综合后立即上传，避免数据堆积
- QoR 数据先上传，功耗和违例路径后上传
- 违例路径按 timing group 分文件，文件名包含 TG 名

### 10.3 版本对比技巧

- 对比相邻版本（如 v1.1 vs v1.2）看增量变化
- 对比跨大版本（如 v1.0 vs v2.0）看整体演进
- 关注 Δ Slack 最负的几条路径，优先修复

### 10.4 Bus 合并使用

- 初步分析时开启 Bus 合并，快速定位问题总线
- 深入分析某条 bus 时关闭合并，查看具体哪一位最差

## 11. 数据库存储与迁移

### 11.1 存储结构（v4.0 起按项目分库）

自 v4.0 起，QoR Recorder 采用**主库 + 项目库**的分离架构：

| 文件                                | 存储内容                                                                                |
|-------------------------------------|-----------------------------------------------------------------------------------------|
| `qor_recorder.db`（主库）            | 用户、项目元数据、API Key、项目成员、仪表板配置主键等**系统级**数据                       |
| `qor_p_<id>.db`（项目库，**每个项目一个**） | 该项目的模块、QoR 记录、违例路径、Run 备注、Tile/Group/Subsystem Review、告警规则等**业务**数据 |

**优势**：

- **性能隔离**：每个项目独立文件，单项目大数据量不会拖慢其他项目
- **易于备份/归档**：可单独备份或归档一个项目（直接拷贝对应 `qor_p_<id>.db`）
- **支持锁定**：项目 `status=locked` 时，对应 DB 文件被设为 `0444`（只读），物理层防止误写
- **可清理**：删除项目时只需删除对应 `.db` 文件，零牵连
- **跨项目查询**：Dashboard 等场景通过 `query_records_by_projects()` 按项目迭代查询并合并结果

### 11.2 迁移历史数据到分库结构

从旧版（v3.x 单库）升级到 v4.0 时，运行迁移脚本：

```bash
# 1. 备份旧主库
cp qor_recorder.db qor_recorder.db.bak.$(date +%Y%m%d)

# 2. 升级代码 + 跑 alembic 迁移（增加 projects.db_path 字段）
flask db upgrade

# 3. 按项目分库数据迁移（默认 dry-run 模式，先看看会迁什么）
python migrate_to_per_project_db.py --dry-run

# 4. 实际迁移
python migrate_to_per_project_db.py

# 5. 迁移后从主库清理已迁数据（可选，节省主库空间）
python migrate_to_per_project_db.py --clean
```

**注意**：

- 迁移脚本使用直接 SQL 操作（不走 ORM bind 路由），避免分库逻辑干扰
- 迁移后主库中 `modules` / `qor_records` 等业务表为 0 条，所有数据都在 `qor_p_<id>.db`
- 单库结构的回滚：删除所有 `qor_p_*.db` 后将主库 `modules` 等表的内容恢复即可（请用 `--clean` 前的备份）

### 11.3 锁定项目（status=locked）

```bash
# 通过管理页面 → 项目管理 → 锁定按钮
# 或直接修改项目状态
```

锁定后该项目的 `.db` 文件被设为只读（`0444`），所有写入请求（上传/编辑/删除）会被拒绝。

**解锁**：在管理页面解锁，文件恢复 `0644`，WAL 模式自动恢复。

### 11.4 删除项目

QoR Recorder 提供两级删除：

| 操作       | 数据保留 | 是否可恢复 | 使用场景                       |
|------------|----------|------------|--------------------------------|
| 软删除     | 全部保留 | ✅ 可恢复   | 误操作、临时清理 dashboard     |
| 硬删除     | 全部删除 | ❌ 不可逆   | 数据迁移完成、释放磁盘空间      |

- **软删除**：admin → 项目管理 → 删除（设 `status=hidden`），admin → 已隐藏项目 → 恢复
- **硬删除**：admin → 已隐藏项目 → 硬删除（需输入 `confirm=true`），同时删除对应 `qor_p_<id>.db`

### 11.5 多数据库后端切换（DB_TYPE）

通过单一环境变量 `DB_TYPE` 切换后端：

| DB_TYPE  | 含义              | 必填额外配置        |
|----------|-------------------|---------------------|
| `sqlite` | SQLite（默认）     | 无                  |
| `sql`    | MySQL/PostgreSQL  | `DATABASE_URL`      |
| `mongodb`| MongoDB           | `MONGODB_URI`       |

```bash
# SQLite (默认)
DB_TYPE=sqlite

# MySQL
DB_TYPE=sql
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/qor_recorder?charset=utf8mb4

# MongoDB
DB_TYPE=mongodb
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=qor_recorder
```

切换后端后执行 `python db_init.py` 自动建库/迁移。

**注意**：MongoDB 模式下，主库走 SQLite（只读回退），业务库走 Mongo + 双写架构。详见 `docs/MIGRATION_MONGODB.md`（如存在）。

## 12. 联系与支持

- 系统管理员：请联系您的团队管理员
- 数据问题：检查 CSV 格式与编码
- 功能建议：反馈给开发团队

***

*文档版本：4.0 | 最后更新：2026-07-28（按项目分库架构 + MongoDB 切换）*
