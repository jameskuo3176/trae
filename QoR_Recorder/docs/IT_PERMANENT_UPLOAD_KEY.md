# QoR Recorder 永久上传 Key 与脚本配置（IT 操作指南）

本文用于为 DC/CI 上传脚本配置固定、永不过期的 `QOR_API_KEY`。

## 1. 适用范围与安全要求

- 永久 Key 仅用于 `scripts/upload_qor.sh`，权限固定为 `read,upload`。
- 所有 Linux/DC 用户统一使用专用服务账户 `dc-uploader` 上传，不使用个人账户、`release` 或 `admin`。
- 绑定账户必须已完成首次改密，`must_change_password=False`，否则上传会返回 403。
- Key 明文只保存在上传主机的受限配置文件中；服务器数据库仅保存哈希，无法反查明文。
- 不要把 Key 写进 Git、Makefile、构建日志、聊天记录或普通共享目录。
- 永久 Key 会持续有效，直到被撤销、删除或主数据库被重置。

### 1.1 上传账户与 Release Owner 分离

本部署采用以下固定职责：

- `dc-uploader`：仅代表自动化上传来源，所有 Linux 用户共用它的永久 Key；
- 上传记录的“上传者”显示为 `dc-uploader`；
- 项目和模块的 Release Owner 由 `config/review_hierarchy.yaml` 配置；
- Release Owner 在网页上审核并发布数据；
- 上传脚本默认**不允许使用 `--release`**，避免把发布执行人记录为 `dc-uploader`。

Linux 本地用户名与 QoR Recorder 用户名不需要一一对应。共享 Key 无法区分具体 Linux 操作人；如需辅助追踪，可在上传记录备注中附加 Linux 用户名和主机名。

推荐流程：

```text
Linux/DC 用户 → dc-uploader 永久 Key → 上传未发布数据
                                           ↓
review_hierarchy.yaml → 模块 Release Owner → 网页审核并发布
```

示例：

```yaml
projects:
  project_a:
    owner: admin
    groups:
      default:
        owner: release
        modules:
          cpu:
            release_owner: user_a
          dsp:
            release_owner: user_b
```

该配置下，Linux 上传者始终显示为 `dc-uploader`，`cpu` 的 Release Owner 显示为 `user_a`，`dsp` 的 Release Owner 显示为 `user_b`。

以下示例假设：

```text
应用目录：/opt/qor_recorder
服务用户：qor
上传账户：dc-uploader
服务器地址：https://qor.example.internal
```

请按实际环境修改账户和服务器地址。

## 2. 前置检查

创建或修正专用上传账户。该账户使用不可登录密码，只允许通过 API Key 上传：

```bash
sudo -u qor bash -lc '
cd /opt/qor_recorder
set -a
source .env
set +a
venv/bin/python -c "
import os
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\", \"django_app.settings\")
import django
django.setup()
from django_app.core.models import User
user, created = User.objects.get_or_create(username=\"dc-uploader\")
user.role = User.ROLE_OWNER
user.is_active = True
user.must_change_password = False
user.password_changed_at = None
user.set_unusable_password()
user.save(update_fields=[
    \"role\",
    \"is_active\",
    \"must_change_password\",
    \"password_changed_at\",
    \"password\",
])
print({
    \"username\": user.username,
    \"created\": created,
    \"active\": user.is_active,
    \"role\": user.role,
    \"must_change_password\": user.must_change_password,
    \"interactive_login_disabled\": not user.has_usable_password(),
})
"
'
```

必须满足：

```text
active=True
must_change_password=False
interactive_login_disabled=True
```

`dc-uploader` 不是模块负责人。`review_hierarchy.yaml` 中的 `release_owner` 仍然决定网页显示、评审和发布权限。应用 YAML 后，后续上传不会覆盖该 Release Owner。

## 3. 创建并安全保存永久 Key

### 3.1 在应用服务器准备密钥目录

```bash
sudo install -d -o qor -g qor -m 0700 /etc/qor-recorder
```

### 3.2 生成 Key 并直接写入受限文件

