# QoR Recorder 数据库部署指南（Ubuntu，无 Docker）

本文说明如何在 Ubuntu 22.04/24.04 上为 QoR Recorder 部署和初始化数据库。文中的应用目录默认为 `/opt/qor_recorder`，运行用户默认为 `qor`。

## 0. IT 执行前先看这里

### 0.1 到底需要安装什么

请研发先向 IT 提供最终的 `.env` 配置，IT 根据其中两个值判断：

- `DB_TYPE=sqlite`：**不用安装数据库服务**。SQLite 已由 Python 内置，IT 只需准备可写的 `/opt/qor_recorder/data` 目录。
- `DB_TYPE=sql`：必须安装 **MySQL 8**，并创建 `qor_recorder` 数据库和 `qor` 账号。
- `PERSISTENCE_MODE=orm`：不用安装 MongoDB。
- `PERSISTENCE_MODE=mongo` 或 `PERSISTENCE_MODE=hybrid`：除关系数据库外，还必须安装 **MongoDB 7**。

如果研发没有指定，先不要自行选择。建议研发从以下两种组合中确认一种：

```dotenv
# 组合 A：MySQL，不使用 MongoDB
DB_TYPE=sql
PERSISTENCE_MODE=orm
```

```dotenv
# 组合 B：MySQL + MongoDB
DB_TYPE=sql
PERSISTENCE_MODE=hybrid
```

当前代码仍会维护部分项目级 `.db` 文件，因此即使采用 MySQL，也必须保留 `/opt/qor_recorder/data` 目录并纳入备份。这不需要额外安装 SQLite 服务。

### 0.2 IT 所需权限和条件

- 一台 Ubuntu 22.04 或 24.04 服务器。
- 可执行 `sudo` 的运维账号。
- 可访问 Ubuntu、MySQL、MongoDB 软件源；离线环境需提前准备对应 DEB 包或内部 apt 镜像。
- 应用代码已放在 `/opt/qor_recorder`。
- Python 虚拟环境已放在 `/opt/qor_recorder/venv`。
- 数据库只供本机应用使用时，不开放公网端口。

先收集服务器信息：

```bash
cat /etc/os-release
uname -m
df -h /opt
free -h
```

支持的常见架构是 `x86_64`（amd64）和 `aarch64`（arm64）。如果系统版本、架构或软件源不匹配，请停止安装并把以上输出交给研发。

### 0.3 推荐执行顺序

1. 按第 2 节创建应用用户和目录。
2. 根据研发确认的组合安装 MySQL。
3. 只有使用 `mongo`/`hybrid` 时才安装 MongoDB。
4. 将研发提供的配置写入 `/opt/qor_recorder/.env`。
5. 按第 6 节运行 Django 初始化命令。
6. 按第 7 节完成验收。
7. 按第 8 节配置并测试备份。

安装过程中不要把真实密码粘贴到工单、聊天或截图中。

## 1. 选择存储方案

QoR Recorder 使用两个配置项决定数据存储方式：

- `DB_TYPE=sqlite`：关系数据使用本机 SQLite，安装最简单，适合小团队。
- `DB_TYPE=sql`：关系数据使用 MySQL/MariaDB；必须配置 `DATABASE_URL`。
- `DB_TYPE=mongodb`：系统和评审配置仍保存在 SQLite，重数据使用 MongoDB。
- `PERSISTENCE_MODE=orm`：业务数据由 Django ORM 保存，不需要 MongoDB。
- `PERSISTENCE_MODE=mongo`：重数据只写入 MongoDB。
- `PERSISTENCE_MODE=hybrid`：重数据优先使用 MongoDB，并保留 ORM 回退能力。

推荐组合：

- 小团队或单机：`DB_TYPE=sqlite` + `PERSISTENCE_MODE=orm`
- 多用户关系库：`DB_TYPE=sql` + `PERSISTENCE_MODE=orm`
- 数据量较大：`DB_TYPE=sql` + `PERSISTENCE_MODE=hybrid`，同时部署 MySQL 和 MongoDB

> `DB_TYPE` 和 `PERSISTENCE_MODE` 不是同一个概念。MySQL 主要替代关系元数据库；只有 `mongo` 或 `hybrid` 模式才要求 MongoDB 正常运行。

## 2. 通用准备

