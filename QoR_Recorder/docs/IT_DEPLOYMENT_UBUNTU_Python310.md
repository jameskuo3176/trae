# QoR Recorder 部署方案（交 IT）

| 项 | 要求 |
|---|---|
| 操作系统 | Ubuntu 22.04 LTS（推荐）/ 24.04 LTS |
| Python | **3.10.x**（`python3.10`） |
| 架构 | x86_64 |
| 对外端口 | HTTP **80**（或由 IT 指定，经 Nginx 反代） |
| 应用运行用户 | 专用系统用户 `qor`（勿用 root） |
| Node.js / Vite | **生产机不需要**；前端只部署 `dist/` 静态文件 |

本文档供 IT 一次性部署与日常运维使用。技术细节以仓库内 `deploy/README.md`、`.env.example` 为准。拷哪些文件、不拷哪些文件见 `docs/DEPLOYMENT_PACKAGE.md`。

**1.1 相对 1.0 的补充（给 IT）：** 明确 `start.sh` 只启动 Gunicorn；生产不跑 Vite；**禁止**把 `frontend-vue/node_modules`（尤其是 Windows 开发机上的）拷到 Ubuntu，只接收研发构建的 `dist/`。

---

## 1. 系统简介

**QoR Recorder** 是 IC 设计团队使用的综合质量（QoR）数据管理系统。

| 组件 | 技术 | 说明 |
|---|---|---|
| 后端 | Django 5.2 + Gunicorn | API、认证、业务逻辑；监听本机 `127.0.0.1:8000` |
| 前端 | Vue 3 **已构建静态文件**（`dist/`） | 由 Nginx 托管；**生产机不跑 Vite / Node.js** |
| 启动脚本 | `start.sh` | 只做 migrate + 启动 Gunicorn；**不会**启动前端开发服务器 |
| 主数据 | SQLite（默认） | 文件落在 `data/`；可按需改 MySQL/PostgreSQL |
| 重数据（可选） | MongoDB 7.0 | `PERSISTENCE_MODE=hybrid` 时需要 |
| 反向代理 | Nginx | 唯一对外入口；**不要**把 Gunicorn 直接暴露到公网 |

推荐生产拓扑：

```
浏览器 ──▶ Nginx(:80/:443) ──▶ Vue 静态页
                           └─▶ /api /uploads /static /health /legacy ──▶ Gunicorn(:8000)
                                                                            │
                                                               SQLite data/ + 可选 MongoDB
```

---

## 2. 部署方式选择

| 方式 | 适用场景 | 建议 |
|---|---|---|
| **A. Docker Compose** | 有 Docker、希望一键启停 | 运维成本最低，推荐 |
| **B. systemd + Nginx（本机 Python 3.10）** | 无 Docker、或公司规范要求本机服务 | 按本文第 4 节执行 |

以下默认交付路径以 **方式 B（Ubuntu + Python 3.10）** 为主；方式 A 见第 5 节。

---

## 3. 资源与网络需求

### 3.1 硬件（起步建议）

| 资源 | 最低 | 建议（10–20 人团队） |
|---|---|---|
| CPU | 2 核 | 4 核 |
| 内存 | 2 GB | 4 GB |
| 磁盘 | 20 GB | 50 GB+（含上传与备份） |
| 磁盘类型 | 任意 | SSD 更佳（SQLite / Mongo 写入） |

### 3.2 开放端口

| 端口 | 方向 | 说明 |
|---|---|---|
| 80 / 443 | 入站 | Nginx；443 需 IT 配置 TLS 证书 |
| 8000 | **仅本机** | Gunicorn，勿对网段开放 |
| 27017 | **仅本机** | MongoDB（启用 hybrid/mongo 时） |

### 3.3 出网（安装阶段）

首次装机若需从公网拉包，请临时放行：

- `pypi.org` / 公司 PyPI 镜像（pip）
- `registry.npmjs.org`（**仅研发构建机**打包前端时需要；生产 Ubuntu **不要**为装前端去开 npm）
- Ubuntu apt 源、MongoDB 官方源（若本机装 Mongo）

**生产运行期可不依赖外网**（离线 wheelhouse 方案见第 7 节）。生产机也不需要安装 Node.js / npm / Vite。