将 `QOR_UPLOAD_SERVER` 修改为浏览器访问 QoR Recorder 使用的实际地址：

```bash
sudo -u qor bash -lc '
cd /opt/qor_recorder
set -a
source .env
set +a

UPLOAD_USERNAME=dc-uploader \
QOR_UPLOAD_SERVER=https://qor.example.internal \
QOR_UPLOAD_ENV=/etc/qor-recorder/upload.env \
venv/bin/python -c "
import os
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\", \"django_app.settings\")
import django
django.setup()
from django_app.core.models import ApiKey, User

username = os.environ[\"UPLOAD_USERNAME\"]
server = os.environ[\"QOR_UPLOAD_SERVER\"].rstrip(\"/\")
env_path = os.environ[\"QOR_UPLOAD_ENV\"]
user = User.objects.get(username=username, is_active=True)
if user.must_change_password:
    raise SystemExit(\"账户必须先完成首次改密\")

# 同名 Key 视为轮换：先撤销旧 Key，再创建新 Key。
ApiKey.objects.filter(
    user=user,
    name=\"dc-uploader-permanent\",
    revoked=False,
).update(revoked=True)

plaintext = ApiKey.generate_key()
key = ApiKey.objects.create(
    user=user,
    key_hash=ApiKey.hash_key(plaintext),
    prefix=plaintext[:12],
    name=\"dc-uploader-permanent\",
    scopes=\"read,upload\",
    expires_at=None,
)

temporary_path = env_path + \".tmp\"
with open(temporary_path, \"w\", encoding=\"utf-8\", newline=\"\\n\") as handle:
    handle.write(f\"QOR_API_KEY={plaintext}\\n\")
    handle.write(f\"QOR_SERVER={server}\\n\")
os.chmod(temporary_path, 0o600)
os.replace(temporary_path, env_path)
print(f\"已创建永久 Key：id={key.id} prefix={key.prefix}... 文件={env_path}\")
"
'
```

检查文件权限，禁止直接打印文件内容：

```bash
sudo ls -l /etc/qor-recorder/upload.env
```

期望权限：

```text
-rw------- 1 qor qor ...
```

文件内部格式为：

```dotenv
QOR_API_KEY=qor_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
QOR_SERVER=https://qor.example.internal
```

如上传脚本运行在 DC/CI 主机，应通过公司认可的密钥传输方式，把该文件安全复制到上传主机，例如：

```text
~/.config/qor-recorder/upload.env
```

复制后设置：

```bash
chmod 600 ~/.config/qor-recorder/upload.env
```

## 4. 配置固定上传脚本

在运行上传任务的主机创建 `qor-upload`：

```bash
cat > ~/qor-upload <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

QOR_UPLOAD_ENV="${QOR_UPLOAD_ENV:-$HOME/.config/qor-recorder/upload.env}"
QOR_UPLOAD_SCRIPT="${QOR_UPLOAD_SCRIPT:-/opt/qor_recorder/scripts/upload_qor.sh}"

if [ ! -r "$QOR_UPLOAD_ENV" ]; then
    echo "[ERROR] 无法读取上传配置: $QOR_UPLOAD_ENV" >&2
    exit 1
fi
if [ ! -x "$QOR_UPLOAD_SCRIPT" ]; then
    echo "[ERROR] 上传脚本不存在或不可执行: $QOR_UPLOAD_SCRIPT" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$QOR_UPLOAD_ENV"
set +a

if [ -z "${QOR_API_KEY:-}" ] || [ -z "${QOR_SERVER:-}" ]; then
    echo "[ERROR] 配置中缺少 QOR_API_KEY 或 QOR_SERVER" >&2
    exit 1
fi

exec "$QOR_UPLOAD_SCRIPT" "$@"
EOF

chmod 700 ~/qor-upload
```

如果上传主机上的源码不在 `/opt/qor_recorder`，设置实际脚本路径：

```bash
export QOR_UPLOAD_SCRIPT=/path/to/QoR_Recorder/scripts/upload_qor.sh
```

也可以直接修改 `~/qor-upload` 中的默认路径。

