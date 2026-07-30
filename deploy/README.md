# QoR Recorder - Linux 部署指南 (IT 部门交接)

> 本文档面向 IT/运维人员,描述在 Linux 服务器上从零部署 QoR Recorder 的完整流程。
> 文档版本: 3.0 | 最后更新: 2026-07-30（v5.0: 三级角色模型 + 多后端切换）

---

## 目录

- [1. 系统概览](#1-系统概览)
- [2. 环境要求](#2-环境要求)
- [3. 部署架构](#3-部署架构)
- [4. 部署方式选择](#4-部署方式选择)
- [5. 方式 A: systemd 直部署 (推荐)](#5-方式-a-systemd-直部署-推荐)
- [6. 方式 B: Docker 部署](#6-方式-b-docker-部署)
- [7. Nginx 反向代理与 HTTPS](#7-nginx-反向代理与-https)
- [8. 数据库后端选择](#8-数据库后端选择)
- [9. 安全加固清单](#9-安全加固清单)
- [10. 备份与恢复](#10-备份与恢复)
- [11. 升级与回滚](#11-升级与回滚)
- [12. 监控与日志](#12-监控与日志)
- [13. 故障排查](#13-故障排查)
- [14. 交接清单](#14-交接清单)

---

## 1. 系统概览

**QoR Recorder** 是一款面向 IC 设计团队的综合质量数据管理系统,基于 Flask + SQLite/MySQL/MongoDB + ECharts 实现。

**核心特性 (v5.0)**:

- Web 化 QoR 数据采集与可视化 (项目/模块/版本维度)
- 支持 DC 流程 Makefile 自动化上传 (API Key 认证)
- 跨版本违例路径对比与 Bus 合并
- **三级角色模型**: admin / owner / viewer（v4.x 的 user / release 自动迁移为 owner）
- **模块级协作**: Module.owner_id + Module.collaborators (JSON)
- **Dashboard 违例分析**: 时钟多选, 每个 clock 并排渲染一张子图
- 数据发布管理 (单条/批量标记 is_released)
- 数据锁定 (项目结束后冻结)
- 主题定制 (6 套预设 + 自定义)
- **多数据库后端**: SQLite (默认) / MySQL/PostgreSQL / MongoDB
- **按项目分库**: 主库存系统数据, 每个项目一个独立 DB 文件

**默认账户 (v5.0, 首次登录后**必须**修改密码)**:

| 用户名     | 初始密码        | 角色     | 用途                                          |
| ---------- | --------------- | -------- | --------------------------------------------- |
| admin      | admin@2026      | admin    | 全功能管理                                    |
| release    | release@2026    | owner    | 历史发布账户, 自动迁移为 owner                |
| **viewer** | **viewer@2026** | **viewer** | **v5.0 新增, 只读, 仅看已发布数据**            |

> **强制改密机制**: 三个默认账户首次登录后, 系统强制跳转到 `/change_password` 改密, 改密之前所有上传/管理操作均被 403 拦截. 弱密码黑名单: `12345678` / `password` / `password1` / `admin123` / `qwerty123` / `11111111` / `00000000`.

---

## 2. 环境要求

### 2.1 硬件

| 资源       | 最低     | 推荐      |
| ---------- | -------- | --------- |
| CPU        | 1 核     | 2 核      |
| 内存       | 512 MB   | 1 GB      |
| 磁盘       | 5 GB     | 20 GB     |
| 网络       | 100 Mbps | 1 Gbps    |

### 2.2 操作系统

- **支持**: Ubuntu 20.04+ / Debian 11+ / CentOS 8+ / RHEL 8+ / Rocky Linux 8+
- **架构**: x86_64 / aarch64 (ARM)
- **内核**: Linux 4.18+

### 2.3 软件依赖

| 组件                | 版本      | 用途                |
| ------------------- | --------- | ------------------- |
| Python              | 3.9+      | 应用运行时          |
| pip                 | 21+       | 依赖管理             |
| nginx               | 1.18+     | 反向代理 (推荐)     |
| systemd             | 239+      | 服务管理             |
| MySQL (可选)        | 8.0+      | 高并发后端           |
| certbot (可选)      | 1.20+     | Let's Encrypt 证书   |

### 2.4 网络端口

| 端口  | 协议  | 用途                          | 是否对外  |
| ----- | ----- | ----------------------------- | --------- |
| 5000  | TCP   | QoR Recorder 应用 (默认)      | 否 (内网) |
| 80    | TCP   | Nginx HTTP (反代/重定向)       | 是        |
| 443   | TCP   | Nginx HTTPS                   | 是        |
| 3306  | TCP   | MySQL (可选)                  | 否 (内网) |

---

## 3. 部署架构

### 3.1 推荐架构 (单机生产)

```
                ┌──────────────────────────┐
   用户 ──HTTPS──▶│  Nginx (80/443)          │
                │  - TLS 终止               │
                │  - 静态资源加速           │
                │  - 请求转发               │
                └──────────┬───────────────┘
                           │ http://127.0.0.1:5000
                ┌──────────▼───────────────┐
                │  QoR Recorder (Flask)    │
                │  systemd 管理的进程       │
                │  venv 隔离依赖           │
                └──────────┬───────────────┘
                           │
                ┌──────────▼───────────────┐
                │  数据存储                  │
                │  - SQLite: /opt/.../*.db  │
                │  - MySQL: localhost:3306  │
                └──────────────────────────┘
```

### 3.2 目录规划

```
/opt/qor_recorder/                 # 应用根目录
├── app.py                          # 主应用
├── venv/                           # Python 虚拟环境
├── data/
│   └── qor_recorder.db             # SQLite 数据文件 (默认)
├── uploads/                        # 上传的 CSV 暂存
├── backups/                        # 自动/手动备份目录
├── logs/                           # 应用日志 (可选)
├── .env                            # 环境变量配置 (敏感)
└── deploy/
    ├── qor_recorder.service        # systemd 单元模板
    └── README.md                   # 本文档
```

---

## 4. 部署方式选择

| 方式         | 适用场景                | 优点                          | 缺点                  |
| ------------ | ----------------------- | ----------------------------- | --------------------- |
| **A. systemd** | 单机生产,需要轻量化     | 资源占用低,配置透明          | 需手动管理依赖与备份 |
| **B. Docker**  | 快速部署,环境隔离      | 一键启动,版本可重现          | 容器化学习成本        |
| **C. k8s**     | 多实例高可用            | 水平扩展,自动伸缩            | 复杂度最高,本指南不覆盖 |

**IT 部门建议**: 单机 20 人团队以下,优先使用 **方式 A (systemd + Nginx)**。

---

## 5. 方式 A: systemd 直部署 (推荐)

### 5.1 创建系统用户与目录

```bash
# 创建专用用户 (不可登录, 无 home)
sudo useradd -r -s /sbin/nologin -M -d /opt/qor_recorder qor

# 创建应用目录
sudo mkdir -p /opt/qor_recorder
sudo chown qor:qor /opt/qor_recorder
```

### 5.2 安装系统依赖

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
    nginx git curl ca-certificates

# CentOS / RHEL / Rocky
sudo dnf install -y python3 python3-devel python3-pip \
    nginx git curl ca-certificates

# 可选: MySQL 客户端库 (使用 MySQL 后端时)
sudo apt install -y default-libmysqlclient-dev   # Debian/Ubuntu
sudo dnf install -y mysql-devel                   # RHEL/CentOS
```

### 5.3 部署应用代码

```bash
# 方式 1: 从 Git 仓库克隆 (推荐)
sudo -u qor git clone <your-repo-url> /opt/qor_recorder

# 方式 2: 从部署包解压
sudo tar -xzf qor_recorder-<version>.tar.gz -C /opt/
sudo chown -R qor:qor /opt/qor_recorder
```

### 5.4 创建虚拟环境并安装依赖

```bash
sudo -u qor bash -c '
  cd /opt/qor_recorder
  python3 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
'
```

### 5.5 配置环境变量

```bash
# 复制模板
sudo -u qor cp /opt/qor_recorder/.env.example /opt/qor_recorder/.env

# 生成强随机 SECRET_KEY
SECRET=$(openssl rand -hex 32)
echo "SECRET_KEY=$SECRET" | sudo -u qor tee -a /opt/qor_recorder/.env

# 编辑配置
sudo -u qor vi /opt/qor_recorder/.env
```

**关键配置项** (`.env` 文件):

```bash
# 监听 (Nginx 反代时建议仅本机)
HOST=127.0.0.1
PORT=5000
DEBUG=0

# 密钥 (必须修改, 否则非 DEBUG 模式会拒绝启动)
SECRET_KEY=<openssl rand -hex 32 的输出>
ENFORCE_SECRET_KEY=1

# Session 安全 (生产环境必须配置)
SESSION_COOKIE_SECURE=1
SESSION_LIFETIME_HOURS=12

# 数据库后端 (v4.0+ 单一变量切换, 默认 sqlite)
DB_TYPE=sqlite
# DB_TYPE=sql
# DATABASE_URL=mysql+pymysql://qor:password@localhost:3306/qor_recorder?charset=utf8mb4
# DB_TYPE=mongodb
# MONGODB_URI=mongodb://localhost:27017
# MONGODB_DB=qor_recorder

# 功能开关
ENABLE_DB_ADMIN=0
```

**权限设置** (`.env` 含密钥, 必须限制):

```bash
sudo chmod 640 /opt/qor_recorder/.env
sudo chown qor:qor /opt/qor_recorder/.env
```

### 5.6 创建数据目录

```bash
sudo -u qor mkdir -p /opt/qor_recorder/{data,uploads,backups,logs}
```

### 5.7 初始化数据库

```bash
sudo -u qor bash -c '
  cd /opt/qor_recorder
  source venv/bin/activate
  python db_init.py
'
# 加演示数据 (可选, 生产环境不建议):
# python db_init.py --demo
# 验证配置 (不会写库, 仅检查):
# python db_init.py --check
```

**初始化过程会自动**:

1. 创建主库表结构 (Alembic 迁移到最新)
2. 创建默认账户: `admin` / `release` / `viewer` (均 `must_change_password=True`)
3. 创建默认 DashboardGroup
4. (可选 `--demo`) 创建 5 个 demo 项目 + 200+ 条记录

### 5.8 安装 systemd 服务

```bash
# 复制 service 文件
sudo cp /opt/qor_recorder/deploy/qor_recorder.service /etc/systemd/system/

# 检查 service 文件中的路径与用户是否匹配
sudo vi /etc/systemd/system/qor_recorder.service

# 重新加载 systemd
sudo systemctl daemon-reload

# 启用开机自启 + 立即启动
sudo systemctl enable qor_recorder
sudo systemctl start qor_recorder

# 验证状态
sudo systemctl status qor_recorder
```

### 5.9 验证应用

```bash
# 本地健康检查 (应用应返回 200)
curl http://127.0.0.1:5000/health

# 查看日志
sudo journalctl -u qor_recorder -f --since "5 min ago"
```

---

## 6. 方式 B: Docker 部署

### 6.1 Docker 版本要求

本项目使用的 Docker 特性及最低版本要求:

| 组件              | 最低版本    | 推荐版本    | 原因                                  |
| ----------------- | ----------- | ----------- | ------------------------------------- |
| Docker Engine     | 20.10+      | 24.0+       | Compose v3.8 格式 + BuildKit          |
| Docker Compose    | v2.0+       | v2.20+      | `docker compose` 子命令(非旧版独立脚本)|
| containerd        | 1.5+        | 1.7+        | Docker Engine 自带                    |
| Linux 内核        | 4.18+       | 5.10+       | overlay2 存储驱动                     |
| cgroup            | v2          | v2          | 现代发行版默认                        |

**版本检查命令**:

```bash
docker --version
# 期望: Docker version 24.x 或更高

docker compose version
# 期望: Docker Compose version v2.20.x 或更高
# 注意: 是 "docker compose" (空格), 不是 "docker-compose" (连字符)

docker info | grep -E "Storage|Cgroup"
# 期望: Storage Driver: overlay2
#       Cgroup Version: 2
```

> **旧版 `docker-compose` (Python 实现,带连字符) 已停止维护**,本指南仅支持
> 新版 `docker compose` (Go 实现,Docker CLI 插件,带空格)。若系统已装旧版,
> 建议卸载: `sudo apt remove docker-compose`。

### 6.2 安装 Docker

#### 6.2.1 Ubuntu / Debian (官方源, 推荐)

```bash
# 1. 卸载旧版本 (避免冲突)
sudo apt remove -y docker docker-engine docker.io containerd runc docker-compose

# 2. 安装依赖
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release

# 3. 添加 Docker 官方 GPG 密钥
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 4. 添加 Docker 软件源
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. 安装 Docker Engine + Compose 插件
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

# 6. 启动并设置开机自启
sudo systemctl enable --now docker

# 7. 验证
sudo docker run hello-world
sudo docker compose version
```

> **Debian 系统**: 将上述命令中的 `ubuntu` 替换为 `debian`, `$(lsb_release -cs)` 自动识别版本代号。

#### 6.2.2 CentOS / RHEL / Rocky Linux 8/9 (官方源)

```bash
# 1. 卸载旧版本
sudo dnf remove -y docker docker-client docker-client-latest \
    docker-common docker-latest docker-latest-logind docker-logind docker-engine

# 2. 添加 Docker 官方源
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo \
    https://download.docker.com/linux/centos/docker-ce.repo

# 3. 安装 (RHEL 9 / Rocky 9 需要 --enableplugin=subscription-manager 可选)
sudo dnf install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

# 4. 启动并设置开机自启
sudo systemctl enable --now docker

# 5. 验证
sudo docker run hello-world
sudo docker compose version
```

#### 6.2.3 一键脚本 (内网/离线环境慎用)

```bash
# get.docker.com 脚本适用于大多数主流发行版
curl -fsSL https://get.docker.com | sudo sh

# 启动服务
sudo systemctl enable --now docker

# 验证
sudo docker --version
sudo docker compose version
```

> 此脚本会自动识别发行版并安装最新 stable 版,但**不会安装 buildx/compose 插件**,
> 需手动补装: `sudo apt install -y docker-compose-plugin` 或 `sudo dnf install -y docker-compose-plugin`。

#### 6.2.4 离线安装 (无外网服务器)

```bash
# 在有网的机器上下载 RPM/DEB 包
# Ubuntu 示例: https://download.docker.com/linux/ubuntu/dists/<codename>/pool/stable/amd64/
# CentOS 示例: https://download.docker.com/linux/centos/<version>/x86_64/stable/Packages/

# 拷贝到目标服务器后安装
# Ubuntu/Debian:
sudo dpkg -i containerd.io_*.deb docker-ce_*.deb docker-ce-cli_*.deb \
    docker-buildx-plugin_*.deb docker-compose-plugin_*.deb

# CentOS/RHEL:
sudo rpm -ivh containerd.io-*.rpm docker-ce-*.rpm docker-ce-cli-*.rpm \
    docker-buildx-plugin-*.rpm docker-compose-plugin-*.rpm

sudo systemctl enable --now docker
```

#### 6.2.5 配置非 root 用户 (推荐)

默认只有 root 和 docker 组用户能执行 docker 命令:

```bash
# 将当前用户加入 docker 组
sudo usermod -aG docker $USER

# 重新登录或执行 newgrp 立即生效
newgrp docker

# 验证 (无需 sudo)
docker ps
```

> **安全提示**: 加入 docker 组等效于赋予 root 权限(可通过挂载宿主目录提权)。
> 生产环境建议仅让运维账号加入, 普通用户通过 sudo 调用。

#### 6.2.6 配置镜像加速与日志限制 (推荐)

```bash
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3"
  },
  "live-restore": true,
  "max-concurrent-downloads": 10,
  "max-concurrent-uploads": 5,
  "storage-driver": "overlay2",
  "userland-proxy": false
}
EOF

sudo systemctl restart docker
```

- `log-opts`: 防止容器日志无限增长撑爆磁盘
- `live-restore`: 升级 dockerd 时容器不中断
- `storage-driver`: overlay2 是现代内核推荐驱动

**国内服务器加速镜像** (可选, 加到 `daemon.json` 的 `registry-mirrors` 字段):

```json
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}
```

> 阿里云镜像加速器需登录 `cr.console.aliyun.com` 获取专属地址。

### 6.3 准备配置

```bash
cd /opt/qor_recorder

# 创建环境变量文件
cp .env.example .env
# 生成 SECRET_KEY 并写入
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
```

### 6.3 启动服务

#### 6.3.1 SQLite 模式 (简单)

```bash
docker-compose up -d

# 查看日志
docker-compose logs -f qor_recorder

# 健康检查
curl http://localhost:5000/health
```

#### 6.3.2 MySQL 模式 (生产推荐, 高并发场景)

```bash
# 创建 .env.mysql 文件
cat > .env.mysql <<EOF
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 16)
MYSQL_PASSWORD=$(openssl rand -hex 16)
SECRET_KEY=$(openssl rand -hex 32)
EOF

# 启动 (主配置 + MySQL 扩展)
docker-compose --env-file .env.mysql \
    -f docker-compose.yml \
    -f docker-compose.mysql.yml \
    up -d
```

### 6.4 数据持久化

Docker 模式下,数据持久化在以下命名卷:

| 卷名            | 挂载点        | 用途             |
| --------------- | ------------- | ---------------- |
| `qor_data`      | `/app/data`   | SQLite 数据库    |
| `qor_backups`   | `/app/backups`| 备份             |
| `qor_uploads`   | `/app/uploads`| 上传文件         |
| `qor_mysql_data`| MySQL 数据    | MySQL 数据 (可选) |

查看卷位置:

```bash
docker volume inspect qor_recorder_qor_data
```

### 6.5 Docker 维护命令

```bash
# 停止
docker-compose down

# 升级镜像
docker-compose build --no-cache qor_recorder
docker-compose up -d

# 进入容器调试
docker-compose exec qor_recorder bash

# 备份数据
docker-compose exec qor_recorder cp /app/data/qor_recorder.db /app/backups/qor_$(date +%Y%m%d).db
```

---

## 7. Nginx 反向代理与 HTTPS

### 7.1 安装并启用 Nginx

```bash
sudo apt install -y nginx      # Debian/Ubuntu
sudo dnf install -y nginx       # RHEL/CentOS
sudo systemctl enable --now nginx
```

### 7.2 配置 HTTP 反向代理

```bash
sudo tee /etc/nginx/conf.d/qor_recorder.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name qor.example.com;   # 替换为实际域名

    # 客户端上传大小 (QoR CSV 通常很小, 按需调整)
    client_max_body_size 32M;

    # 请求体缓冲
    client_body_buffer_size 128k;
    large_client_header_buffers 4 16k;

    # 反向代理到 Flask 应用
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;

        # WebSocket 兼容 (Flask 不需要, 但保留通用性)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 保留客户端真实信息
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时
        proxy_connect_timeout 30s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        # 缓冲
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 8 32k;
    }

    # 静态资源直接由 Nginx 服务 (可选, 减轻应用压力)
    location /static/ {
        alias /opt/qor_recorder/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # 安全响应头
    add_header X-Frame-Options SAMEORIGIN;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
}
EOF

sudo nginx -t
sudo systemctl reload nginx
```

### 7.3 启用 HTTPS (强烈推荐)

#### 7.3.1 使用 Let's Encrypt (公网域名)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d qor.example.com -d www.qor.example.com

# 自动续期已通过 systemd timer 配置, 手动测试:
sudo certbot renew --dry-run
```

certbot 会自动修改 Nginx 配置启用 HTTPS 并设置 301 重定向。

#### 7.3.2 使用自签证书 (内网)

```bash
# 生成自签证书
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/qor_recorder.key \
    -out /etc/nginx/ssl/qor_recorder.crt \
    -subj "/C=CN/ST=BJ/L=Beijing/O=ICDesign/CN=qor.example.com"

# 修改 Nginx 配置 (在 80 端口基础上增加 443)
sudo tee /etc/nginx/conf.d/qor_recorder.conf > /dev/null <<'EOF'
# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name qor.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name qor.example.com;

    ssl_certificate     /etc/nginx/ssl/qor_recorder.crt;
    ssl_certificate_key /etc/nginx/ssl/qor_recorder.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    client_max_body_size 32M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/qor_recorder/static/;
        expires 7d;
    }

    # 安全响应头
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options SAMEORIGIN;
    add_header X-Content-Type-Options nosniff;
}
EOF

sudo nginx -t && sudo systemctl reload nginx
```

#### 7.3.3 启用 HTTPS 后的应用配置

`.env` 中**必须**开启 Cookie Secure:

```bash
SESSION_COOKIE_SECURE=1
```

### 7.4 自定义内网域名 (如 bpfeint.qor.local)

部署后用户通常不想记 `http://10.x.x.x:5000` 这样的地址,可配置一个易记域名别名(如 `bpfeint.qor.local`)。

> **关于 `.local` 后缀**: `.local` 是 mDNS (RFC 6762) 保留 TLD。单标签 `xxx.local` 在 macOS/Avahi 上会被 mDNS 拦截。多级域名 `bpfeint.qor.local` 在 Linux/systemd-resolved 下走正常 DNS,但 macOS 可能仍先尝试 mDNS。如团队内有 macOS 用户,建议改用 `.internal`、`.lan`、`.corp` 或 `.test` 等保留 TLD。

#### 7.4.1 方案选择

| 方案             | 适用范围            | 运维成本 | 推荐度     |
| ---------------- | ------------------- | -------- | ---------- |
| A. 客户端 hosts  | 仅单机/几个开发机   | 极低     | 临时调试   |
| B. dnsmasq       | 局域网内所有客户端  | 低       | **推荐**   |
| C. 公司 DNS 服务器| 全公司              | 中       | 大企业适用 |

#### 7.4.2 方案 A: 修改客户端 hosts (最简单, 仅本机生效)

在**每个**需要访问的客户端机器上修改 hosts:

**Linux / macOS**:
```bash
sudo tee -a /etc/hosts > /dev/null <<EOF
# QoR Recorder 内网别名
10.0.1.20  bpfeint.qor.local
EOF
```

**Windows** (以管理员身份打开 PowerShell):
```powershell
Add-Content C:\Windows\System32\drivers\etc\hosts "`n10.0.1.20  bpfeint.qor.local"
```

将 `10.0.1.20` 替换为实际服务器 IP。修改后即可用 `http://bpfeint.qor.local/` 访问。

> 缺点: 每台客户端都要改一次, 不适合大规模团队。

#### 7.4.3 方案 B: dnsmasq 局域网 DNS (推荐)

在 QoR Recorder 服务器(或任意一台内网 Linux)上装 dnsmasq,客户端把 DNS 指向它即可全局生效。

**1. 安装 dnsmasq**

```bash
sudo apt install -y dnsmasq          # Debian/Ubuntu
sudo dnf install -y dnsmasq          # RHEL/CentOS
```

**2. 配置**

```bash
sudo tee /etc/dnsmasq.d/qor.conf > /dev/null <<'EOF'
# 监听内网网卡 (按需修改)
listen-address=10.0.1.20
bind-interfaces

# 上游 DNS (解析其他域名时回退)
server=10.0.1.1
server=8.8.8.8

# 域名别名映射: 域名,IP
address=/bpfeint.qor.local/10.0.1.20
# 可继续添加多个别名:
# address=/qor.local/10.0.1.20
# address=/api.qor.local/10.0.1.20

# 扩展 hosts 文件 (会读取 /etc/hosts 中的静态映射)
addn-hosts=/etc/hosts
EOF
```

**3. 启动并开机自启**

```bash
sudo systemctl enable --now dnsmasq
sudo systemctl status dnsmasq

# 验证解析 (在服务器本机)
dig @127.0.0.1 bpfeint.qor.local +short
# 应输出: 10.0.1.20
```

**4. 防火墙放行 53 端口**

```bash
sudo ufw allow 53/tcp
sudo ufw allow 53/udp
```

**5. 客户端配置 DNS**

各客户端把 DNS 服务器改为 dnsmasq 主机 IP:

- **Linux**: `nm-connection-editor` → IPv4 → DNS: `10.0.1.20`
- **Windows**: 控制面板 → 网络适配器 → IPv4 → 首选 DNS: `10.0.1.20`
- **macOS**: 系统偏好 → 网络 → DNS → 添加 `10.0.1.20`

验证:
```bash
# 在客户端执行
nslookup bpfeint.qor.local
ping bpfeint.qor.local
curl http://bpfeint.qor.local/
```

#### 7.4.4 方案 C: 公司 DNS 服务器

若公司有内网 DNS(Windows AD DNS / BIND / CoreDNS),只需添加 A 记录:

| 类型 | 主机名                 | 值          |
| ---- | ---------------------- | ----------- |
| A    | bpfeint.qor.local      | 10.0.1.20   |

联系 IT/网络管理员添加即可。

#### 7.4.5 更新 Nginx 配置 (server_name)

域名解析生效后,修改 Nginx 配置使用新域名:

```bash
sudo vi /etc/nginx/conf.d/qor_recorder.conf
# 将所有 server_name 行改为:
#   server_name bpfeint.qor.local;
sudo nginx -t && sudo systemctl reload nginx
```

如需同时支持多个别名:

```nginx
server {
    listen 80;
    server_name bpfeint.qor.local qor.local;
    # ...
}
```

#### 7.4.6 自签证书绑定新域名 (HTTPS 场景)

若已按 § 7.3.2 配置 HTTPS, 需重新生成包含新域名的证书:

```bash
# 1. 生成带 SAN 的自签证书 (现代浏览器要求 SAN, CN 已不够)
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/qor_recorder.key \
    -out /etc/nginx/ssl/qor_recorder.crt \
    -subj "/C=CN/ST=BJ/L=Beijing/O=ICDesign/CN=bpfeint.qor.local" \
    -addext "subjectAltName=DNS:bpfeint.qor.local,DNS:qor.local,IP:10.0.1.20"

# 2. 验证证书 SAN
openssl x509 -in /etc/nginx/ssl/qor_recorder.crt -text -noout | grep -A1 "Subject Alternative Name"

# 3. 重载 Nginx
sudo nginx -t && sudo systemctl reload nginx
```

> 客户端为避免证书告警, 可将 `/etc/nginx/ssl/qor_recorder.crt` 导入到各客户端的"受信任根证书"。
> 公网域名场景用 `certbot --nginx -d bpfeint.qor.local` 自动签发 Let's Encrypt 证书即可。

#### 7.4.7 验证全链路

```bash
# 1. DNS 解析
dig bpfeint.qor.local +short
# 期望: 10.0.1.20

# 2. HTTP/HTTPS 连通
curl -I http://bpfeint.qor.local/
curl -Ik https://bpfeint.qor.local/    # 若启用 HTTPS

# 3. 浏览器访问
# http://bpfeint.qor.local/  或  https://bpfeint.qor.local/
```

---

## 8. 数据库后端选择

### 8.1 三种后端对比（v4.0+）

通过单一环境变量 `DB_TYPE` 切换后端：

| 维度       | SQLite (默认)                      | MySQL / PostgreSQL               | MongoDB                            |
| ---------- | ---------------------------------- | -------------------------------- | ---------------------------------- |
| 部署难度   | 零配置, 单文件                     | 需独立服务, 配置较复杂           | 需独立服务, 副本集等运维           |
| 并发能力   | 读多写少 OK, 写锁全局              | 完整 MVCC, 高并发强              | 文档级锁, 横向扩展                 |
| 备份       | 复制文件                           | `mysqldump` / `pg_dump`          | `mongodump`                        |
| 适用规模   | < 20 人, < 10 万记录               | 20+ 人, 大数据量                 | 已有 Mongo 基础设施, 文档型        |
| 运维成本   | 极低                               | 中等                             | 中等偏高                           |
| 多项目分库 | 自动按项目分库 (`qor_p_<id>.db`) | 按项目分库 (DB 或 Schema)        | 按项目分库 (collection)            |

### 8.2 SQLite 模式 (默认, 推荐 20 人以下团队)

**零配置**: 不设置 `DB_TYPE` 即使用 `/opt/qor_recorder/data/qor_recorder.db`。

**按项目分库结构**:

```
data/
├── qor_recorder.db           # 主库 (用户/项目/API Key)
├── qor_p_1.db                # 项目 1 业务数据
├── qor_p_2.db                # 项目 2 业务数据
└── qor_p_3.db                # 项目 3 业务数据
```

- 创建新项目时自动生成 `qor_p_<id>.db`
- 项目 `status=locked` 时该文件被设为 `0444` (只读)
- 软删除项目保留 `qor_p_<id>.db`, 硬删除时才移除

**性能优化** (已在 config.py 中启用):
- WAL 模式 (读写不互斥)
- busy_timeout = 30s
- `check_same_thread=False` (多线程共享)

**手动调优** (可选, 在 `.env` 中无法直接设置, 已硬编码为最佳实践):
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA wal_autocheckpoint = 1000;
```

### 8.3 MySQL / PostgreSQL 模式 (高并发场景)

#### 8.3.1 安装 MySQL

```bash
# Ubuntu 22.04+
sudo apt install -y mysql-server
sudo systemctl enable --now mysql

# 安全初始化
sudo mysql_secure_installation
```

#### 8.3.2 创建数据库与用户

```bash
sudo mysql <<EOF
CREATE DATABASE qor_recorder
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'qor'@'localhost' IDENTIFIED BY '替换为强密码';
GRANT ALL PRIVILEGES ON qor_recorder.* TO 'qor'@'localhost';
FLUSH PRIVILEGES;
EOF
```

#### 8.3.3 配置应用连接 (v4.0+ 单一变量切换)

```bash
# 写入 .env
cat >> /opt/qor_recorder/.env <<'EOF'
DB_TYPE=sql
DATABASE_URL=mysql+pymysql://qor:替换为强密码@localhost:3306/qor_recorder?charset=utf8mb4
EOF
```

> 简写也支持: `mysql://user:pass@host:3306/db` → 自动转换为 `mysql+pymysql://`.
> PostgreSQL 同样: `postgres://user:pass@host:5432/db` → `postgresql+psycopg2://`.

#### 8.3.4 重启应用并初始化

```bash
sudo systemctl restart qor_recorder
sudo journalctl -u qor_recorder -f   # 观察启动日志
python db_init.py --check             # 验证配置
```

### 8.4 MongoDB 模式 (v4.0+)

MongoDB 模式采用**主库 SQLite + 业务库 Mongo dual-write** 架构:

- **主库** (用户/项目/API Key): SQLite, 只读回退
- **业务库** (QorRecord / ViolationPath / RunNote / Review): MongoDB, 双写
- 业务读优先 Mongo, 失败时降级到 SQLite 副本

#### 8.4.1 安装 MongoDB

```bash
# Ubuntu 22.04+ (官方源)
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
    | sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] http://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
    | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org

# 启动
sudo systemctl enable --now mongod
```

#### 8.4.2 配置应用连接

```bash
# 写入 .env
cat >> /opt/qor_recorder/.env <<'EOF'
DB_TYPE=mongodb
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=qor_recorder
EOF
```

#### 8.4.3 验证 Mongo 连接

```bash
sudo systemctl restart qor_recorder
python db_init.py --check
# 期望: DB_TYPE=mongodb, MONGODB_URI=mongodb://localhost:27017

# MongoDB shell 验证
mongosh --eval "db.qor_records.countDocuments({})"
```

### 8.5 从 SQLite 迁移到 MySQL / MongoDB

```bash
# 1. 备份当前 SQLite
sudo systemctl stop qor_recorder
sudo -u qor cp -r /opt/qor_recorder/data /opt/qor_recorder/data.bak.$(date +%Y%m%d)

# 2. 切到 MySQL (或 MongoDB) 模式
#    编辑 .env, 修改 DB_TYPE + DATABASE_URL / MONGODB_URI

# 3. 启动 (会自动建表)
sudo systemctl start qor_recorder
python db_init.py

# 4. 迁移数据 (历史 v3.x 单库 → v4.0+ 分库)
python migrate_to_per_project_db.py --dry-run   # 先看计划
python migrate_to_per_project_db.py
python migrate_sqlite_to_mongo.py --dry-run     # SQLite → Mongo 时
python migrate_sqlite_to_mongo.py

# 5. 验证
curl -s http://localhost/api/v1/projects
```

### 8.6 按项目分库与多后端的兼容

| 后端     | 项目库存储                                              |
|----------|---------------------------------------------------------|
| SQLite   | 每个项目一个 `qor_p_<id>.db` 文件                       |
| MySQL    | 单库多表 (`projects` + 业务表, 无分库)                  |
| MongoDB  | 单库多 collection (`projects` + `qor_records_<pid>` 等)  |

> MySQL/Mongo 模式下没有 `qor_p_<id>.db` 文件, 数据全部集中到对应后端, 跨项目查询效率更高. SQLite 模式适合单机+小团队, 业务隔离更强.

---

## 9. 安全加固清单

### 9.1 部署后必须执行

- [ ] **修改默认密码**: 登录 admin / admin@2026, 立即修改为强密码
- [ ] **修改 release 账户密码**: 登录 release / release@2026, 修改密码
- [ ] **修改 viewer 账户密码 (v5.0 新增)**: 登录 viewer / viewer@2026, 修改密码
- [ ] **生成强 SECRET_KEY**: `openssl rand -hex 32`, 写入 `.env`
- [ ] **关闭 DEBUG**: `.env` 中 `DEBUG=0`
- [ ] **启用 HTTPS**: 通过 Nginx 配置 TLS (推荐 Let's Encrypt)
- [ ] **Cookie Secure**: HTTPS 后设置 `SESSION_COOKIE_SECURE=1`
- [ ] **限制监听地址**: 反代场景下 `HOST=127.0.0.1`, 不直接暴露 5000 端口
- [ ] **关闭 DB Admin**: `ENABLE_DB_ADMIN=0` (除非确实需要可视化)
- [ ] **`.env` 权限**: `chmod 640 .env`, 仅 qor 用户可读

### 9.2 防火墙配置

```bash
# 仅开放必要端口 (假设使用 Nginx + HTTPS)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp          # SSH (建议改成非默认端口)
sudo ufw allow 80/tcp          # HTTP (重定向到 HTTPS)
sudo ufw allow 443/tcp        # HTTPS
sudo ufw enable

# 验证
sudo ufw status verbose
```

### 9.3 SELinux (RHEL/CentOS/Rocky)

```bash
# 检查状态
getenforce

# 若 enforcing, 需为自定义路径设置标签
sudo semanage fcontext -a -t httpd_sys_content_t "/opt/qor_recorder(/.*)?"
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/opt/qor_recorder/(data|uploads|backups|logs)(/.*)?"
sudo restorecon -Rv /opt/qor_recorder

# 允许 Nginx 反代
sudo setsebool -P httpd_can_network_connect 1
```

### 9.4 Fail2ban (防爆破登录)

```bash
sudo apt install -y fail2ban
sudo tee /etc/fail2ban/jail.d/qor_recorder.conf > /dev/null <<'EOF'
[qor_recorder-auth]
enabled  = true
port     = 80,443
filter   = qor_recorder
logpath  = /var/log/nginx/access.log
maxretry = 5
findtime = 600
bantime  = 3600
EOF

sudo tee /etc/fail2ban/filter.d/qor_recorder.conf > /dev/null <<'EOF'
[Definition]
failregex = <HOST>.* "POST /login HTTP/.* 4\d\d
ignoreregex =
EOF

sudo systemctl restart fail2ban
```

> 应用自身已对 `/login` 做了限流 (每 IP 每分钟 5 次), Fail2ban 作为第二道防线。

### 9.5 文件系统权限

```bash
# 应用目录: qor 用户可读写, 其他用户不可访问
sudo chmod 750 /opt/qor_recorder
sudo chown -R qor:qor /opt/qor_recorder

# 数据库文件: 仅 qor 可读写
sudo chmod 600 /opt/qor_recorder/data/qor_recorder.db
sudo chmod 700 /opt/qor_recorder/data

# 备份目录: qor 可读写
sudo chmod 700 /opt/qor_recorder/backups
```

---

## 10. 备份与恢复

### 10.1 备份策略

| 数据类型              | 备份频率   | 保留      | 位置                |
| --------------------- | ---------- | --------- | ------------------- |
| 主库 (qor_recorder.db) | 每日 02:00 | 30 天     | `backups/main/`     |
| 项目库 (qor_p_*.db)   | 项目结束时 | 永久      | `backups/projects/` |
| 上传 CSV 文件         | 每周日     | 8 周      | `backups/csv/`      |
| `.env` 配置           | 变更时     | 永久      | `backups/conf/`     |
| 完整快照              | 每月 1 号  | 6 个月    | 异地存储             |

### 10.2 SQLite 自动备份 (主库 + 项目库)

```bash
sudo tee /opt/qor_recorder/scripts/backup.sh > /dev/null <<'EOF'
#!/bin/bash
# SQLite 在线备份 (使用 .backup 命令, 不锁库)
set -e
BACKUP_DIR=/opt/qor_recorder/backups
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR/main $BACKUP_DIR/projects

cd /opt/qor_recorder
source venv/bin/activate

# 1) 主库
python -c "
from app import app, db
from sqlalchemy import text
with app.app_context():
    with db.engine.connect() as conn:
        conn.execute(text('VACUUM INTO :path'), {'path': f'$BACKUP_DIR/main/qor_$TS.db'})
        print(f'[OK] 主库已备份')
"

# 2) 项目库 (按项目分库 v4.0+)
for db_file in data/qor_p_*.db; do
    [ -e "$db_file" ] || continue
    name=$(basename "$db_file" .db)
    python -c "
import sqlite3
src = '$db_file'
dst = '$BACKUP_DIR/projects/${name}_$TS.db'
src_conn = sqlite3.connect(src)
dst_conn = sqlite3.connect(dst)
with dst_conn:
    src_conn.backup(dst_conn)
print(f'[OK] {src} -> {dst}')
"
done

# 3) 清理 30 天前的主库备份
find $BACKUP_DIR/main -name 'qor_*.db' -mtime +30 -delete
EOF

sudo chmod +x /opt/qor_recorder/scripts/backup.sh
sudo chown qor:qor /opt/qor_recorder/scripts/backup.sh

# 加入 crontab
sudo -u qor crontab -l 2>/dev/null | { cat; echo "0 2 * * * /opt/qor_recorder/scripts/backup.sh >> /opt/qor_recorder/logs/backup.log 2>&1"; } | sudo -u qor crontab -
```

### 10.3 单项目归档（项目结束时推荐）

```bash
# 单项目打包 (含项目库 + 关联上传 CSV)
PROJECT_ID=3
cd /opt/qor_recorder
tar -czf backups/project_${PROJECT_ID}_$(date +%Y%m%d).tar.gz \
    data/qor_p_${PROJECT_ID}.db* \
    uploads/ \
    --transform 's|^uploads/||'
```

### 10.4 MySQL 备份

```bash
# 手动备份
mysqldump -u qor -p qor_recorder | gzip > backups/qor_$(date +%Y%m%d).sql.gz

# 自动备份 (crontab)
echo "0 2 * * * mysqldump -u qor -p替换密码 qor_recorder | gzip > /opt/qor_recorder/backups/qor_\$(date +\%Y\%m\%d).sql.gz" | sudo -u qor crontab -
```

### 10.5 MongoDB 备份

```bash
# 手动备份
mongodump --uri="$MONGODB_URI" --db=qor_recorder --gzip \
    --archive=backups/mongo_$(date +%Y%m%d).archive

# 自动备份 (crontab)
echo "0 2 * * * mongodump --uri=\"\$MONGODB_URI\" --db=qor_recorder --gzip --archive=/opt/qor_recorder/backups/mongo_\$(date +\%Y\%m\%d).archive" \
    | sudo -u qor crontab -
```

### 10.6 恢复流程

#### 10.6.1 SQLite 恢复

```bash
# 1. 停止应用
sudo systemctl stop qor_recorder

# 2. 备份当前损坏的 DB
sudo -u qor cp /opt/qor_recorder/data/qor_recorder.db \
                /opt/qor_recorder/backups/main/broken_$(date +%s).db

# 3. 用备份覆盖
sudo -u qor cp /opt/qor_recorder/backups/main/qor_20260723_020000.db \
                /opt/qor_recorder/data/qor_recorder.db
# 项目库同理
sudo -u qor cp /opt/qor_recorder/backups/projects/qor_p_3_20260723_020000.db \
                /opt/qor_recorder/data/qor_p_3.db

# 4. 启动
sudo systemctl start qor_recorder
```

#### 10.6.2 MySQL 恢复

```bash
sudo systemctl stop qor_recorder
gunzip < backups/qor_20260723.sql.gz | mysql -u qor -p qor_recorder
sudo systemctl start qor_recorder
```

#### 10.6.3 MongoDB 恢复

```bash
sudo systemctl stop qor_recorder
mongorestore --uri="$MONGODB_URI" --gzip --archive=backups/mongo_20260723.archive
sudo systemctl start qor_recorder
```

---

## 11. 升级与回滚

### 11.1 升级流程

```bash
# 1. 备份当前状态
sudo -u qor /opt/qor_recorder/scripts/backup.sh

# 2. 备份当前应用代码 (用于回滚)
sudo cp -a /opt/qor_recorder /opt/qor_recorder.bak.$(date +%Y%m%d)

# 3. 拉取新代码
cd /opt/qor_recorder
sudo -u qor git pull

# 4. 更新依赖
sudo -u qor bash -c '
    cd /opt/qor_recorder
    source venv/bin/activate
    pip install -r requirements.txt
'

# 5. 数据库迁移 (Flask-Migrate)
sudo -u qor bash -c '
    cd /opt/qor_recorder
    source venv/bin/activate
    flask db upgrade
'

# 6. 重启
sudo systemctl restart qor_recorder

# 7. 验证
curl http://127.0.0.1:5000/health
sudo journalctl -u qor_recorder -n 50
```

### 11.2 回滚流程

```bash
# 1. 停止应用
sudo systemctl stop qor_recorder

# 2. 恢复代码
sudo rm -rf /opt/qor_recorder
sudo mv /opt/qor_recorder.bak.YYYYMMDD /opt/qor_recorder

# 3. 恢复数据库 (若升级包含 schema 变更)
#   见 10.4 恢复流程

# 4. 重启
sudo systemctl start qor_recorder
```

### 11.3 蓝绿部署 (零停机, 可选)

对于高可用要求, 可部署两套实例:

```bash
# 蓝环境 (当前): 5000 端口
# 绿环境 (新版本): 5001 端口

# 1. 部署绿环境并测试
curl http://127.0.0.1:5001/health

# 2. 切换 Nginx upstream
sudo vi /etc/nginx/conf.d/qor_recorder.conf
#   proxy_pass http://127.0.0.1:5001;  # 改为绿环境
sudo systemctl reload nginx

# 3. 观察无异常后停止蓝环境
sudo systemctl stop qor_recorder@blue
```

---

## 12. 监控与日志

### 12.1 应用日志

```bash
# 实时查看
sudo journalctl -u qor_recorder -f

# 最近 100 行
sudo journalctl -u qor_recorder -n 100

# 按时间过滤
sudo journalctl -u qor_recorder --since "2026-07-23 10:00" --until "2026-07-23 12:00"

# 按级别过滤
sudo journalctl -u qor_recorder -p err
```

### 12.2 Nginx 日志

```bash
# 访问日志
sudo tail -f /var/log/nginx/access.log

# 错误日志
sudo tail -f /var/log/nginx/error.log
```

### 12.3 系统资源监控

```bash
# 进程状态
ps aux | grep python

# 内存与 CPU
top -p $(pgrep -f "python app.py")

# 磁盘
df -h /opt/qor_recorder
du -sh /opt/qor_recorder/*

# 网络
ss -tlnp | grep -E '5000|80|443'
```

### 12.4 Prometheus + Grafana (可选)

```bash
# 安装 node_exporter (系统指标)
sudo apt install -y prometheus-node-exporter
sudo systemctl enable --now prometheus-node-exporter

# 自定义应用指标 (需在代码中接入 prometheus_client, 本指南不展开)
```

### 12.5 告警脚本 (简易)

```bash
sudo tee /opt/qor_recorder/scripts/healthcheck.sh > /dev/null <<'EOF'
#!/bin/bash
# 每 5 分钟检查一次应用健康, 异常发邮件告警
ALERT_EMAIL=ops@example.com
HOST=http://127.0.0.1:5000/health

if ! curl -sf --max-time 5 $HOST > /dev/null; then
    echo "[$(date)] QoR Recorder 健康检查失败!" | mail -s "[告警] QoR Recorder Down" $ALERT_EMAIL
    sudo systemctl restart qor_recorder
fi
EOF

sudo chmod +x /opt/qor_recorder/scripts/healthcheck.sh
echo "*/5 * * * * root /opt/qor_recorder/scripts/healthcheck.sh" | sudo tee /etc/cron.d/qor-healthcheck
```

---

## 13. 故障排查

### 13.1 服务无法启动

```bash
# 1. 查看详细错误
sudo journalctl -u qor_recorder -n 200 --no-pager

# 2. 常见原因
#   a) SECRET_KEY 未配置 → 编辑 .env, 设置随机值
#   b) 端口被占用 → ss -tlnp | grep 5000, 修改 PORT
#   c) 权限问题 → chown -R qor:qor /opt/qor_recorder
#   d) venv 损坏 → 重建虚拟环境
#   e) 数据库连接失败 → 检查 DATABASE_URL
```

### 13.2 数据库锁定 (SQLite)

**症状**: 日志出现 `sqlite3.OperationalError: database is locked`

```bash
# 1. 检查是否有人长事务
sudo -u qor sqlite3 /opt/qor_recorder/data/qor_recorder.db <<EOF
PRAGMA wal_checkpoint;
SELECT * FROM pragma_wal_checkpoint;
EOF

# 2. 重启应用 (清空所有连接)
sudo systemctl restart qor_recorder

# 3. 长期方案 → 迁移到 MySQL (见 8.4)
```

### 13.3 上传文件失败

```bash
# 检查上传目录权限
ls -ld /opt/qor_recorder/uploads
# 应为 drwx------  qor qor

# 检查 Nginx 上传大小限制
# (nginx.conf 中 client_max_body_size)

# 检查应用配置
grep MAX_CONTENT_LENGTH /opt/qor_recorder/config.py
```

### 13.4 Nginx 502 Bad Gateway

```bash
# 1. 应用是否在运行
sudo systemctl status qor_recorder

# 2. 端口是否监听
curl -v http://127.0.0.1:5000/health

# 3. SELinux 是否阻止 (RHEL 系)
sudo grep nginx /var/log/audit/audit.log | audit2allow -w
sudo setsebool -P httpd_can_network_connect 1
```

### 13.5 性能问题

```bash
# 慢查询日志 (MySQL)
sudo mysql
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 1;

# SQLite 性能分析
sudo -u qor sqlite3 /opt/qor_recorder/data/qor_recorder.db <<EOF
PRAGMA journal_mode;     -- 应为 wal
PRAGMA synchronous;      -- 应为 1 (NORMAL) 或 0 (OFF)
PRAGMA busy_timeout;     -- 应为 30000
.timer ON
SELECT COUNT(*) FROM qor_records;
EOF
```

### 13.6 日志清理

```bash
# journalctl 占用空间检查
journalctl --disk-usage

# 限制为 100MB
sudo journalctl --vacuum-size=100M

# 仅保留 7 天
sudo journalctl --vacuum-time=7d
```

---

## 14. 交接清单

部署完成后,请将以下信息交接给应用管理员 (IC 设计团队):

### 14.1 部署信息表

| 项目                  | 值                                                |
| --------------------- | ------------------------------------------------- |
| 服务器主机名          |                                                   |
| 服务器 IP             |                                                   |
| 操作系统              |                                                   |
| 部署方式              | [ ] systemd  [ ] Docker                           |
| 应用版本              | `git rev-parse HEAD`                              |
| **数据库后端 (v4.0+)** | [ ] SQLite  [ ] MySQL  [ ] MongoDB               |
| 数据库位置            | `/opt/qor_recorder/data/` 或 MySQL/MongoDB        |
| 项目库数              | `ls data/qor_p_*.db | wc -l` (SQLite 模式)        |
| 应用 URL             | `https://qor.example.com`                         |
| 管理员账号            | admin (密码: 已修改为 ______)                     |
| release 账号          | release (密码: 已修改为 ______)                   |
| **viewer 账号 (v5.0)** | viewer (密码: 已修改为 ______)                   |
| **API Key (dc-bot)** | `qor_xxxxxxxx` (创建于: ______)                   |
| 备份策略              | 每日 02:00 自动备份到 `backups/main + backups/projects` |
| 监控方式              | [ ] journalctl  [ ] Prometheus + Grafana          |
| SSL 证书有效期        | `echo | openssl s_client -connect host:443 2>/dev/null | openssl x509 -noout -dates` |
| SSL 自动续期          | [ ] certbot renew (systemd timer)                 |
| Nginx 配置位置        | `/etc/nginx/conf.d/qor_recorder.conf`             |
| systemd 服务名        | `qor_recorder`                                    |
| 日志位置              | `journalctl -u qor_recorder` + `/var/log/nginx/` |
| 备份脚本              | `/opt/qor_recorder/scripts/backup.sh`             |
| 健康检查              | `/health` 端点返回 200                            |
| 文档位置              | `/opt/qor_recorder/docs/`                         |

### 14.2 常用运维命令速查

```bash
# 服务管理
sudo systemctl start|stop|restart|status qor_recorder
sudo systemctl enable|disable qor_recorder

# 日志
sudo journalctl -u qor_recorder -f
sudo journalctl -u qor_recorder --since "1 hour ago"

# 数据库
sudo -u qor sqlite3 /opt/qor_recorder/data/qor_recorder.db
# 或
mysql -u qor -p qor_recorder

# 备份
sudo -u qor /opt/qor_recorder/scripts/backup.sh

# 升级
cd /opt/qor_recorder && sudo -u qor git pull
sudo -u qor bash -c 'cd /opt/qor_recorder && source venv/bin/activate && pip install -r requirements.txt && flask db upgrade'
sudo systemctl restart qor_recorder

# Nginx
sudo nginx -t && sudo systemctl reload nginx

# 防火墙
sudo ufw status
sudo ufw allow|deny <port>/tcp
```

### 14.3 交接确认

部署人员 (IT):
- [ ] 完成 5 节 (systemd) 或 6 节 (Docker) 部署
- [ ] 完成 7 节 Nginx 反代与 HTTPS 配置
- [ ] 完成 8 节数据库后端选择（SQLite / MySQL / MongoDB）
- [ ] 完成 9 节安全加固清单
- [ ] 完成 10 节自动备份配置 (主库 + 项目库)
- [ ] 完成 12.5 节健康检查告警
- [ ] 填写 14.1 部署信息表
- [ ] 移交 14.1 信息表给应用管理员

接收人员 (应用管理员):
- [ ] 修改 **admin / release / viewer** 三个默认账户密码（v5.0 三级角色）
- [ ] 验证 Web 界面访问正常
- [ ] 创建 API Key (`dc-bot`, scope=upload), 写入 DC 流程的 `~/.qor_api_key`
- [ ] 验证数据上传功能 (admin 上传一份 demo CSV)
- [ ] 创建首个项目 (按 IC 项目代号), 验证 `data/qor_p_<id>.db` 自动生成
- [ ] 创建首个模块 + 配置 owner/collaborators
- [ ] 阅读 `docs/user_guide.md` 与 `docs/DATA_FORMAT.md`
- [ ] 把 `scripts/Makefile.example` 复制到 DC run 目录, 修改变量后 `make upload-all` 验证
- [ ] 如有 viewer 客户, 创建 viewer 角色用户, 批量发布数据后用 viewer 账号验证只读

### 14.4 应用管理员的"首启 30 分钟"清单

```bash
# 1. 登录 (强制改密)
#    https://qor.example.com/login
#    admin / admin@2026  → 强密码
#    release / release@2026 → 强密码
#    viewer / viewer@2026 → 强密码

# 2. 创建 API Key (Web → 管理 → API Key → 新建)
#    name=dc-bot, scope=upload
#    保存 key 到: echo "qor_xxx" > ~/.qor_api_key && chmod 600 ~/.qor_api_key

# 3. 创建项目 (Web → 管理 → 项目 → 新建)
#    name=ChipA (与 IC 项目代号一致)
#    自动生成 /opt/qor_recorder/data/qor_p_<id>.db

# 4. 创建模块 (Web → 管理 → 项目 → 进入 → 模块)
#    name=cpu_top (与 RTL top module 一致)
#    owner=admin (或指定用户)

# 5. 测试上传 (DC 流程端)
cd /scratch/runs/cpu_v1
cp /opt/qor_recorder/scripts/Makefile.example Makefile
# 编辑 Makefile: PROJECT_ID, API_KEY_FILE
make upload-qor   # 上传 QoR
make release      # 上传并发布 (viewer 可见)

# 6. 验证 viewer
#    用 viewer 账号登录 Web
#    Dashboard 看到刚发布的数据
#    违例分析 → 选多 clock → 应看到每个 clock 一张子图
```

---

## 附录: 相关文档

| 文档                     | 位置                              | 用途                                       |
| ------------------------ | --------------------------------- | ------------------------------------------ |
| 用户使用指南             | `docs/user_guide.md`              | 面向终端用户 (admin / owner / viewer)      |
| **数据格式规范 (v5.0)**   | `docs/DATA_FORMAT.md`             | CSV 上传格式 + 部署清单 + 角色权限         |
| 开发者文档               | `docs/developer_guide.md`         | 架构与开发流程                              |
| MongoDB 迁移文档         | `docs/MIGRATION_V4.md`            | v3.x → v4.0 分库 + MongoDB 迁移步骤        |
| Docker Compose 配置      | `docker-compose.yml`              | Docker 部署                                 |
| MySQL Compose 扩展       | `docker-compose.mysql.yml`        | Docker + MySQL                              |
| systemd 服务模板         | `deploy/qor_recorder.service`      | systemd 单元文件                           |
| 自动上传脚本             | `scripts/upload_qor.sh`           | DC 流程集成                                 |
| Makefile 示例            | `scripts/Makefile.example`        | DC 流程自动化模板                           |
| 环境变量模板             | `.env.example`                    | 配置项参考 (含 DB_TYPE 切换)                |
| 迁移脚本 (单库→分库)     | `migrate_to_per_project_db.py`    | v3.x 数据迁到 v4.0+ 按项目分库              |
| 迁移脚本 (SQLite→Mongo)  | `migrate_sqlite_to_mongo.py`      | SQLite 数据迁到 MongoDB                     |
| 数据库初始化/校验         | `db_init.py`                       | `--check` 校验, `--demo` 演示数据          |
| 演示数据生成             | `seed_demo_data.py`               | 5 项目 × 200+ 条记录的演示数据              |

---

*如有部署问题,请联系部署人员或查阅 `docs/developer_guide.md` 与 `docs/DATA_FORMAT.md` 第 20 节"实际环境部署清单".*