---

## 4. 方式 B：Ubuntu + Python 3.10 + systemd + Nginx

### 4.1 安装系统依赖

```bash
sudo apt update
sudo apt install -y \
  python3.10 python3.10-venv python3.10-dev \
  build-essential \
  nginx \
  git curl ca-certificates
```

确认版本：

```bash
python3.10 --version   # 期望 Python 3.10.x
```

> Django 5.2 支持 Python 3.10；请勿使用 3.9 及以下。  
> 系统包列表**不含 Node.js**。生产前端是静态文件，不需要在 Ubuntu 上安装 npm。

### 4.2 创建运行用户与目录

```bash
sudo useradd --system --home /opt/qor_recorder --shell /usr/sbin/nologin qor
sudo mkdir -p /opt/qor_recorder/{data,uploads,backups,logs,mongodbdir,staticfiles}
sudo mkdir -p /var/www/qor-recorder
```

### 4.3 放置应用代码

#### 4.3.1 后端（`/opt/qor_recorder`）

将发布包解压或克隆到 `/opt/qor_recorder`（内容对应仓库中的 `QoR_Recorder/` 目录）。

目录中应至少包含：

- `manage.py`、`django_app/`、`start.sh`
- `requirements.txt`
- `deploy/qor_recorder.service`、`deploy/nginx.conf`
- `.env.example`

**不要**把 Windows 开发机上的 `venv/`、`.venv/` 拷过来；必须在 Ubuntu 上用 Python 3.10 新建虚拟环境（见 4.4）。

#### 4.3.2 前端（只拷 `dist/`，禁止拷 `node_modules`）

生产环境的前端是 **Vite 构建后的静态文件**，由 Nginx 直接提供，**不是**开发时的热更新服务。

| 项 | IT 要做的 | 不要做的 |
|---|---|---|
| 交付物 | 只接收研发交付的 `frontend-vue/dist/` | **不要**拷贝 `frontend-vue/node_modules/`（体积常 300MB+，且 Windows 产物在 Ubuntu 上不可用） |
| 落地路径 | 将 `dist/` **内部文件**放到 `/var/www/qor-recorder/`（该目录下应能直接看到 `index.html`） | 不要把整个 `frontend-vue/` 源码放到生产机（除非另行约定在服务器上构建） |
| 运行时 | Nginx 托管静态页；API 反代到 Gunicorn | **不要**在生产机执行 `npm run dev` / 启动 Vite（端口 5173） |
| Node.js | **不需要安装** | 不要为“跑前端”去装 Node |

研发在有网络的 **构建机**（Linux 或本机构建均可，与生产 OS 无关）执行：

```bash
cd frontend-vue
npm ci
npm run build
```

然后将生成的 `dist/` 交给 IT。服务器上示例：

```bash
# 假设发布包里是 web/dist/（含 index.html 与 assets/）
sudo mkdir -p /var/www/qor-recorder
sudo cp -r /path/to/web/dist/. /var/www/qor-recorder/
sudo chown -R www-data:www-data /var/www/qor-recorder
ls -l /var/www/qor-recorder/index.html    # 必须存在，否则登录页空白
```

验收：`/var/www/qor-recorder/index.html` 存在，且通常还有 `assets/` 目录。

> 文件级清单、排除项见 `docs/DEPLOYMENT_PACKAGE.md`。  
> `start.sh` **只启动 Django/Gunicorn**，不会构建前端，也不会启动 Vite。热更新（改 `.vue` 后浏览器实时刷新）仅研发本机 `npm run dev` 使用，与 Ubuntu 生产部署无关。

```bash
sudo chown -R qor:qor /opt/qor_recorder
sudo chown -R www-data:www-data /var/www/qor-recorder
```

### 4.4 创建 Python 虚拟环境并安装依赖

```bash
sudo -u qor python3.10 -m venv /opt/qor_recorder/venv
sudo -u qor /opt/qor_recorder/venv/bin/pip install -U pip
sudo -u qor /opt/qor_recorder/venv/bin/pip install -r /opt/qor_recorder/requirements.txt
```

