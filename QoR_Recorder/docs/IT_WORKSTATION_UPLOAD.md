# 工作机上传 QoR（IT + 工程师）

工程师在**自己的工作机**上传 CSV/JSON 到已部署的 Linux 服务器。  
**不要**在工作机 `cd /opt/qor_recorder`，也**不必**依赖完整 Django。

---

## 一次：IT 准备

### 1) 服务器侧（部署机）

- 服务已跑，且 `django_app/api/views.py` 已兼容表单字段 **`files`**（兼认 `file`），否则 multipart 会 400「缺少上传文件」。
- 创建永久上传 Key（3 步摘要，细节见 [IT_PERMANENT_UPLOAD_KEY.md](IT_PERMANENT_UPLOAD_KEY.md)）：
  1. 确保服务账户 `dc-uploader` 存在且 `must_change_password=False`
  2. 生成永久 Key（scopes: `read,upload`）写入受限文件
  3. 把 Key **安全**拷到工程师工作机（勿进 Git / 聊天）

### 2) 工作机侧（拷给工程师）

推荐只拷两样（Python 3.8+，不需要 Bash、curl、dos2unix 或第三方包）：

| 文件 | 说明 |
|------|------|
| `scripts/upload_qor_client.py` | 单文件客户端，内置 multipart、CSV→§6.5、原生 DC→§6.5 |
| `scripts/qor_upload.env.example` → 改名为 `qor_upload.env` | 填 `QOR_SERVER`、`QOR_API_KEY` |

```bash
# 编辑 qor_upload.env：
#   QOR_SERVER=http://qor.example.internal   # 或 http://10.x.x.x:5000
#   QOR_API_KEY=qor_xxxxxxxx

# Windows / Linux 均可先检查：
python upload_qor_client.py --help
# Linux 上也可以：
python3 upload_qor_client.py --help
```

脚本依次查找 `--env FILE`、`QOR_UPLOAD_ENV`、脚本同目录
`qor_upload.env`、`~/.qor_upload.env`、`~/.config/qor-recorder/upload.env`。
已设置的环境变量优先于文件，`--server` 优先级最高。配置文件只按
`KEY=VALUE` 解析，不会作为 shell 代码执行。

旧的 `upload_qor_client.sh` 仍保留并支持；已有 Linux 工作机可继续使用。
新部署优先用 Python 客户端，转换时不再需要 client kit。

---

## 每天：工程师两条命令

在**作业目录 / 工作机**执行（CSV 是本机路径）：

```bash
# 1) CSV → multipart /api/v1/upload
python3 upload_qor_client.py 2 v1.0 /path/to/module_alu_qor.csv

# 2) 原生 DC 报告 JSON（推荐写法，无需 --json）
#    脚本识别 .json 后自动走 /api/v1/qor/upload，并在本文件内转换；
#    未传 --full-dir 时使用报告里的 run.full_dir。
python3 upload_qor_client.py 3 v1.1 \
  /project/feint2/SYN/voyager/weekly/regr_20260902/main/io_d2dw2_t_work/rpts/Synthesis/Synthesis.qor_summary.json

# 3) 已有 §6.5 JSON（同样自动走 JSON 接口；没有 upload.full_dir/upload.directory 时必须补）
python3 upload_qor_client.py 2 v1.0 ./run.json --full-dir /scratch/runs/v1.0

# 4) CSV 转 JSON 再传（转换器已内置）
python3 upload_qor_client.py 2 v1.0 ./module_alu_qor.csv --json --full-dir "$PWD"

# 5) 最近的 DC 文件示例（Windows）
python upload_qor_client.py 3 v1.1 "D:\runs\io_d2dw2_t_work\rpts\Synthesis\Synthesis.qor_summary.json"

# 6) 目录元数据示例：--directory 是 --full-dir 的别名
python upload_qor_client.py 2 v1.0 .\module_alu_qor.csv --directory "D:\runs\v1.0"
```