创建应用用户和可写目录：

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin qor
sudo mkdir -p /opt/qor_recorder/{data,backups,mongodbdir}
sudo chown -R qor:qor /opt/qor_recorder
sudo chmod 750 /opt/qor_recorder /opt/qor_recorder/{data,backups,mongodbdir}
```

进入项目目录并确认 Python 环境可用：

```bash
cd /opt/qor_recorder
sudo -u qor /opt/qor_recorder/venv/bin/python manage.py check
```

以下方案选择一种配置即可；需要混合存储时，同时完成 MySQL 和 MongoDB 两节。

## 3. 方案一：SQLite

SQLite 不需要安装数据库服务。编辑 `/opt/qor_recorder/.env`：

```dotenv
DB_TYPE=sqlite
PERSISTENCE_MODE=orm
DATA_DIR=/opt/qor_recorder/data
BACKUP_DIR=/opt/qor_recorder/backups
```

确保应用用户可以写入数据目录：

```bash
sudo chown -R qor:qor /opt/qor_recorder/data
sudo chmod 750 /opt/qor_recorder/data
```

主数据库默认创建为：

```text
/opt/qor_recorder/data/qor_recorder.db
```

项目数据库通常位于同一数据目录，文件名形如 `qor_p_<项目ID>.db`。

## 4. 方案二：MySQL 8

### 4.1 安装并启动 MySQL

```bash
sudo apt-get update
sudo apt-get install -y mysql-server
sudo systemctl enable --now mysql
sudo systemctl status mysql --no-pager
```

可选执行安全加固向导：

```bash
sudo mysql_secure_installation
```

### 4.2 创建数据库和专用账号

先生成一个不含 URL 保留字符的强密码。密码会写入 `.env`，请妥善保存：

```bash
openssl rand -hex 24
sudo mysql
```

在 MySQL 控制台执行以下 SQL，并将 `替换为强密码` 改为实际密码：

```sql
CREATE DATABASE qor_recorder
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'qor'@'127.0.0.1' IDENTIFIED BY '替换为强密码';
GRANT ALL PRIVILEGES ON qor_recorder.* TO 'qor'@'127.0.0.1';
FLUSH PRIVILEGES;
EXIT;
```

不要让应用使用 MySQL `root` 账号。数据库和应用在同一台服务器时，应保留 MySQL 的本机监听，不要向公网开放 3306 端口。

### 4.3 配置应用

编辑 `/opt/qor_recorder/.env`：

```dotenv
DB_TYPE=sql
PERSISTENCE_MODE=orm
DATABASE_URL=mysql+pymysql://qor:替换为强密码@127.0.0.1:3306/qor_recorder?charset=utf8mb4
DATA_DIR=/opt/qor_recorder/data
BACKUP_DIR=/opt/qor_recorder/backups
```

当前项目依赖已包含 `PyMySQL`，无需安装 `mysqlclient`。连接密码中不要直接使用 `@`、`/`、`?` 等 URL 保留字符；可以重新生成不含这些字符的密码，避免连接字符串被错误解析。

限制配置文件权限：

```bash
sudo chown qor:qor /opt/qor_recorder/.env
sudo chmod 600 /opt/qor_recorder/.env
```

验证账号能够连接：

```bash
mysql -h 127.0.0.1 -u qor -p qor_recorder \
  -e "SELECT VERSION(), DATABASE();"
```

## 5. 方案三：MongoDB 7

只有 `PERSISTENCE_MODE=mongo` 或 `PERSISTENCE_MODE=hybrid` 时才需要 MongoDB。

### 5.1 添加官方软件源

安装基础工具并导入签名密钥：

```bash
sudo apt-get update
sudo apt-get install -y curl gnupg
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
```

自动读取 Ubuntu 代号（22.04 为 `jammy`，24.04 为 `noble`）并添加软件源：

```bash
. /etc/os-release
echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/ubuntu ${VERSION_CODENAME}/mongodb-org/7.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org
```

### 5.2 配置数据目录和监听地址

```bash
sudo mkdir -p /opt/qor_recorder/mongodbdir
sudo chown -R mongodb:mongodb /opt/qor_recorder/mongodbdir
```

编辑 `/etc/mongod.conf`，确保对应配置为：

```yaml
storage:
  dbPath: /opt/qor_recorder/mongodbdir

net:
  port: 27017
  bindIp: 127.0.0.1
```

启动并设置开机自启：

```bash
sudo systemctl enable --now mongod
sudo systemctl status mongod --no-pager
```

验证 MongoDB：

```bash
mongosh --host 127.0.0.1 --port 27017 \
  --eval "db.runCommand({ping: 1})"
```

### 5.3 配置应用

仅使用 MongoDB 重数据存储：

```dotenv
DB_TYPE=mongodb
PERSISTENCE_MODE=mongo
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=qor_recorder
MONGODB_DATA_DIR=/opt/qor_recorder/mongodbdir
MONGODB_TIMEOUT_MS=2000
```

MySQL 与 MongoDB 混合部署：

```dotenv
DB_TYPE=sql
DATABASE_URL=mysql+pymysql://qor:替换为强密码@127.0.0.1:3306/qor_recorder?charset=utf8mb4
PERSISTENCE_MODE=hybrid
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=qor_recorder
MONGODB_TIMEOUT_MS=2000
```

MongoDB 未运行时，`mongo`/`hybrid` 模式下的 Dashboard 等业务接口可能返回 503。

## 6. 初始化和升级数据库

无论选择哪种方案，都由 Django migrations 创建和升级表结构，不需要手工导入 SQL 文件。

首次部署执行：

```bash
cd /opt/qor_recorder