生产依赖（`requirements.txt`）核心包括：Django、gunicorn、pymongo、pandas、openpyxl、PyMySQL、PyYAML 等。

### 4.5 配置环境变量 `.env`

```bash
sudo -u qor cp /opt/qor_recorder/.env.example /opt/qor_recorder/.env
sudo -u qor chmod 600 /opt/qor_recorder/.env
```

**生产必须修改**（示例）：

```bash
# 生成密钥
openssl rand -hex 32
```

写入 `/opt/qor_recorder/.env`（按实际主机名/域名修改）：

```dotenv
DEBUG=0
SECRET_KEY=<上一步生成的随机串>
ENFORCE_SECRET_KEY=1
ALLOWED_HOSTS=qor.example.internal,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://qor.example.internal

HOST=127.0.0.1
PORT=8000
GUNICORN_WORKERS=3
GUNICORN_TIMEOUT=120

DB_TYPE=sqlite
PERSISTENCE_MODE=hybrid
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=qor_recorder

DATA_DIR=/opt/qor_recorder/data
UPLOAD_FOLDER=/opt/qor_recorder/uploads
BACKUP_DIR=/opt/qor_recorder/backups

FRONTEND_MODE=vue
FRONTEND_URL=/
```

HTTPS 上线后再打开：

```dotenv
SESSION_COOKIE_SECURE=1
SECURE_SSL_REDIRECT=1
# 全站 HTTPS 验证通过后再启用：
# SECURE_HSTS_SECONDS=31536000
```

说明：

- `CSRF_TRUSTED_ORIGINS` **必须带协议**（`https://...`）。
- 浏览器与 API 保持**同源**（由 Nginx 统一入口）。

#### 数据存储模式（`PERSISTENCE_MODE`）

| 模式 | 说明 | 是否需要 MongoDB |
|---|---|---|
| `orm` | 全部业务数据存 SQLite（或 MySQL/PostgreSQL），零运维 | **否** |
| `mongo` | 业务数据主存 MongoDB，SQLite 只存系统/评审配置 | **是（必须）** |
| `hybrid` | MongoDB 为主、SQLite 兜底（Docker Compose 默认） | **是（必须）** |

- 只需评估/统计、团队 < 20 人：用 `orm` + SQLite，**无需安装 MongoDB**。
- 需要 MongoDB（`mongo` / `hybrid`）：**必须先按 4.6 节准备好 MongoDB**，否则 Dashboard 等业务接口会全部 503（后端 `/health` 的 `mongo.ready` 为 `false`）。

纯 MongoDB 模式（`mongo`）的 `.env` 关键项示例：

```dotenv
DB_TYPE=mongodb
PERSISTENCE_MODE=mongo
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=qor_recorder
MONGODB_DATA_DIR=/opt/qor_recorder/mongodbdir
MONGODB_TIMEOUT_MS=2000
```

### 4.6 MongoDB 7.0 环境准备（`mongo` / `hybrid` 模式必做）

> 仅当 `PERSISTENCE_MODE` 为 `mongo` 或 `hybrid` 时需要；`orm` 模式可跳过本节。
>
> **切记**：若 `.env` 配置了 MongoDB 模式但 MongoDB 未运行，`/health` 的 `mongo.ready`
> 为 `false`，Dashboard 等业务接口会全部 503（与"Dashboard request failed"故障一致）。

#### 4.6.1 方案一：本机安装 mongod（官方 apt 源）

以 Ubuntu 22.04 LTS（jammy）/ 24.04 LTS（noble）为例，安装 MongoDB **7.0.x**。

1. 安装依赖并导入官方 GPG 公钥：

```bash
sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
```

2. 添加官方 apt 源（`<distro>` 换成 `jammy` 或 `noble`）：

```bash
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu <distro>/mongodb-org/7.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update
```

3. 安装：

```bash
sudo apt-get install -y mongodb-org
```

4. 配置数据目录与监听地址。编辑 `/etc/mongod.conf`，让数据落在应用的
   `mongodbdir`（与 `.env` 的 `MONGODB_DATA_DIR` 一致），且只监听本机：

```yaml
storage:
  dbPath: /opt/qor_recorder/mongodbdir
net:
  port: 27017
  bindIp: 127.0.0.1
```

