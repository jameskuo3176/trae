# QoR Recorder 脚本上传试验（交 IT）

本文用于在 Linux 部署机上验证 `scripts/upload_qor.sh`。  
试验可在**用户自己的工作目录**执行，不必 `cd` 到 `/opt/qor_recorder`。

以下假设：

```text
应用目录：/opt/qor_recorder
服务端口：5000（按实际 .env / systemd 修改）
项目 ID：2
演示 CSV：/opt/qor_recorder/demo_batch_upload/module_alu/module_alu_qor.csv
```

请按实际环境替换服务器地址、项目 ID 和 API Key。

---

## 1. 本次试验要同步的文件

先把这 4 个文件同步到生产机再试。缺任何一个都会失败。

| 文件 | 作用 |
|---|---|
| `django_app/api/views.py` | 默认上传接口兼容 `files` 字段（脚本发 `files=@csv`） |
| `scripts/csv_to_json.py` | `--json` 时从文件名推断模块（`module_alu_qor.csv` → `module_alu`）；旧列别名从共享模块读取 |
| `django_app/services/csv_upload_paths.py` | 被 `csv_to_json.py` import；没有则 JSON 转换失败 |
| `django_app/services/csv_field_mapping.py` | 被 `csv_to_json.py` import；网页 CSV 与 CLI 共用旧字段映射 |

同步后重启服务：

```bash
sudo systemctl restart qor_recorder
sudo systemctl status qor_recorder --no-pager
```

确认 `csv_upload_paths.py` 存在：

```bash
ls -l /opt/qor_recorder/django_app/services/csv_upload_paths.py
ls -l /opt/qor_recorder/django_app/services/csv_field_mapping.py
ls -l /opt/qor_recorder/scripts/csv_to_json.py
```

---

## 2. 试验前准备

### 2.1 API Key

必须设置 `QOR_API_KEY`（格式 `qor_xxxxxxxx`）。获取方式见 `docs/IT_PERMANENT_UPLOAD_KEY.md`。

```bash
export QOR_API_KEY=qor_xxxxxxxxxxxxxxxx
```

不要把 Key 写进聊天、Git 或共享目录。

### 2.2 服务器地址

脚本默认打 `http://localhost:5000`。  
**在自己工作机上跑时必须改成部署机地址**，否则会打到本机。

```bash
# 在部署机本机试验
export QOR_SERVER=http://localhost:5000

# 在自己工作目录 / 其他机器试验（改成实际主机名或 IP）
export QOR_SERVER=http://<部署机主机名或IP>:5000
```

若前面有 Nginx 反代，用对外地址，例如 `http://qor.example.internal`。

### 2.3 工作目录

可拷贝演示 CSV 到自己的目录：

```bash
mkdir -p ~/qor_upload_trial/module_alu
cp /opt/qor_recorder/demo_batch_upload/module_alu/module_alu_qor.csv \
   ~/qor_upload_trial/module_alu/
cd ~/qor_upload_trial
```

不要把 `csv_to_json.py` 单独拷到工作目录。始终调用 `/opt/qor_recorder/scripts/upload_qor.sh`。

---

## 3. 试验 A：默认 multipart（推荐先做）

这条路对应脚本默认行为，**不要加 `--json`**。  
依赖已更新的 `views.py`。

```bash
cd ~/qor_upload_trial

/opt/qor_recorder/scripts/upload_qor.sh 2 v1.0 \
  ./module_alu/module_alu_qor.csv
```

模块名从文件名推断：`module_alu_qor.csv` → `module_alu`。  
项目 2 里需要已有同名模块，或后端允许自动创建；若提示模块不存在，先在管理页创建 `module_alu`，或加上 `--module-id <ID>`。

**成功示例：**

```text
[INFO] 上传 ... -> http://.../api/v1/upload
[INFO] HTTP 状态: 200
[OK] 上传成功 (qor)
```

响应里应有 `saved` 或 `updated` 大于 0。

**失败对照：**

| HTTP | 响应 | 原因 | 处理 |
|---|---|---|---|
| 400 | `缺少上传文件` | 旧 `views.py` 只认 `file`，脚本发 `files` | 确认已同步 `views.py` 并重启 |
| 401 / 403 | Key / 权限 | Key 无效或无 upload 权限 | 换 `dc-uploader` 永久 Key |
| 422 | 未保存任何记录 | 模块对不上或 CSV 行被跳过 | 看响应 `skipped`；补模块或 `--module-id` |

---

## 4. 试验 B：JSON 协议（`--json`）

这条路会先把 CSV 转成 JSON，再 POST `/api/v1/qor/upload`。  
JSON 协议**强制要求 `--full-dir`**（version 从该路径派生）。

```bash
cd ~/qor_upload_trial

/opt/qor_recorder/scripts/upload_qor.sh 2 v1.0 \
  ./module_alu/module_alu_qor.csv \
  --json --full-dir /project/feint/0904/v1.0
```

`--full-dir` 换成你们真实的 run 目录；路径里要能解析出版本段（如 `v1.0`）。

**成功示例：**

```text
[INFO] 转换 ... -> JSON (使用 /opt/qor_recorder/scripts/csv_to_json.py)
[INFO] 上传 -> http://.../api/v1/qor/upload?project_id=2&version=v1.0
[INFO] HTTP 状态: 200
[OK] 上传成功
```

**失败对照：**

| HTTP | 响应 | 原因 | 处理 |
|---|---|---|---|
| 转换失败 / ImportError | 找不到 `csv_upload_paths` | 未同步 `csv_upload_paths.py` | 同步该文件后再试 |
| 400 | `$.upload.full_dir: 必填` | 没传 `--full-dir` | 补上 `--full-dir` |
| 400 | `$.records[0].module_name: 必填` | 旧 `csv_to_json.py` 不会从文件名推断 | 同步新的 `csv_to_json.py` |

模块名推断只看 **CSV 文件名**，不看 `--full-dir`，也与网页整目录模式（父目录推断）不同：

```text
./module_alu/module_alu_qor.csv  →  module_alu
```

CSV 里若已有 `module_name` 列，以列为准；`--module-name` 可覆盖文件名推断。

---

## 5. 一条命令里带齐参数（不依赖事先 export）

在工作目录：

```bash
cd ~/qor_upload_trial

QOR_API_KEY=qor_xxxxxxxxxxxxxxxx \
/opt/qor_recorder/scripts/upload_qor.sh 2 v1.0 \
  ./module_alu/module_alu_qor.csv \
  --server http://<部署机主机名或IP>:5000
```

JSON 模式：

```bash
QOR_API_KEY=qor_xxxxxxxxxxxxxxxx \
/opt/qor_recorder/scripts/upload_qor.sh 2 v1.0 \
  ./module_alu/module_alu_qor.csv \
  --server http://<部署机主机名或IP>:5000 \
  --json --full-dir /project/feint/0904/v1.0
```

---

## 6. 建议验收顺序

1. 同步 4 个文件并重启服务。  
2. 在部署机本机做试验 A（`QOR_SERVER=http://localhost:5000`）。  
3. 在用户工作目录做试验 A（改 `QOR_SERVER`）。  
4. 可选：试验 B（必须带 `--full-dir`）。  
5. 打开网页 Dashboard，确认项目 2 / `module_alu` 出现新记录；没有 Physical 数据时显示 `—` 属正常，不应再出现 `record not found`。

日常 DC 流程优先用试验 A（默认 multipart）。试验 B 仅在需要 JSON 协议时使用。