| 场景 | 用哪个 |
|------|--------|
| 普通 QoR CSV，图省事 | 直接传 CSV（multipart） |
| 原生 DC 报告 JSON（`*.qor_summary.json`） | 直接传文件即可；`--json` 可加可不加，自动转换并读取 `run.full_dir` |
| 已有 §6.5 JSON | 直接传文件；JSON 无 `upload.full_dir` 时加 **`--full-dir`** |
| CSV 但必须走 JSON API | `--json` + `--full-dir`（转换已内置） |
| 确实要把 JSON 塞给旧 multipart 接口 | `--multipart`（不推荐，服务端会按 CSV 解析） |

说明：输入是 `.json`（或内容以 `{` 开头）时脚本自动切到 JSON 接口，`--json` 只是显式声明，
不再需要手工指定。JSON API 要求转换后的 `upload.full_dir`；原生 DC 报告会从
`run.full_dir` 或 `run.directory` 带入。历史 §6.5 文件中的 `upload.directory` 也会在
客户端/服务端入口规范化为 `upload.full_dir`。若同一对象中的两个字段都非空，它们必须
相同；值不同会返回校验错误，避免上传到错误的 run。空白 `full_dir` 会回退到非空的
`directory`。一般不要加 `--release`（由网页 Owner 发布）。

> Python 客户端直接处理 Unicode 路径与 UTF-8/UTF-8-BOM 文件，不启动 locale
> 相关子进程；终端不能显示中文时会安全转义，不影响上传内容。

### 旧命令迁移

命令参数保持一致，只需把开头替换：

```text
./upload_qor_client.sh  PROJECT VERSION FILE [options]
python3 upload_qor_client.py PROJECT VERSION FILE [options]
```

兼容选项：`--json`、`--multipart`/`--no-json`、`--module-id`、
`--full-dir`、`--release`、`--release-dir`、`--server`、`--env`。
Python 版另外支持 `--directory`（`--full-dir` 别名）、`--timeout`、
`--ca-file` 和仅用于排障的 `--insecure`。API Key 只放在 `X-API-Key`
请求头，不打印、也不放入 URL。

这里的 “directory” 是上传记录的 run 目录元数据，不表示递归扫描本机目录。
与原 `.sh` 一样，每次命令输入一个 CSV/JSON 文件；批量上传可由调用方逐文件执行。

---

## 谁装什么

| 位置 | 需要 |
|------|------|
| **工作机** | 推荐 `upload_qor_client.py` + 可选 `qor_upload.env`（SERVER/KEY）；仅需 Python 3.8+ |
| **Linux 服务器** | 完整 QoR Recorder 服务、兼容 `files` 的 views、已建 API Key；**不要**要求工程师登录服务器跑上传 |

旧脚本 `upload_qor.sh` 仍留给服务器/完整仓库场景；工作机请用本客户端。

---

## 排障

| 现象 | 处理 |
|------|------|
| 400 `缺少上传文件` | 服务器 views 未兼容 `files` → 同步并重启 |
| 400 提到 `full_dir` | 加 `--full-dir /实际/run/目录` |
| 401 | Key 错/撤销/未 export |
| cannot connect | 查 `QOR_SERVER`、网络、防火墙、服务是否在跑；必要时调大 `--timeout` |
| 422 `skipped == total`、`saved=0` | JSON 被当成 CSV 传给了 `/api/v1/upload`：去掉 `--multipart`，用新版脚本自动路由 |
| `Unable to decode the command line` / `surrogates not allowed` | 旧版 shell 客户端 + `C` locale：改用 `upload_qor_client.py` |
| HTTPS 私有 CA 报证书错误 | 优先 `--ca-file company-ca.pem`；`--insecure` 只用于临时排障 |
| `--json` + CSV 转换失败 | 检查 CSV 表头/UTF-8 编码和 `--full-dir`；Python 版不需要转换包 |