> 若保留默认 `/var/lib/mongodb`，也**必须**把 `bindIp` 改为 `127.0.0.1`，不要对外网段开放。

```bash
sudo mkdir -p /opt/qor_recorder/mongodbdir
sudo chown -R mongodb:mongodb /opt/qor_recorder/mongodbdir
```

5. 启动并设置开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mongod
sudo systemctl status mongod
```

#### 4.6.2 方案二：Docker 运行 MongoDB（有 Docker 时最省事）

与部署方式 A（Docker Compose）配套；也可独立运行，供方式 B 使用：

```bash
mkdir -p /opt/qor_recorder/mongodbdir

docker run -d --name qor-recorder-mongo-local --restart unless-stopped \
  -p 127.0.0.1:27017:27017 \
  -v /opt/qor_recorder/mongodbdir:/data/db \
  mongo:7.0
```

要点：

- 只暴露 `127.0.0.1:27017`，**不要**映射到 `0.0.0.0`。
- `--restart unless-stopped` 保证 Docker/机器重启后自动拉起（否则会复现 Dashboard 503）。
- 使用前必须先启动 Docker（如 Docker Desktop / `systemctl start docker`），并确认容器为 `Up`。

#### 4.6.3 验证 MongoDB 已就绪

```bash
# 1) 进程状态（方案一）
systemctl is-active mongod            # 期望 active
# 或（方案二）
docker ps | grep mongo                # 期望 Up

# 2) 端口监听（两种方案通用）
ss -ltnp | grep 27017                 # 期望 LISTEN 127.0.0.1:27017

# 3) 连通性（如已装 mongosh）
mongosh --host 127.0.0.1 --port 27017 --eval "db.runCommand({ping:1})"
# 期望: { ok: 1 }

# 4) Django 健康检查（后端启动后）
curl -sS http://127.0.0.1:8000/health
# 期望: "mongo": {"enabled": true, "ready": true}
```

#### 4.6.4 常见问题（本次事故复盘）

| 现象 | 原因 | 处理 |
|---|---|---|
| `/health` 的 `mongo.ready=false`，Dashboard 全部 503 | MongoDB 未启动，或未监听 `127.0.0.1:27017` | 按 4.6.1 / 4.6.2 启动；`ss -ltnp` 确认 27017 在听 |
| MongoDB 连上但数据为空 | `MONGODB_URI` / `MONGODB_DB` 指错库，或数据目录未挂载 | 核对 `.env`；确认 `dbPath` / volume 指向含数据的目录 |
| 端口冲突 | 27017 被其他进程占用 | `ss -ltnp \| grep 27017` 定位，停止冲突进程或改端口并同步 `.env` |

### 4.7 初始化数据库与静态文件

```bash
cd /opt/qor_recorder
sudo -u qor /opt/qor_recorder/venv/bin/python manage.py migrate --noinput
sudo -u qor /opt/qor_recorder/venv/bin/python manage.py collectstatic --noinput
```

若存在多项目 SQLite 库，升级时还需（有待迁移时由研发确认后执行）：

```bash
sudo -u qor /opt/qor_recorder/venv/bin/python manage.py migrate_project_databases --check
sudo -u qor /opt/qor_recorder/venv/bin/python manage.py migrate_project_databases
```

### 4.8 注册 systemd 服务

```bash
sudo install -m 0644 /opt/qor_recorder/deploy/qor_recorder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qor_recorder
sudo systemctl status qor_recorder
sudo journalctl -u qor_recorder -f
```

服务要点（已内置于 unit 文件）：

- 用户：`qor`
- 启动：`/opt/qor_recorder/start.sh`（先 `migrate`，再 `exec gunicorn`）
- 可写目录：`data` / `uploads` / `backups` / `logs` / `mongodbdir`
- **启动脚本不会联网装包**；依赖必须预先装进 venv
- **`start.sh` 不启动 Vite、不执行 `npm`、不更新 `/var/www/qor-recorder`**。前端升级只替换该目录下的 `dist` 文件后 `reload nginx` 即可（静态资源带 hash，必要时清浏览器缓存）

### 4.9 配置 Nginx

1. 复制并修改 `deploy/nginx.conf`：将 upstream 从 `django:8000` 改为本机：

```nginx
upstream qor_django {
    server 127.0.0.1:8000;
    keepalive 16;
}
```

2. `root` 指向 Vue 静态目录（目录里必须直接有 `index.html`，不要多套一层 `dist/`）：

```nginx
root /var/www/qor-recorder;
```

3. 安装站点并启用：

```bash
sudo cp /path/to/edited-nginx.conf /etc/nginx/sites-available/qor-recorder
sudo ln -sf /etc/nginx/sites-available/qor-recorder /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # 若与 default 冲突
sudo nginx -t
sudo systemctl reload nginx
```

Nginx 需反代至少：`/api`、`/uploads/`、`/static/`、`/health`、`/legacy/`；其余走 Vue `index.html`（history 模式）。

### 4.10 验收检查

| 检查项 | 命令 / 操作 | 期望 |
|---|---|---|
| 服务状态 | `systemctl is-active qor_recorder` | `active` |
| 健康检查 | `curl -sS http://127.0.0.1:8000/health` | HTTP 200 |
| 前端静态文件 | `test -f /var/www/qor-recorder/index.html && ls /var/www/qor-recorder/assets` | `index.html` 存在，`assets/` 非空 |
| 对外入口 | 浏览器打开 `http://<服务器>/` | 出现登录页（不是空白页 / Nginx 403） |
| 未误开 Vite | `ss -ltnp \| grep 5173` | 无监听（生产不应有 Vite） |
| 部署检查 | `sudo -u qor .../python manage.py check --deploy` | 无严重报错 |
| 日志 | `journalctl -u qor_recorder -n 100` | 无反复崩溃 |

