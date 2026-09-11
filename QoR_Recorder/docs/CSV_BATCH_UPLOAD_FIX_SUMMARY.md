# 网页 CSV 批量上传与 path_group timing 解析修复摘要

## 范围

本文总结与“网页 CSV 批量上传”、“动态 path_group timing 解析”以及 **CSV 上传后在 Dashboard 正常展示（不再误报 record not found）** 直接相关的修改。当前工作树中同时存在项目 YAML 导入、logging、永久上传 Key 等其他改动，均不在本文范围内。

本轮修复分为三个阶段：

1. 修复管理页 CSV 上传链路，使用户能够选择单个 CSV 或一次选择整个本地目录、查看所有文件的真实预览与模块映射，并获得准确的逐文件导入统计与错误反馈。
2. 将任意 path group 的动态 timing 列转换为标准 timing 数据，使网页上传和 `scripts/csv_to_json.py` 生成一致的结果。
3. 修复 Dashboard DC 报告面板：CSV 记录通常没有 `raw_dc_report` 和 Physical 指标，不应再显示 `record not found` 红色错误；Timing 等数据改从记录字段 / `extra_fields` 读取。
## 阶段一：网页 CSV 批量上传

### 行为变化

- 上传窗口明确区分“单文件上传”和“整目录上传”。整目录上传使用浏览器
  `webkitdirectory` 选择本地目录，并上传 `files` 与对应的
  `webkitRelativePath`；后端只处理浏览器提交的内容，**不会扫描服务器
  `base_dir` 或访问服务器文件系统**。
- 目录结构约定为
  `base_dir/module_name/module_name_qor.csv`。默认由 CSV 父目录推断模块；
  也可由文件名推断，并安全剥离 `_qor_report`、`_qor`、`qor` 后缀。