## 5. 上传用法

通用格式：

```bash
~/qor-upload <project_id> <version> <报告文件> [data_type] [options]
```

推荐的 JSON 上传：

```bash
~/qor-upload 7 v1.0 /path/to/dc_report.json --json
```

CSV 上传：

```bash
~/qor-upload 7 v1.0 /path/to/qor_report.csv qor --json
```

本部署中禁止自动发布，不要添加：

```bash
--release
```

如果添加 `--release`，数据会立即发布，`released_by` 将记录为共享的 `dc-uploader`，绕过 Release Owner 的网页确认流程。

`project_id` 可在管理后台项目列表中查看。不要把项目名称误当成数字 ID。

上传前必须确认 `review_hierarchy.yaml` 已在“评审层级状态”页面应用完成。模块的 `release_owner` 以 YAML 为准，与 `dc-uploader` 无关。

## 6. 验证

先检查服务健康：

```bash
curl -fsS https://qor.example.internal/health/live
```

检查 Key 是否能通过认证。此命令不会打印完整 Key：

```bash
set -a
source ~/.config/qor-recorder/upload.env
set +a

curl -fsS \
  -H "X-API-Key: ${QOR_API_KEY}" \
  "${QOR_SERVER}/api/v1/auth/me"

unset QOR_API_KEY
```

然后使用不带 `--release` 的测试报告执行上传，并在网页中确认：

- 上传者显示为 `dc-uploader`；
- 数据状态为“未发布”；
- 模块 Release Owner 与 `review_hierarchy.yaml` 一致；
- 对应 Release Owner 登录后能够审核并发布。

## 7. 轮换或撤销

重新执行第 3.2 节会：

1. 撤销该账户名下现有的 `dc-uploader-permanent` Key；
2. 创建一个新的永久 Key；
3. 原子覆盖 `/etc/qor-recorder/upload.env`。

轮换后必须把新的 `upload.env` 安全分发到所有上传主机。旧 Key 会立即失效。

仅撤销、不创建新 Key：

```bash
sudo -u qor bash -lc '
cd /opt/qor_recorder
set -a
source .env
set +a
venv/bin/python -c "
import os
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\", \"django_app.settings\")
import django
django.setup()
from django_app.core.models import ApiKey, User
user = User.objects.get(username=\"dc-uploader\")
count = ApiKey.objects.filter(
    user=user,
    name=\"dc-uploader-permanent\",
    revoked=False,
).update(revoked=True)
print(f\"已撤销 {count} 个 Key\")
"
'
```

## 8. 常见问题

### 返回 401：API Key 无效或已撤销

- 检查上传主机是否仍使用轮换前的旧文件；
- 检查配置文件是否被截断或带有多余引号；
- 检查主数据库是否被恢复或重置；API Key 记录保存在主数据库中。

### 返回 403：请先修改密码

绑定账户仍为 `must_change_password=True`，必须先登录网页完成改密。

### 返回 403：无上传权限

- 确认 Key 的 `scopes` 包含 `upload`；
- 确认项目不是 locked、archived 或 hidden 状态。

### 网页显示的 Release Owner 变成 dc-uploader

- 检查 `review_hierarchy.yaml` 中对应模块的 `release_owner`；
- 在“管理 → 评审层级状态”重新校验并应用 YAML；
- 确认模块创建后已建立 `GlobalModule`、`ProjectModule` 和 `LegacyModuleMapping`。

### 上传后数据已经发布

检查调用参数并移除 `--release`。共享上传账户只负责上传，发布操作应由 YAML 指定的 Release Owner 在网页完成。

### 上传主机没有 `/opt/qor_recorder`

将 `scripts/upload_qor.sh`、`scripts/csv_to_json.py` 和所需 Schema 文件部署到上传主机，并通过 `QOR_UPLOAD_SCRIPT` 指向实际位置。

### Key 会不会在重启后失效

不会。`expires_at=None` 表示永不过期，Django/Gunicorn/Nginx 重启不影响 Key。主数据库和上传主机的 `upload.env` 必须纳入受控备份。