### 4.11 默认账号（首次上线必须改密）

| 用户名 | 初始密码 | 角色 |
|---|---|---|
| admin | admin@2026 | 管理员 |
| release | release@2026 | owner |
| viewer | viewer@2026 | 只读 |

首次登录会强制改密；改密前写操作会被拒绝（403）。

---

## 5. 方式 A：Docker Compose（可选）

在 `QoR_Recorder/` 目录：

```bash
cp .env.example .env
# 编辑 SECRET_KEY、ALLOWED_HOSTS、CSRF_TRUSTED_ORIGINS 等
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f django nginx mongo
```

说明：

- 对外端口：`HTTP_PORT`（默认 80）。
- 持久化目录（与 compose 同级）：`data/`、`uploads/`、`backups/`、`mongodbdir/`。
- **禁止**把 `docker compose down -v` 当作备份手段。
- 镜像默认 Python 为 3.11；若 IT 要求镜像也用 3.10，构建时指定：

```bash
docker compose build --build-arg PYTHON_IMAGE=python:3.10-slim
```

---

## 6. HTTPS / 反向代理注意点

1. TLS 建议由公司统一入口（F5 / 公司 Nginx / Certbot）终结，后端可继续 HTTP。
2. 必须正确传递 `Host`、`X-Forwarded-Proto`；**不要**把不可信的外部 `X-Forwarded-*` 原样追加。
3. 设置 `CSRF_TRUSTED_ORIGINS=https://真实域名`。
4. 启用 HTTPS 后打开 `SESSION_COOKIE_SECURE=1`。
5. **不要**把 Gunicorn `:8000` 发布到防火墙外。

---

## 7. 离线 / 内网部署

在有网、**同架构（x86_64）同 OS 族（Ubuntu）** 的构建机准备：

```bash
# Python 依赖离线包
python3.10 -m pip download -r requirements.txt -d wheelhouse/

# 目标机安装
python3.10 -m venv /opt/qor_recorder/venv
/opt/qor_recorder/venv/bin/pip install --no-index --find-links=/opt/qor_recorder/wheelhouse \
  -r /opt/qor_recorder/requirements.txt
```

前端：在构建机执行 `npm ci && npm run build`，**只把 `dist/` 内容**拷到生产机 `/var/www/qor-recorder`。

