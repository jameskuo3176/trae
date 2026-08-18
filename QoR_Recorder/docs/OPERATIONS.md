# QoR Recorder 运维与日常操作指南

> 面向部署人员与日常使用者。命令、路径、端口以当前仓库为准（Django + Gunicorn + Vue，默认端口 **8000**）。
> 数据格式细节见 [`DATA_FORMAT.md`](DATA_FORMAT.md)；生产 Compose/离线细节见 [`../deploy/README.md`](../deploy/README.md)。

**文档目录**

1. [在 Ubuntu 上部署](#1-在-ubuntu-上部署)
2. [Linux 下通过 Makefile 上传数据](#2-linux-下通过-makefile-上传数据)
3. [前台与后台操作](#3-前台与后台操作)
4. [如何可视化 DB 数据](#4-如何可视化-db-数据)
5. [后续升级流程](#5-后续升级流程)

---

## 1. 在 Ubuntu 上部署

推荐两种方式任选其一：**Docker Compose（优先）** 或 **systemd + Nginx 本机部署**。

### 1.1 前提

| 项 | 说明 |
|----|------|
| 系统 | Ubuntu 20.04+（同类 Debian 亦可） |
| 代码位置 | 仓库中的 `QoR_Recorder/`（Compose 构建上下文为上一级，以拷贝 `frontend-vue/`） |
| Python | 3.11 推荐（与 Docker 镜像一致）；本机部署需已安装 venv 依赖 |
| 端口 | 应用默认 `HOST`/`PORT` → `0.0.0.0:8000`（见 `start.sh`）；Compose 对外多为 `HTTP_PORT`（默认 **80**）经 Nginx |
| 密钥 | 生产必须设置 `SECRET_KEY`（`openssl rand -hex 32`），见 `.env.example` |

### 1.2 方式 A：Docker Compose（推荐）

在 **`QoR_Recorder/`** 目录执行：

```bash
cp .env.example .env
# 编辑 .env：至少设置 SECRET_KEY、ALLOWED_HOSTS；HTTPS 时再设 CSRF_TRUSTED_ORIGINS 等

docker compose build
docker compose up -d
docker compose ps
docker compose logs -f django nginx postgres mongo
```

要点：

- `docker-compose.yml` 的 build context 是仓库根目录（`..`），Dockerfile 为 `QoR_Recorder/Dockerfile`，这样才能打进同级的 `frontend-vue/`。
- 默认持久化为 PostgreSQL 命名卷 `postgres_data`、`mongodbdir/`、`uploads/` 和 `backups/`；`data/` 仅保留待迁移/归档的历史 SQLite。分别使用 `pg_dump`、`mongodump` 和文件备份，不要用 `docker compose down -v`。
- **默认持久化**：`DB_TYPE=sql`（PostgreSQL：用户/项目/权限/评审等元数据）+ `PERSISTENCE_MODE=mongo`（QoR 重数据）。`mongo` 模式禁止自动创建项目 SQLite；`hybrid`/`orm` 仅作迁移或回滚。
- 对外入口是 Nginx（`HTTP_PORT`，默认 80）。Django/Mongo **不映射**到宿主机端口。
- Nginx 代理 `/api`、`/uploads`、`/static`、`/health`、`/legacy/`，其余走 Vue SPA。
- 健康检查：`curl -s http://localhost/health`（或 `http://<服务器IP>/health`）。

#### 从已有 SQLite 项目库迁到 Mongo（升级到默认 `mongo` 前必做）

若历史上使用主 SQLite 和 `data/qor_p_*.db` / `*_syn_qor.db`，须在停写窗口按以下顺序迁移（命令默认 dry-run，加 `--execute` 才写入）：

```bash
# 停写；备份 data/；对目标 PostgreSQL/Mongo 分别做 pg_dump/mongodump
docker compose up -d postgres mongo
docker compose run --rm django python manage.py migrate --noinput
docker compose run --rm django python manage.py migrate_sqlite_metadata_to_postgres --source /app/data/qor_recorder.db
docker compose run --rm django python manage.py migrate_sqlite_metadata_to_postgres --source /app/data/qor_recorder.db --execute
docker compose run --rm django python manage.py migrate_project_metadata_to_postgres
docker compose run --rm django python manage.py migrate_project_metadata_to_postgres --execute
docker compose exec django python manage.py migrate_global_modules
docker compose exec django python manage.py migrate_global_modules --execute
docker compose exec django python manage.py migrate_sqlite_to_mongo
docker compose exec django python manage.py migrate_sqlite_to_mongo --execute
# 确认 .env / Compose 为 PERSISTENCE_MODE=mongo 后重启
docker compose up -d
curl -fsS http://localhost/health/ready
```

细节与回滚见 [`FINAL_MIGRATION_RUNBOOK.md`](FINAL_MIGRATION_RUNBOOK.md)。

防火墙示例（仅开放对外端口）：

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
# 若自建 HTTPS 终止在本机 Nginx，再开放 443
sudo ufw enable
sudo ufw status
```

### 1.3 方式 B：systemd + 本机 Nginx

1. 准备目录与用户（示例路径 `/opt/qor_recorder`，与 `deploy/qor_recorder.service` 一致）：

```bash
sudo useradd -r -s /sbin/nologin -M -d /opt/qor_recorder qor || true
sudo mkdir -p /opt/qor_recorder/{data,uploads,backups,logs,mongodbdir}
# 将 QoR_Recorder 内容部署到 /opt/qor_recorder（git clone / rsync 均可）
sudo chown -R qor:qor /opt/qor_recorder
```

2. 创建 venv 并安装依赖（**须联网或事先准备 wheelhouse**；`start.sh` **不会**自动 `pip install`）：

```bash
cd /opt/qor_recorder
sudo -u qor python3 -m venv venv
sudo -u qor bash -c 'source venv/bin/activate && pip install -r requirements.txt'
```

3. 配置环境：

```bash
sudo -u qor cp .env.example .env
# 编辑 .env：SECRET_KEY、ALLOWED_HOSTS、HOST=127.0.0.1、PORT=8000、DEBUG=0 等
sudo chmod 640 .env
```

4. 迁移并初始化默认账号：

```bash
sudo -u qor bash -c 'source venv/bin/activate && python manage.py migrate --noinput'
sudo -u qor bash -c 'source venv/bin/activate && python manage.py init_default_data'
```

> **注意**：仓库中**没有** `db_init.py`。请使用上面的 `manage.py` 命令。

5. 构建并放置前端（本机/systemd 路径）：

```bash
# 在能访问 npm 的机器上（仓库根目录）
cd /path/to/repo/frontend-vue
npm ci
npm run build
# 默认 FRONTEND_DIST 指向仓库根下 frontend-vue/dist；
# 若代码只部署了 QoR_Recorder，请在 .env 中设置：
# FRONTEND_DIST=/var/www/qor-recorder
# 并把 dist/ 内容拷到该目录；或用 Nginx 直接托管 dist（见 deploy/README.md）
```

6. 安装 systemd 并启动：

```bash
sudo install -m 0644 deploy/qor_recorder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qor_recorder
sudo journalctl -u qor_recorder -f
```

`start.sh` 会：加载 `.env` → `python manage.py migrate --noinput` → `exec gunicorn ... --bind ${HOST}:${PORT}`。

7. Nginx：参考 `deploy/nginx.conf`。本机部署时把 `upstream` 从 `django:8000` 改为 `127.0.0.1:8000`，再按 [`deploy/README.md`](../deploy/README.md) 配置同域反代与 CSRF。

### 1.4 首次登录与改密（必做）

出厂默认账号由 `init_default_data` 创建（若已存在则不会覆盖密码）：

| 用户名 | 出厂密码 | 角色 |
|--------|----------|------|
| admin | admin@2026 | admin |
| user | user@2026 | owner |
| release | release@2026 | owner（历史角色迁移） |
| viewer | viewer@2026 | viewer |

- 首次登录若仍使用出厂口令，会被标记 **强制改密**；改密前写操作（含 API Key 上传）返回 **403**。
- 浏览器会跳到 `/change_password/`（或 Vue 改密弹窗，视入口而定）。
- 生产环境务必改密；紧急重置可用：

```bash
EMERGENCY_RESET_ADMIN_PASSWORD=1 python manage.py init_default_data
# 终端打印 16 位随机密码；用完后取消该环境变量
```

### 1.5 常见注意点

- **不要**把 Gunicorn 直接暴露到公网；用 Nginx 终止 TLS / 反代。
- HTTPS 时设置 `CSRF_TRUSTED_ORIGINS=https://你的域名`（必须带 scheme）、`SESSION_COOKIE_SECURE=1`。
- 默认端口是 **8000**，不是历史文档里的 5000；上传脚本默认 `QOR_SERVER=http://localhost:5000`，Makefile/脚本里请显式改成实际地址（如 `http://127.0.0.1:8000` 或 `https://qor.example.com`）。
- 离线/air-gap 流程见 [`deploy/README.md`](../deploy/README.md)（镜像 `docker save/load`、`wheelhouse/`、npm offline）。

---

## 2. Linux 下通过 Makefile 上传数据

适合 DC 综合结束后在跑目录自动上传，**无需打开浏览器会话**（使用 API Key）。

### 2.1 获取 API Key（当前实现）

**现状（与代码一致）**：

- 登录接口 `POST /api/v1/auth/login` 成功后会签发一把明文 API Key（前缀 `qor_`），`scopes=read,upload`，**默认 7 天过期**。
- 浏览器登录后，前端会把该 key 存到 localStorage（Pinia persist，`qor-auth`），用于后续带 `X-API-Key` 的请求。
- 后端另有 `GET /api/v1/apikeys`（列出）、`DELETE/POST 撤销` 类接口；**Vue 管理页目前没有「API Key 管理」标签**（文档里若写「管理 → API Key」视为**未实现 UI**，见下文）。

**推荐：用 curl 登录取 key，写入文件供 Makefile 使用**（账号须已完成强制改密）：

```bash
# 将 SERVER 换成实际入口（本机直连 Gunicorn 或经 Nginx 的公网地址）
SERVER=http://127.0.0.1:8000

RESP=$(curl -sS -X POST "$SERVER/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"你的用户名","password":"你的密码"}')

echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['api_key'])" \
  > ~/.qor_api_key
chmod 600 ~/.qor_api_key

# 可选：查看过期相关元数据
curl -sS -H "X-API-Key: $(cat ~/.qor_api_key)" "$SERVER/api/v1/apikeys"
```

也可从已登录浏览器的开发者工具 → Application → Local Storage → `qor-auth` 中读取 `apiKey` 字段（同样约 7 天有效）。

过期后重新登录一次即可拿到新 key；旧 key 可调 `GET /api/v1/apikeys` 查看，需要时用撤销接口作废。

**前提**：`must_change_password=True` 时，即使持有 API Key，上传也会被拒绝，必须先改密。

### 2.2 环境变量与脚本

脚本：[`scripts/upload_qor.sh`](../scripts/upload_qor.sh)

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `QOR_API_KEY` | ✅ | — | `qor_` 开头的 key |
| `QOR_SERVER` | | `http://localhost:5000` | **请改成实际地址**（常见 `http://host:8000` 或 `https://域名`） |
| `QOR_MODULE_ID` | | — | 可选模块 ID |
| `QOR_RELEASE` | | `0` | `1` 等同 `--release` |
| `QOR_FULL_DIR` | | — | notes 的 full_dir |
| `QOR_RELEASE_DIR` | | — | qor 类型的 release_dir |

```bash
export QOR_API_KEY="$(cat ~/.qor_api_key)"
export QOR_SERVER=http://127.0.0.1:8000   # 按实际修改

# 从仓库拷贝或指定绝对路径
./scripts/upload_qor.sh <project_id> <version> <csv或json> [qor|power|violation|notes] [选项]

# 推荐 JSON 协议（CSV 会经 csv_to_json.py 转换；DC 报告 JSON 可直接识别）
./scripts/upload_qor.sh 1 v1.0 qor_report.csv --json --release
./scripts/upload_qor.sh 1 v1.0 dc_report.json --json
```

常用选项：`--release`、`--full-dir DIR`、`--release-dir DIR`、`--module-id ID`、`--server URL`、`--json`、`--keep-json FILE`。

### 2.3 Makefile 方式

1. 将 [`scripts/Makefile.example`](../scripts/Makefile.example) 复制到 DC run 目录（可改名为 `Makefile`）。
2. 编辑变量：`QOR_SERVER`、`PROJECT_ID`、`UPLOAD_SCRIPT`（指向真实的 `upload_qor.sh`）、CSV 文件名等。
3. 配置 API Key 文件（Makefile 默认读 `~/.qor_api_key`）：

```bash
echo "qor_xxxxxxxx" > ~/.qor_api_key
chmod 600 ~/.qor_api_key
```

4. 在 run 目录执行：

```bash
make check-api-key    # 检查 key 文件
make upload           # 仅 QoR（依赖 QOR_CSV 存在）
make upload-all       # QoR → 功耗 → 违例 → 备注
make release          # QoR + --release
make help
```

`upload-notes` 会把 `RUN_DIR`（默认 `$(PWD)`）作为 `--full-dir`；同目录重复上传会覆盖该 full_dir 下旧备注。

更完整的列定义与 JSON 协议见 [`DATA_FORMAT.md`](DATA_FORMAT.md) 第 2 节与 §6。

---

## 3. 前台与后台操作

### 3.1 访问入口

| 入口 | URL | 谁能用 |
|------|-----|--------|
| 登录 | `/login` | 所有人 |
| Dashboard（主可视化） | `/dashboard` | 登录用户（viewer 仅已发布数据） |
| 管理后台 | `/admin` | **admin / owner**（导航栏「管理」） |
| 周评审 Group | `/review/group` | admin / owner |
| 周评审 Project | `/review/project` | admin / owner |
| 记录详情 | `/record/<id>` | 有权限查看该记录的用户 |
| 强制改密 | `/change_password/` | `must_change_password` 用户 |
| Legacy 回滚页 | `/legacy/dashboard/` | 保留用于前端切换验证 |
| DB 管理页（可选） | `/dbadmin/` | 仅 admin，且需 `ENABLE_DB_ADMIN=1` |

生产 Compose 下浏览器访问 `http://<服务器>/`（Nginx 80）；本机调试常见 `http://127.0.0.1:8000` 或 Vite `http://localhost:5173`。

导航栏（`AppNavbar`）：Dashboard；admin/owner 另有「评审」「管理」；viewer **无**管理入口。

### 3.2 前台日常（Dashboard）

1. 登录后进入 `/dashboard`。
2. 用筛选器选项目 / 模块 / 版本 / 目录等，刷新数据。
3. 页面内能力（侧边目录可跳转）：
   - 统计与 **风险总览**
   - **DC 报告表格**（多 run 对比、变化标注、导出）
   - 视图切换：合并表 / 转置表 / 目录聚合 / 目录-模块 / **图表网格**（面积、时序、功耗、单元、饼图等）
   - 时序分析：支持多 clock 并排子图（详见用户指南图表章节）
   - 违例路径：单 run 查看 / 两 run 对比、Bus 合并
4. owner 可切换数据 scope（mine / all，以界面为准）。
5. 主题：导航栏主题按钮，按用户持久化。

### 3.3 后台日常（`/admin`）

管理页标签（以当前 `AdminView.vue` 为准）：

| 标签 | 功能摘要 |
|------|----------|
| 记录管理 | 筛选记录、发布/撤回、编辑 release_dir、删除、打开上传弹窗；下方含 Snapshot & Backup |
| 项目管理 | 新建/锁定/解锁/软删除/恢复/硬删除（硬删需确认） |
| 模块管理 | 模块 CRUD、owner / 协作者 |
| 用户管理 | 仅 **admin**：建用户、改角色、重置密码（默认 `Reset@123` + 强制改密） |
| 评审层级 | 层级相关管理（与 `config/review_hierarchy.yaml` / sync 命令配合） |

owner 通常只能看到与自己相关的记录管理能力；viewer 进不了 `/admin`。

上传也可在管理页「上传数据」完成（CSV：qor / power / violation / notes），与脚本数据类型一致。

周评审、星标、备份恢复细节见 [`WEEKLY_REVIEW_AND_RECOVERY.md`](WEEKLY_REVIEW_AND_RECOVERY.md)。

---

## 4. 如何可视化 DB 数据

以**项目内已实现能力**为主，外部 DB 工具为辅。

### 4.1 Web 前台（首选）

- **`/dashboard`**：指标图表、DC 报告对比表、目录聚合、风险面板、违例分析——日常看数入口。
- **`/record/<id>`**：单条记录详情与同 module+version 横向对比。
- **`/review/group` / `/review/project`**：周评审视图（冻结快照、星标 run、风险相对上周）。

默认 Compose 下：元数据来自 PostgreSQL；QoR 重数据来自 Mongo。历史 `qor_p_*.db` / `*_syn_qor.db` 仅作为迁移源保留，应用在 `mongo` 模式下不会新建或打开它们。

### 4.2 管理页与备份

- `/admin` → 记录列表可核对上传/发布状态。
- Snapshot & Backup：创建/校验备份；**真正恢复**须在维护窗口执行：

```bash
python manage.py restore_backup "<备份zip路径>" --verify --apply
```

Web 请求不会在线覆盖数据库。

### 4.3 可选：内置 `/dbadmin`

```bash
# .env
ENABLE_DB_ADMIN=1
# 重启服务后访问 /dbadmin/
```

- 仅 **admin** 角色。
- 可切换主库 / 各项目库，浏览表、只读 `SELECT`、按主键改删行。
- **绕过业务校验**，改生产数据前先备份。说明见 [`WEEKLY_REVIEW_AND_RECOVERY.md`](WEEKLY_REVIEW_AND_RECOVERY.md)。

### 4.4 历史 SQLite 审计

迁移期间可在停写后只读打开：

- 主库：`data/qor_recorder.db`（用户、项目元数据、API Key 等）
- 项目库：`data/qor_p_<id>.db` 或重命名后的 `*_syn_qor.db`

工具示例：`sqlite3` CLI、DB Browser for SQLite。注意 WAL 模式下请勿在应用仍写入时复制半截文件；备份请用应用备份或停写后拷贝。

日常运维使用 PostgreSQL 与 MongoDB 客户端；SQLite 工具不再是默认运行依赖。

---

## 5. 后续升级流程

升级前：备份 `data/`、`uploads/`、`backups/`，以及（若启用）Mongo 数据；记录当前镜像 tag / git commit。

### 5.1 Docker Compose

```bash
cd QoR_Recorder
# 拉取/同步新代码与 frontend-vue 后
docker compose build
docker compose up -d --build
docker compose exec django python manage.py check --deploy
docker compose ps
```

项目库 schema 核对（按需）：

```bash
docker compose exec django python manage.py migrate_project_databases --check
docker compose exec django python manage.py migrate_project_databases
```

（命令行为以当前 `manage.py` 帮助与 [`deploy/README.md`](../deploy/README.md)「Upgrade and checks」为准；含 legacy NULL 规范化时需显式 `--normalize-legacy-nulls`。）

### 5.2 systemd 本机

```bash
cd /opt/qor_recorder
sudo systemctl stop qor_recorder
# 更新代码（git pull / rsync），保留 .env 与 data/

sudo -u qor bash -c 'source venv/bin/activate && pip install -r requirements.txt'   # 或离线 wheelhouse
sudo -u qor bash -c 'source venv/bin/activate && python manage.py migrate --noinput'
sudo -u qor bash -c 'source venv/bin/activate && python manage.py init_default_data'  # 幂等补齐默认项

# 前端：在有 Node 的环境构建后同步 dist
cd /path/to/repo/frontend-vue && npm ci && npm run build
# 确保 FRONTEND_DIST 或 Nginx 根目录指向新 dist

sudo systemctl start qor_recorder
sudo journalctl -u qor_recorder -n 100 --no-pager
curl -sS http://127.0.0.1:8000/health
```

若使用本机 Nginx：`sudo nginx -t && sudo systemctl reload nginx`。

### 5.3 前端单独发版

Vue 源码仅在仓库根 **`frontend-vue/`**：

```bash
cd frontend-vue
npm ci
npm run build
```

- Compose：重建 `nginx`/`frontend-runtime` 镜像即可带上新 `dist`。
- 本机：更新 `FRONTEND_DIST` 指向的目录，或按 Nginx `root` 覆盖静态文件；Django `FRONTEND_MODE=vue` 时也可由 Django 托管该 dist。

### 5.4 回滚思路

- Compose：切回旧镜像 tag，必要时恢复协调备份的 data/uploads/mongo。
- systemd：回退代码与 DB 备份后 `systemctl start`。
- 前端紧急回滚可验证 `/legacy/dashboard/`（勿在未验收前删除 legacy 模板）。

---

## 附录：与代码不一致或「未实现」声明

| 文档/口头说法 | 实际代码 |
|---------------|----------|
| 「管理 → API Key 管理」或 `/admin#apikeys` | **Vue Admin 无此页**；key 主要靠登录签发；仅有 list/revoke API |
| `db_init.py` | **不存在**；用 `manage.py migrate` + `init_default_data` |
| 默认上传端口 `5000` | 应用默认 **8000**；脚本默认值仍为 5000，部署时必须改 `QOR_SERVER` |
| 独立「对比」导航路由 | Vue Router **无** `/compare`；对比在 Dashboard（表/图/违例）与 `/record/:id`；legacy 仍有 `/compare/` |
| `seed_demo_data.py` | Flask 时代脚本，**当前仓库不提供** |

---

*文档版本：1.0 | 与仓库对齐日期：2026-08-18*