- 浏览器相对路径统一处理 `/` 和 `\`，拒绝绝对路径、`..`、空路径和非
  CSV。目录根部的 `base_dir/block_qor.csv` 不符合
  `base/module/file.csv` 结构，会在预览和上传结果中明确报告，不会被导入。
- 上传窗口只列出可写项目，并显示所选项目的模块。
- 若 CSV 中只有一个 `module_name` 且能唯一匹配现有模块，则自动选择；用户手动选择的模块优先。
- 上传请求明确提交 `project_id`、`module_id`、可选 `release_dir`，勾选自动发布时提交后端字段 `mark_released=true`，不再使用旧的 `auto_release` 字段。
- 文件选择后调用后端预览接口；接口逐文件返回相对路径、推断模块、映射
  状态、真实表头、前 20 行、总行数和错误，并提供整批汇总。
- 后端校验模块是否属于目标项目，返回逐文件的 `saved`、`updated`、`skipped`、`errors` 和行号/原因。
- 正式上传与预览共用同一安全路径/模块推断 helper；目录推断出的模块不
  存在时可自动创建项目模块映射。单个文件失败不会中断其余文件。
- 文件为空、解析失败或某个文件没有保存/更新任何记录时，该文件标为失败；所有文件均为零写入时，整体返回 HTTP 422 和 `ok=false`，前端不会误报“上传成功”。
- 成功页显示新增、更新和跳过数量，成功后刷新管理页数据。
- 兼容旧 CSV 字段：
  - `total_area -> area_total`（Dashboard Total area）
  - `comb_area -> area_combinational`（Combinational area）
  - `reg_area -> area_sequential`（Sequential area）
  - `macro_area -> area_macro`（Macro area）
  - `total_count -> instance_count`（Instance count）
  - `reg_count -> register_count`（Register count）
  - `macro_count -> macro_cell_count`
  - `stdcell_area` 无独立 Dashboard 列，保留在 extra；语义为 Total area − Macro area。若缺少 `total_area`，用 `stdcell_area + macro_area` 回填 `area_total`。
- 版本仍优先从 `full_dir` 派生；在原有 `regr_*`、`YYYYQn_wN` 规则之外兼容 `v1`、`v1.2` 等旧发布目录。路径中没有可识别版本时，才使用经过字符和长度校验的 CSV/请求版本 fallback。
- 模块名比较采用规范化结果，减少大小写或 Unicode 表示差异造成的重复模块。

### 目录上传界面优化（补充）

- **单文件预览修复**：单文件模式提交 `module_name_source=csv`（此前误用 `dirname`，导致扁平 CSV 如 `module_alu_qor.csv` 预览失败）。
- **错误展示**：后端逐行/逐文件错误对象在前端可读渲染，不再出现 `[object Object]`。
- **部分失败 UX**：目录预览时若部分文件无效，显示警告并允许导入有效文件；全部不可导入时禁用确认按钮；按钮文案为「确认导入 N 个模块」。
- **拖拽限制**：拖拽上传仅支持单文件模式（浏览器无法为拖拽文件设置 `webkitRelativePath`）。

## 阶段二：动态 path_group timing
### 解析规则

解析器按列名最后一个受支持后缀拆分，因此 path group 名可以包含下划线，不硬编码 `SYS_CLK` 或 `I2C_CLK`：

- `*_period`：周期，转换为有限浮点数 `period`
- `*_wns`：最差 setup 违例值，转换为有限浮点数 `wns`
- `*_tns`：setup 总违例值，转换为有限浮点数 `tns`
- `*_path`：违例条数，转换为非负整数 `nvp`

空值、NaN、Infinity、负数或非整数违例条数不会进入标准 timing 指标；原始动态列仍保留在 `extra_fields`，便于兼容和审计。

### 标准结构与聚合

每条记录生成：

- `extra_fields.timing_sections.default.default.<path_group>`
- `extra_fields.path_groups` 兼容镜像
- `extra_fields.clocks` 兼容镜像

Dashboard 使用的 setup 汇总规则与现有 DC report 逻辑一致：

- `wns_setup`：所有 path group 的最小 WNS
- `tns_setup`：所有负 TNS 之和
- `nvp_setup`：所有 path group 的 NVP 之和

CSV 已显式提供记录级 setup 指标时保留该值；缺失时才由 path group 聚合补齐。

网页 CSV 上传、`/api/v1/upload` 与 `scripts/csv_to_json.py` 共用 `django_app/services/csv_field_mapping.py`（旧列别名、`stdcell_area` 回填）以及 `django_app/services/csv_timing.py`（动态 path group）。转换脚本同时输出 `timing.setup`、`clocks`、`extra.path_groups` 和 `extra.timing_sections`。JSON 上传校验及 schema 也允许 path group 中的非负整数 `nvp`/`hold_nvp`，从而可接收转换后的 JSON。

### 仍无法消除的协议差异

字段映射已经统一；下面差异来自传输协议和模块推断约定，不是两套别名表：

- **JSON 上传仍要求 `full_dir`**（`/api/v1/qor/upload`）。CLI `--json` 必须带 `--full-dir`；网页 CSV 与默认 CLI multipart 可从 CSV 列或 `full_dir` 路径派生版本。
- **网页整目录模式**从相对路径的**父目录**推断模块（`base/module_alu/*.csv` → `module_alu`）。
- **CLI `--json` / `csv_to_json.py`**从 **CSV 文件名**推断模块（`module_alu_qor.csv` → `module_alu`）。默认 CLI multipart 同样按文件名推断。
- JSON 记录是嵌套对象（`area.total`、`cells.instance_count`），网页/v1 CSV 保存的是扁平列；转换后语义相同，JSON schema 仍要求 `schema_version` 与 `upload` 对象。

## 阶段三：Dashboard 与 CSV 记录兼容

### 背景

CSV 上传的记录通常：

- **没有** `raw_dc_report`（完整 DC 报告 JSON），Mongo `raw_reports` 集合中可能无对应条目；
- **没有** Physical 类指标（如 `utilization`、`congestion_h` 等），Dashboard 对应列显示 `—` 属正常；
- **有** path group timing，保存在 `extra_fields.timing_sections` / 记录级 `wns_setup` 等字段。

在 `PERSISTENCE_MODE=mongo` 或 `hybrid` 下，记录列表使用 MongoDB ObjectID（如 `6a858e1eafb0e39b66a02e96`）。DC 报告面板选中记录后会请求 `/api/v2/projects/{id}/records/{recordId}/raw`。修复前若 raw 不存在，API 返回 404 `"record not found"`，前端将 ObjectID 与错误一并显示为红色提示。

### 行为变化

- **后端 raw API**：记录存在但无 raw report 时返回 HTTP 200 和 `{ content: null }`，不再 404。
- **Hybrid 回退**：Mongo 查不到 raw 时，通过记录的 `legacy_id` 回退到 ORM/SQLite；Mongo 内联 `qor_records.raw_dc_report` 也可作为备选来源。
- **前端静默处理**：无 raw 数据视为正常，不写入 `rawErrors`；即使旧后端仍返回 404 `"record not found"` 也不展示红色错误行。
- **Timing 展示**：DC 面板从完整记录（含 `extra_fields.timing_sections`）解析 timing，不再仅依赖 lazy raw payload。
- **Physical 等 canonical 指标**：仍从记录字段读取；CSV 未提供时显示 `—`，不是系统错误。

## 修改文件
### 运行时必须部署

- `QoR_Recorder/django_app/api/views.py`
  - CSV 上传接入统一行归一化；
  - 校验 `module_id` 与项目归属；
  - 返回逐文件错误、统计和全跳过失败态；
  - 预览接口返回真实列、前 20 行、总行数及可用于自动匹配的模块名。
- `QoR_Recorder/django_app/api_v2.py`
  - raw report 接口：记录存在但无 raw 时返回 200 + `content: null`，避免 Dashboard 误报 `record not found`。
- `QoR_Recorder/django_app/repositories.py`
  - Mongo `get_raw_report` 增加 `qor_records.raw_dc_report` 内联回退；
  - Hybrid `get_raw_report` 通过 `legacy_id` 回退 ORM。
- `QoR_Recorder/django_app/services/csv_field_mapping.py`（新增）
  - 旧 CSV 字段别名与 `stdcell_area` 回填的唯一来源；网页导入与 CLI 转换共用。
- `QoR_Recorder/django_app/services/qor_import.py`  - 从共享模块读取别名并实现 `normalize_csv_record()`；
  - 接入动态 path group、`timing_sections` 和 setup 聚合；
  - 保存时记录逐行跳过原因；
  - 支持旧版本目录和受控版本 fallback。
- `QoR_Recorder/django_app/services/csv_upload_paths.py`（新增）
  - 只解析浏览器提交的相对路径元数据，不访问服务器文件系统；
  - 提供路径安全校验、父目录推断和文件名安全剥后缀。
- `QoR_Recorder/django_app/services/path_derivation.py`
  - 识别 `v1`/`v1.2` 等旧版本段；
  - 提供严格校验、仅按需启用的版本 fallback。
- `QoR_Recorder/django_app/services/csv_timing.py`（新增）
  - 提供纯 Python 的动态列拆分、数值清洗、`_path -> nvp`、setup 聚合和 `timing_sections` 构造逻辑。
- `QoR_Recorder/django_app/services/json_upload.py`
  - JSON `clocks` 校验允许非负整数 `nvp` 和 `hold_nvp`，兼容 CSV 转换结果。
- `QoR_Recorder/schemas/qor_upload.v1.json`
  - path group schema 增加 `nvp`、`hold_wns`、`hold_tns`、`hold_nvp`。
- `frontend-vue/src/api/admin.js`
  - 增加 CSV 服务端预览请求。
- `frontend-vue/src/api/dashboard.js`
  - `rawReport()` 正确解包 `content: null`，不把空响应当成错误对象。
- `frontend-vue/src/components/admin/DataUploadModal.vue`
  - 实现模式卡片、浏览器目录选择、逐文件映射/真实预览、完整 FormData、
    部分失败明细、键盘焦点管理和响应式布局；
  - 单文件 `module_name_source=csv`、可读错误展示、部分目录导入 UX。
- `frontend-vue/src/components/dashboard/DcReportPanel.vue`
  - 无 raw 时不展示 `record not found`；Timing 从 `extra_fields` 读取；缓存“已查无 raw”状态避免重复请求。
- `frontend-vue/src/stores/dashboard.js`
  - 新增 `hasRawReportEntry()`，区分“未查询”与“已查询但无 raw”。
- `frontend-vue/src/views/AdminView.vue`
  - 向上传窗口传入项目列表和当前项目，并在成功后刷新数据。
以下文件按使用场景部署：

- `QoR_Recorder/scripts/csv_to_json.py`
  - 命令行 CSV 转 JSON 工具接入共享 path group 解析与共享字段别名；服务器或离线环境使用该工具时必须同步。
  - 不再复制 `CSV_FIELD_ALIASES`，改为 import `csv_field_mapping`。

本修复不包含数据库模型变更，不需要执行 migration。CSV 预览 URL 已存在，本轮无需部署新的 URL 配置。

### 仅开发、测试或演示

- `QoR_Recorder/tests/test_csv_upload.py`（新增）
  - 覆盖旧字段映射、动态 path group、浏览器路径安全、真实 demo 目录预览/
    导入、逐文件隔离、旧版本 fallback 和全跳过错误。
- `QoR_Recorder/tests/test_repositories.py`
  - Hybrid raw 回退 ORM `legacy_id`；Mongo 内联 raw 回退。
- `QoR_Recorder/tests/test_api_v2.py`
  - raw API 在无 raw 内容时返回 200 + `content: null`。
- `frontend-vue/tests/components/DataUploadModal.test.js`（新增）
  - 覆盖真实预览、项目/模块字段、显式模块优先、错误展示、零导入不成功、
    部分/全部无效目录预览。
- `frontend-vue/tests/components/DcReportPanel.test.js`
  - 无 raw report 时不展示 `record not found` 错误行。
- `frontend-vue/tests/unit/api/dashboard.test.js`
  - `rawReport()` 解包 `content: null` 契约测试。
- `frontend-vue/tests/unit/api/admin.test.js`
  - 增加 CSV 预览 API 契约测试；该文件中的其他功能测试不属于本摘要范围。
- `QoR_Recorder/demo_batch_upload/module_alu/module_alu_qor.csv`
  - 保留旧字段格式并补齐第 6 条真实演示记录，用作端到端回归样本；不是生产运行依赖。
## 真实 demo 的预期结果

单文件模式使用 `demo_batch_upload/module_alu/module_alu_qor.csv`，在网页中选择正确项目和 `module_alu` 模块：

- 首次上传：`saved=6`、`updated=0`、`skipped=0`
- 原文件重复上传：`saved=0`、`updated=6`、`skipped=0`
- 版本集合：`v1`、`v2`、`v3`、`v4`、`v5`、`v7`
- 每条记录有 2 个 path group：`SYS_CLK`、`I2C_CLK`
- 每组包含可用的 `period`、`wns`、`tns`、`nvp`，并写入 `timing_sections`

重复上传通过记录唯一键更新原记录，不会新增第二组相同记录。

整目录模式选择本地 `demo_batch_upload` 时共有 6 个 CSV：

- 5 个模块子目录文件有效：`module_alu`、`module_ctrl`、`module_mem`、
  `module_misc`、`module_rf`；
- 首次上传合计 `saved=18`，5 个文件成功；
- 根目录 `block_qor.csv` 因不符合 `base/module/file.csv` 结构被明确报告，
  1 个文件失败；该失败不影响其余 5 个文件；
- 这是浏览器选择目录后的上传结果，不是服务器扫描该目录得到的结果。

## 已执行验证

- `python -m pytest tests/test_csv_upload.py -q`：14 passed。
- `python -m pytest tests/test_repositories.py tests/test_api_v2.py::test_v2_raw_report_returns_empty_payload_when_record_has_no_raw -q`：通过。
- 扩展 timing 定向测试（CSV 上传、timing normalization、DC report timing aggregation）：13 passed。
- `npm run test:unit -- tests/components/DataUploadModal.test.js tests/unit/api/admin.test.js`：通过（含目录上传与单文件预览）。
- `npm run test:unit -- tests/components/DcReportPanel.test.js tests/unit/api/dashboard.test.js`：17 passed（含无 raw 时不报 record not found）。
- `python scripts/csv_to_json.py demo_batch_upload/module_alu/module_alu_qor.csv --project-id 1 --version fallback --output NUL`：命令行转换通过。
- `schemas/qor_upload.v1.json`：JSON 解析有效。
- 相关 Python/Vue 文件 lint 与 diff whitespace 检查通过。

完整后端 `python -m pytest -q` 当前并非全绿；按要求记录一个与本轮修复无关的既有失败：

- `tests/test_performance_baseline.py::test_5k_metadata_list_and_lazy_raw_baseline` 期望 raw API 返回 200，当前环境因 Mongo raw 后端不可用返回 503。CSV 定向测试独立通过，因此该失败不归因于本轮 CSV/path_group/Dashboard 修改。
## Linux / Vue 部署清单

1. 同步“运行时必须部署”章节中的后端 Python 文件和 JSON schema；若生产环境使用 CSV 转 JSON 命令行工具，同时同步 `scripts/csv_to_json.py`。
2. 同步以下 Vue 源码：
   - `frontend-vue/src/api/admin.js`
   - `frontend-vue/src/api/dashboard.js`
   - `frontend-vue/src/components/admin/DataUploadModal.vue`
   - `frontend-vue/src/components/dashboard/DcReportPanel.vue`
   - `frontend-vue/src/stores/dashboard.js`
   - `frontend-vue/src/views/AdminView.vue`
3. 在 `frontend-vue` 目录执行 `npm ci`（依赖未变化且现有 `node_modules` 可用时可跳过），再执行 `npm run build`。
4. 将新生成的 `frontend-vue/dist/` 完整替换到生产静态资源部署位置，避免只复制单个编译产物造成旧 chunk 残留。
5. 重启 Django/Gunicorn/uWSGI 对应服务，例如 `sudo systemctl restart qor_recorder`；本轮未修改 systemd unit，不需要仅因本修复执行 `daemon-reload`。
6. 清理浏览器/CDN 静态缓存后验证：
   - 管理页：demo 或脱敏 CSV 单文件/整目录上传，确认项目、模块、真实预览和导入统计正常；
   - Dashboard：选中 CSV 导入的记录，DC 报告面板 **不再出现** `6a858e...: record not found`；Physical 无数据时显示 `—` 属正常；Timing 有 path group 数据时应能展示。

## 旧记录重新上传提示

修复只影响新导入或被更新的记录，不会自动回填数据库中此前已上传但缺少 path group timing 的旧记录。部署完成后，请在网页中选择原项目和原模块，重新上传原 CSV；相同唯一键的记录应计为 `updated`，并补齐 `timing_sections`、path group 兼容镜像及 setup 聚合。建议先备份数据库，并用少量记录确认更新数量和 timing 展示后再批量重传。

**Dashboard 说明**：CSV 记录本身不含 Physical / 完整 DC raw report 时，部署后也不会 magically 出现这些列的数据；修复的是 **不再误报 record not found**。若需 Physical 等指标，须从含相应列的 CSV 或完整 DC JSON 导入。