- **禁止**把 Windows 开发机的 `frontend-vue/node_modules/` 拷到 Ubuntu（体积大，且含 Windows 原生二进制，Ubuntu 上无法使用）。
- 生产机不需要 `node_modules`、不需要 Node.js。
- 若必须在内网 Ubuntu **重新构建**前端：拷源码 + `package-lock.json`，在该机执行 `npm ci` 生成 Linux 版 `node_modules`，再 `npm run build`；不要复用 Windows 的 `node_modules`。

Docker 离线：用 `docker save` / `docker load`，详见 `deploy/README.md`「Air-gapped workflow」。

---

## 8. 备份与恢复

### 8.1 必须备份的目录

| 路径 | 内容 |
|---|---|
| `/opt/qor_recorder/data` | SQLite 主库与项目库 |
| `/opt/qor_recorder/uploads` | 上传/评审文件 |
| `/opt/qor_recorder/backups` | 应用内备份 |
| `/opt/qor_recorder/mongodbdir` | Mongo 数据（若启用） |
| `/opt/qor_recorder/.env` | 配置（含密钥，按密件保管） |

### 8.2 建议策略

1. **停写后冷备**（最稳）：`systemctl stop qor_recorder`（及 mongod），打包上述目录，再启动。
2. **在线**：应用内备份 + `mongodump`（Mongo 启用时），注意与文件备份时间对齐。
3. 恢复：停服务 → 还原目录 → 启动 → 访问 `/health` 与登录页验证。

升级前务必完整备份。

---

## 9. 日常运维命令

```bash
# 启停
sudo systemctl start|stop|restart qor_recorder
sudo systemctl reload nginx

# 日志
sudo journalctl -u qor_recorder -f
sudo tail -f /var/log/nginx/error.log

# 健康
curl -sS http://127.0.0.1/health
curl -sS http://127.0.0.1:8000/health
```

升级大致流程：备份 → 更新后端代码（仍不要带 `venv`/`node_modules`）→ 用研发新构建的 `dist/` 覆盖 `/var/www/qor-recorder/` → `pip install -r requirements.txt`（或离线 wheel）→ `migrate` / 必要时 `migrate_project_databases` → `collectstatic` → `systemctl restart qor_recorder` → `systemctl reload nginx` → 验收。

回滚：还原上一版代码与备份数据目录，重启服务。

---

## 10. 交付清单（请 IT 勾选）

- [ ] Ubuntu 22.04/24.04，Python **3.10** 可用
- [ ] 已创建用户 `qor` 与目录 `/opt/qor_recorder`、`/var/www/qor-recorder`
- [ ] 前端仅为 `dist/` 产物：`/var/www/qor-recorder/index.html` 存在；**未**拷贝 `node_modules`
- [ ] 生产机未安装/未运行 Vite（无 5173 端口）
- [ ] 已安装 venv 依赖，`import django, gunicorn` 成功
- [ ] `.env` 已设置 `SECRET_KEY` / `ALLOWED_HOSTS` /（HTTPS 时）`CSRF_TRUSTED_ORIGINS`
- [ ] `qor_recorder` systemd 已 enable 且 active（`start.sh` 只起 Gunicorn）
- [ ] Nginx 反代正确，`nginx -t` 通过；`root` 直指含 `index.html` 的目录
- [ ] `curl /health` 返回 200；浏览器可打开登录页
- [ ] 防火墙仅开放 80/443；8000、27017 不对公网
- [ ] 默认账号密码已通知业务方并要求首次登录改密
- [ ] 备份路径与周期已纳入 IT 备份策略

---

## 11. 联系与参考

| 文档 | 用途 |
|---|---|
| `docs/DEPLOYMENT_PACKAGE.md` | **拷什么 / 不拷什么**（含禁止 `node_modules`） |
| `deploy/README.md` | 生产 / Docker / 离线权威说明 |
| `.env.example` | 全部环境变量说明 |
| `docs/user_guide.md` | 业务使用说明 |
| `docs/DATA_FORMAT.md` | 数据格式 |

部署问题请联系研发接口人，并附上：`systemctl status qor_recorder`、`journalctl -u qor_recorder -n 200`、`nginx -t` 输出。

---

*文档版本：1.1 | 目标环境：Ubuntu + Python 3.10 | 应用：QoR Recorder（Django + Nginx 托管 Vue `dist/`）*