# 加载 .env，并执行主库迁移
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate --noinput'

# 创建默认账号并检查项目数据库
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py init_default_data'

# 检查并升级已有项目数据库
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate_project_databases --check'
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate_project_databases'
```

`init_default_data` 会创建默认账号，默认密码仅用于首次登录。上线后必须立即修改，且不要在日志、工单或聊天中传播默认密码。

后续版本升级至少执行：

```bash
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate --noinput'
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate_project_databases --check'
```

确认检查结果后，再运行不带 `--check` 的项目库迁移命令。

## 7. 验证部署

检查 Django 配置和迁移状态：

```bash
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py check'
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py showmigrations'
```

启动 QoR Recorder 后检查健康接口：

```bash
curl -sS http://127.0.0.1:5000/health
```

如果启用了 MongoDB，应确认返回内容中的 Mongo 状态为 `enabled: true`、`ready: true`。

### 7.1 IT 验收清单

MySQL 部署必须满足：

- `systemctl is-active mysql` 输出 `active`。
- `mysql -h 127.0.0.1 -u qor -p qor_recorder` 可以登录。
- `python manage.py migrate --noinput` 执行成功。
- `python manage.py showmigrations` 中需要应用的迁移均显示 `[X]`。
- 3306 没有监听公网地址；仅本机使用时应连接 `127.0.0.1`。

启用 MongoDB 时还必须满足：

- `systemctl is-active mongod` 输出 `active`。
- `mongosh ... db.runCommand({ping:1})` 返回 `ok: 1`。
- 27017 监听在 `127.0.0.1`。
- 应用 `/health` 返回 MongoDB `ready: true`。

交付研发时，请提供以下输出，但必须隐藏密码和连接字符串：

```bash
systemctl is-active mysql
systemctl is-active mongod 2>/dev/null || true
ss -ltnp | grep -E '3306|27017'
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py showmigrations'
```

## 8. 备份和恢复

### 8.1 SQLite

安装 SQLite 命令行工具：

```bash
sudo apt-get install -y sqlite3
```

在线备份主库：

```bash
sudo -u qor sqlite3 /opt/qor_recorder/data/qor_recorder.db \
  ".backup '/opt/qor_recorder/backups/qor_recorder-$(date +%F-%H%M%S).db'"
```

项目库也需要逐个备份。恢复前停止应用，并保留当前数据库副本。

### 8.2 MySQL

备份：

```bash
mysqldump -h 127.0.0.1 -u qor -p \
  --single-transaction --routines --triggers qor_recorder \
  | gzip > "/opt/qor_recorder/backups/qor_recorder-$(date +%F-%H%M%S).sql.gz"
```

恢复：

```bash
gunzip -c /opt/qor_recorder/backups/qor_recorder-YYYY-MM-DD-HHMMSS.sql.gz \
  | mysql -h 127.0.0.1 -u qor -p qor_recorder
```

### 8.3 MongoDB

备份：

```bash
mongodump --uri="mongodb://127.0.0.1:27017" \
  --db=qor_recorder \
  --archive="/opt/qor_recorder/backups/qor_recorder-mongo-$(date +%F-%H%M%S).archive" \
  --gzip
```

恢复：

```bash
mongorestore --uri="mongodb://127.0.0.1:27017" \
  --db=qor_recorder \
  --archive="/opt/qor_recorder/backups/qor_recorder-mongo-YYYY-MM-DD-HHMMSS.archive" \
  --gzip --drop
```

`--drop` 会覆盖目标集合。执行恢复前应停止应用并再次确认备份文件。

## 9. 安全与运维要求

- MySQL 3306 和 MongoDB 27017 只监听内网或 `127.0.0.1`，不要直接暴露到公网。
- `.env` 权限设置为 `600`，数据库密码不要提交到 Git。
- 应用使用专用数据库账号，不使用 `root`。
- 每次升级前同时备份关系库、所有项目库和 MongoDB。
- 定期执行恢复演练；只有实际恢复验证过的文件才算有效备份。
- 使用 `systemctl enable mysql` 或 `systemctl enable mongod` 确保数据库随系统启动。

常用排查命令：

```bash
sudo systemctl status mysql --no-pager
sudo journalctl -u mysql -n 100 --no-pager
sudo systemctl status mongod --no-pager
sudo journalctl -u mongod -n 100 --no-pager
ss -ltnp | grep -E '3306|27017'
```

遇到安装失败时，IT 应向研发提供：

- `cat /etc/os-release` 和 `uname -m` 输出。
- 失败的完整命令和完整错误信息。
- `systemctl status <服务名> --no-pager` 输出。
- `journalctl -u <服务名> -n 100 --no-pager` 输出。
- 当前端口监听情况。

不要提供 `.env` 原文、数据库密码、密钥或未脱敏的 `DATABASE_URL`。

完整应用部署（Python、Gunicorn、systemd、Nginx）请继续参考 `docs/IT_DEPLOYMENT_UBUNTU_Python310.md`。
