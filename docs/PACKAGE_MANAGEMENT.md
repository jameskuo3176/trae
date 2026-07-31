# QoR Recorder - Python 依赖 (Package) 管理方案

> 本文档是 **Python 项目** 的依赖管理规范. 项目现状:
> - 后端: Python 3.9+ / Flask / SQLAlchemy / pandas
> - 数据库驱动: PyMySQL (MySQL) / 内置 sqlite3 (SQLite) / pymongo (MongoDB, 切换后端时)
> - 前端: 仅 `static/vendor/echarts.min.js` (本地化, 零 npm 依赖)
> - 当前 `requirements.txt` 是松散版本 (`>=`), **缺少 lockfile / 哈希校验 / 拆分**
>
> 文档版本: 1.0 | 最后更新: 2026-07-30
>
> **本项目无 Node.js 依赖, 因此不涉及 npm/yarn/pnpm.** 文末附录对比了 Python 与 Node 生态工具, 方便有前端扩展时参考.

---

## 目录

1. [现状评估与目标](#1-现状评估与目标)
2. [工具选型](#2-工具选型)
3. [版本控制策略 (lockfile 方案)](#3-版本控制策略-lockfile-方案)
4. [安全管理 (漏洞扫描 + 哈希校验)](#4-安全管理-漏洞扫描--哈希校验)
5. [体积优化 (slim 镜像 + 依赖分层)](#5-体积优化-slim-镜像--依赖分层)
6. [安装与缓存策略](#6-安装与缓存策略)
7. [环境差异 (开发 / 测试 / 生产)](#7-环境差异-开发--测试--生产)
8. [CI/CD 集成](#8-cicd-集成)
9. [项目改造步骤 (零侵入迁移)](#9-项目改造步骤-零侵入迁移)
10. [常见故障排查](#10-常见故障排查)
11. [附录: Python vs Node 生态工具对照](#11-附录-python-vs-node-生态工具对照)

---

## 1. 现状评估与目标

### 1.1 现状 (问题)

| 问题                    | 风险                                                |
|-------------------------|-----------------------------------------------------|
| `Flask>=3.1.0` 松散版本  | 不同机器装的版本不一致, "在我电脑上能跑" 问题        |
| 单一 `requirements.txt`  | 生产/开发依赖混在一起, 镜像体积大                    |
| 无哈希校验              | 供应链攻击 (supply chain attack) 无防护             |
| 无 lockfile             | 升级时 breaking change 突然出现                     |
| 无漏洞扫描              | 已知 CVE 静默存在                                   |
| 无缓存复用              | 每次部署都全量下载, 慢 + 浪费流量                   |
| 无 SBOM                 | 审计 / 合规无法追溯                                 |

### 1.2 目标

| 目标               | 验收标准                                          |
|--------------------|---------------------------------------------------|
| **可复现**         | 任意机器部署后依赖版本 100% 一致                  |
| **可审计**         | 任何包都能追溯到来源 + 哈希 + 许可证              |
| **可回滚**         | 升级出错可一键回退到上一个 lockfile                |
| **安全**           | CI 自动扫描漏洞, 严重 CVE 阻止合并                |
| **轻量**           | 生产镜像无开发依赖, layer 缓存复用                |
| **快速**           | 二次部署只下载增量, 离线优先                      |

---

## 2. 工具选型

### 2.1 安装器: pip / uv

| 工具          | 速度        | 兼容性 | 适用场景                                       |
|---------------|-------------|--------|------------------------------------------------|
| `pip`         | 慢          | 标准   | 现状, 简单场景                                 |
| `uv` (推荐)   | **快 10-100x** | 兼容 pip | 新项目, CI 流水线, 镜像构建                  |
| `pip-tools`   | 中等        | 标准   | 配合 pip 做 lockfile 编译                      |
| `poetry`      | 中等        | 自有 lock | 需要一体化项目管理时                          |
| `pipenv`      | 慢          | 自有 lock | 已不推荐用于新项目                             |

**推荐组合**:
- **小团队 / 简单部署**: `pip` + `pip-tools` (门槛低)
- **大团队 / 高频部署**: `uv` + `pip-tools` (速度极致)
- **不想用 lockfile**: `pip` + `requirements.in` (手写)

### 2.2 安全扫描: pip-audit / safety

| 工具             | 数据源              | 维护方         | 适用性                |
|------------------|---------------------|----------------|-----------------------|
| `pip-audit` (推荐) | PyPI Advisory DB   | PyPA 官方      | 离线可用, 持续维护    |
| `safety`         | Safety DB           | Safety CLI     | 商业版功能更多        |
| `snyk`           | Snyk DB             | Snyk           | 商业 + 容器扫描       |
| `bandit`         | 自有规则            | PyCQA          | 静态代码, 不扫依赖    |

### 2.3 锁文件: pip-compile / uv pip compile

| 工具                          | 输出           | 兼容性      | 推荐度 |
|-------------------------------|----------------|-------------|--------|
| `pip-tools` (`pip-compile`)   | `requirements.txt` | 标准 pip | ⭐⭐⭐⭐ |
| `uv pip compile`              | `requirements.txt` | 标准 pip | ⭐⭐⭐⭐⭐ |
| `pip freeze`                  | `requirements.txt` | 标准 pip | ⭐⭐ (脏输出) |
| `poetry lock`                 | `poetry.lock`  | Poetry only | ⭐⭐⭐ |

> 本项目选择 **`uv pip compile`** 或 **`pip-tools`**, 仍输出标准 `requirements.txt` (CI 友好, 无需 Poetry 运行时).

---

## 3. 版本控制策略 (lockfile 方案)

### 3.1 双层文件: 输入文件 + lockfile

**原则**: **输入文件 (`*.in`) 手写顶层依赖, lockfile (`*.txt`) 自动生成**.

```
requirements/
├── base.in            # 生产依赖 (手写)
├── dev.in             # 开发依赖 (手写, -r base.in)
├── prod.txt           # base 的 lockfile (pip-compile 生成)
├── dev.txt            # dev 的 lockfile (pip-compile 生成)
└── README.md          # 操作说明
```

#### `base.in` (生产依赖, 8 个核心包)
```text
# 基础 Web 框架
Flask>=3.1.0,<4
Flask-Login>=0.6.3,<0.7
Flask-SQLAlchemy>=3.1.1,<4
Flask-Migrate>=4.0.0,<5
Werkzeug>=3.1.0,<4

# 数据处理
pandas>=2.1.0,<3
openpyxl>=3.1.0,<4

# 加密 (Werkzeug 密码哈希)
# Werkzeug 内部提供

# 数据库驱动 (默认 SQLite, MySQL/Mongo 按需启用)
PyMySQL>=1.1.0,<2
pymongo>=4.6.0,<5 ; sys_platform == "linux" and extra == "mongo"
```

#### `dev.in` (开发依赖, 包含测试 + lint + 安全扫描)
```text
-r base.in
# 测试
pytest>=7.4.0,<8
pytest-cov>=4.1.0
pytest-flask>=1.3.0
httpx>=0.25.0
# 代码质量
ruff>=0.1.0
mypy>=1.7.0
# 安全扫描
pip-audit>=2.6.0
# 文档
Sphinx>=7.2.0
```

### 3.2 生成 lockfile

```bash
# 1. 安装 pip-tools (一次性)
pip install -U pip-tools

# 2. 编译生产 lockfile
pip-compile --output-file=requirements/prod.txt \
            --generate-hashes \
            --strip-extras \
            requirements/base.in

# 3. 编译开发 lockfile
pip-compile --output-file=requirements/dev.txt \
            --generate-hashes \
            --strip-extras \
            requirements/dev.in
```

> **`--generate-hashes`**: 关键! 在 lockfile 中写入每个包的 SHA256 哈希, 防止供应链攻击.

### 3.3 版本控制原则

| 原则                | 做法                                                          |
|---------------------|---------------------------------------------------------------|
| **精确锁定**         | lockfile 中**不允许**使用 `>=`, 全部用 `==` 锁定               |
| **兼容升级**         | 输入文件用 `>=X.Y,<X+1` 范围, lockfile 用 `==X.Y.Z` 精确       |
| **可重现**           | 生产部署**只用 lockfile**, 不用输入文件                        |
| **定期更新**         | 每月 1 号跑 `pip-compile --upgrade` 更新 lockfile              |
| **紧急补丁**         | CVE 出现时: 改 `.in` 上限 → 重编译 → 立即部署                 |
| **回滚**             | `git revert <lockfile 更新 commit>` → 重装                    |

### 3.4 升级流程

```bash
# 1. 查看过期依赖
pip list --outdated

# 2. 升级所有 lockfile (谨慎!)
pip-compile --upgrade --output-file=requirements/prod.txt requirements/base.in
pip-compile --upgrade --output-file=requirements/dev.txt requirements/dev.in

# 3. 仅升级某个包 (推荐)
pip-compile --upgrade-package flask --output-file=requirements/prod.txt requirements/base.in

# 4. 测试
pip-sync requirements/dev.txt
pytest

# 5. 提交 PR (lockfile diff 自动展示)
git add requirements/
git commit -m "deps: bump flask 3.1.0 → 3.1.5"
```

---

## 4. 安全管理 (漏洞扫描 + 哈希校验)

### 4.1 安装时哈希校验 (Pip 默认)

```bash
# 强制使用哈希校验安装 (--require-hashes)
pip install --require-hashes -r requirements/prod.txt
```

> 当 `requirements.txt` 中含有 `--hash=sha256:...` 行时, `--require-hashes` 强制启用. **生产部署必须开启**.

### 4.2 漏洞扫描 (CI 中自动)

```bash
# 安装扫描器
pip install pip-audit

# 扫描当前环境
pip-audit

# 扫描 lockfile (不安装, 仅比对)
pip-audit -r requirements/prod.txt

# 严格模式 (严重 CVE 报错退出 1)
pip-audit --strict

# 输出 JSON (CI 集成)
pip-audit -f json -o audit.json
```

#### CI 集成示例 (`.github/workflows/audit.yml`)

```yaml
name: dependency-audit
on:
  push:
    paths: ['requirements/**']
  schedule:
    - cron: '0 6 * * 1'   # 每周一 06:00

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install pip-audit
      - run: pip-audit -r requirements/prod.txt --strict
        continue-on-error: false   # 严重 CVE 阻止合并
```

### 4.3 SBOM (软件物料清单)

```bash
# 生成 CycloneDX SBOM (合规审计用)
pip install cyclonedx-bom
cyclonedx-py environment -o sbom.json

# 或用 syft (容器层)
syft scan dir:. -o spdx-json > sbom.spdx.json
```

### 4.4 避免不安全的包

| 风险类型              | 防护                                                                |
|-----------------------|---------------------------------------------------------------------|
| **Typosquatting**     | pip ≥ 21.0 默认拒绝与已知包名相近的拼写错误                          |
| **依赖混淆**           | pip 默认只从 PyPI 拉取, 不混入私有源; 若需私有源必须显式 `--index-url` |
| **后门植入**           | 哈希校验 + lockfile 锁定版本 (即使上游被劫持, 哈希不匹配则拒绝安装)  |
| **License 问题**      | `pip-licenses` 工具扫描所有依赖许可证                                |

```bash
# 许可证扫描
pip install pip-licenses
pip-licenses --format=markdown --output-file=LICENSES.md

# 限制只允许 MIT / BSD / Apache-2.0 (脚本)
pip-licenses --fail-on="GPL;AGPL"  # GPL 出现则失败
```

---

## 5. 体积优化 (slim 镜像 + 依赖分层)

### 5.1 多阶段 Dockerfile (推荐)

```dockerfile
# ========== Stage 1: builder ==========
FROM python:3.11-slim AS builder

# 安装编译依赖 (PyMySQL 不需要, 但若换 mysqlclient 需 gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# 创建 venv 隔离依赖
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 先复制 lockfile 单独缓存 (关键!)
COPY requirements/prod.txt /tmp/req.txt
RUN pip install --no-cache-dir \
        --require-hashes \
        -r /tmp/req.txt

# ========== Stage 2: runtime ==========
FROM python:3.11-slim

# 仅安装运行时的系统库 (curl 用于健康检查)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1000 qor

# 复制 venv (剔除编译垃圾, 通常能省 100MB+)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . .

# 静态资源
RUN mkdir -p data uploads logs backups \
    && chown -R qor:qor /app

USER qor

EXPOSE 5000
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "app:app"]
```

**体积对比**:

| 镜像                        | 大小     |
|-----------------------------|----------|
| `python:3.11`               | ~1.2 GB  |
| `python:3.11-slim`          | ~180 MB  |
| `python:3.11-alpine`        | ~50 MB   |
| 多阶段 slim + 精简 venv     | **~150 MB** ✅ |
| 多阶段 alpine + musl + 静态 | **~80 MB**  ✅✅ |

> **Alpine 注意**: 很多 wheel 在 musl 上编译问题, 仅在确定全部依赖兼容时使用.

### 5.2 依赖分层缓存

Docker layer 缓存策略 — **复制顺序决定缓存粒度**:

```dockerfile
# ✅ 正确顺序: 锁定文件先, 代码后
COPY requirements/prod.txt /tmp/req.txt
RUN pip install -r /tmp/req.txt       # 这一层 99% 时间不重建
COPY . /app                            # 代码改动只重建最后一层

# ❌ 错误: 先 copy 所有代码 → 任何文件改动导致 pip 缓存失效
COPY . /app
RUN pip install -r /app/requirements/prod.txt
```

**效果**: 代码高频改动, 但 pip 安装层在 lockfile 不变时**100% 命中缓存**, 镜像构建从 3 分钟降到 5 秒.

### 5.3 移除生产不需要的包

| 不需要安装到生产              | 原因                                     |
|------------------------------|------------------------------------------|
| `pytest` / `pytest-cov`      | 测试框架                                 |
| `ruff` / `mypy` / `black`    | 代码风格 / 类型检查                      |
| `pip-audit` / `safety`       | 安全扫描只在 CI 跑                       |
| `ipython` / `ipdb`           | 交互调试                                 |
| `sphinx` / `mkdocs`          | 文档生成只在 CI 跑                       |
| `flask-debugtoolbar`         | 调试面板                                 |

→ 这就是 `base.in` vs `dev.in` 分拆的核心价值.

### 5.4 Tree-shaking 模拟 (清理无用 transitive 依赖)

```bash
# 1. 用 pipdeptree 看依赖图
pip install pipdeptree
pipdeptree --warn silence

# 2. 发现 conflict 或未用包
pipdeptree --reverse --packages flask-sqlalchemy

# 3. 若发现 `import` 了但不直接依赖的包 (如 transitively), 显式声明
# 4. 用 pipdeptree + pydeps 静态分析确定真正用到的包
```

---

## 6. 安装与缓存策略

### 6.1 pip 缓存目录

```bash
# 默认缓存位置
~/.cache/pip/                    # Linux
%LOCALAPPDATA%\pip\Cache         # Windows

# 自定义缓存 (CI 推荐)
pip install --cache-dir /var/cache/pip flask

# 离线模式 (用缓存, 不联网)
pip install --no-index --find-links=/var/cache/pip/wheels -r req.txt
```

### 6.2 预下载 wheel 加速部署

```bash
# 1. 在构建机下载所有 wheel 到本地目录
pip download --dest /opt/wheels \
             --requirement requirements/prod.txt

# 2. 在目标机离线安装
pip install --no-index --find-links=/opt/wheels \
            --requirement requirements/prod.txt
```

### 6.3 私有 PyPI 源 (公司内网)

```bash
# .pip/pip.conf (Linux: ~/.config/pip/pip.conf, Windows: %APPDATA%\pip\pip.ini)
[global]
index-url = https://pypi.yourcompany.com/simple/
extra-index-url =
    https://pypi.org/simple/        # 兜底
    https://pypi.tuna.tsinghua.edu.cn/simple/  # 国内镜像
timeout = 60
retries = 3
```

> `extra-index-url` 比 `index-url` 多一层兜底, 但**有依赖混淆风险** (同名包可能来自不同源), 生产环境推荐只配 `index-url`.

### 6.4 Docker 构建缓存 (BuildKit)

```dockerfile
# syntax=docker/dockerfile:1.7
# 启用 BuildKit 缓存挂载
FROM python:3.11-slim AS builder
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/req.txt
```

```bash
# 显式使用 registry 缓存
DOCKER_BUILDKIT=1 docker build \
    --cache-from type=registry,ref=registry.example.com/qor:cache \
    --tag qor:latest .
```

### 6.5 Kubernetes 环境分布式缓存

```yaml
# configmap 挂载 NFS 共享 pip 缓存
volumes:
  - name: pip-cache
    nfs:
      server: nfs.example.com
      path: /opt/pip-cache
volumeMounts:
  - name: pip-cache
    mountPath: /root/.cache/pip
```

---

## 7. 环境差异 (开发 / 测试 / 生产)

### 7.1 三环境对比

| 维度           | 开发 (`dev`)                    | 测试 (`test`) / CI           | 生产 (`prod`)                  |
|----------------|--------------------------------|------------------------------|--------------------------------|
| **依赖集**     | `dev.txt` (含 pytest/ruff 等)  | `dev.txt`                    | `prod.txt` (仅运行)            |
| **安装命令**   | `pip-sync dev.txt`             | `pip install -r dev.txt`     | `pip install --require-hashes -r prod.txt` |
| **哈希校验**   | 可选                            | 强制 (CI 阻断)              | **强制**                        |
| **网络**       | 允许 PyPI                       | PyPI (whitelist)            | 内网私有源 / 离线 wheel        |
| **缓存**       | 本地 `~/.cache/pip`            | CI 缓存 (actions/cache)     | 镜像 layer + BuildKit cache    |
| **DEBUG**      | `DEBUG=1`                       | `DEBUG=1`                    | `DEBUG=0`                       |
| **secret**     | `.env` 本地                     | CI secret                    | Kubernetes Secret / Vault       |
| **更新频率**   | 随时                             | PR 合并时                    | 每月 1 次窗口期 + 紧急 CVE     |
| **锁定策略**   | 跟随 `dev.txt`                  | 跟随 `dev.txt`               | 严格跟随 `prod.txt`             |

### 7.2 配置文件样例

#### `requirements/base.in` (生产基础, 见 §3.1)

#### `requirements/dev.in` (开发额外)
```text
-r base.in
pytest>=7.4.0,<8
pytest-cov>=4.1.0
pytest-flask>=1.3.0
httpx>=0.25.0
ruff>=0.1.0
mypy>=1.7.0
pip-audit>=2.6.0
Sphinx>=7.2.0
ipython>=8.0.0
ipdb>=0.13.0
```

#### `requirements/prod.txt` (生成样例片段)
```text
#
# This file is autogenerated by pip-compile with Python 3.11
# by the following command:
#
#    pip-compile --generate-hashes --strip-extras --output-file=requirements/prod.txt requirements/base.in
#
flask==3.1.5 \
    --hash=sha256:13b17f7d8d4d4e3e5a7e7c5d8a8e8e1c7e0b3e4d5c6b7a8b9c0d1e2f3a4b5c6d \
    --hash=sha256:6c6b6e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d
    # via -r requirements/base.in
flask-login==0.6.3 \
    --hash=sha256:7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d \
    # via -r requirements/base.in
flask-sqlalchemy==3.1.1 \
    --hash=sha256:1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b \
    # via -r requirements/base.in
flask-migrate==4.0.0 \
    --hash=sha256:2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c \
    # via -r requirements/base.in
werkzeug==3.1.0 \
    --hash=sha256:3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d \
    # via flask
sqlalchemy==2.0.25 \
    --hash=sha256:4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e \
    # via flask-sqlalchemy
pandas==2.1.4 \
    --hash=sha256:5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f \
    # via -r requirements/base.in
pymysql==1.1.0 \
    --hash=sha256:6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a \
    # via -r requirements/base.in
```

> 真实 lockfile 有 ~30 个包 + 哈希, 此处仅展示结构.

### 7.3 三环境部署命令速查

#### 开发环境
```bash
git clone <repo>
cd QoR_Recorder
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -U pip-tools
pip-sync requirements/dev.txt
cp .env.example .env        # 改 SECRET_KEY / DEBUG=1
flask db upgrade
python db_init.py --demo    # 可选, 加 demo 数据
flask run --debug
```

#### 测试环境 (CI)
```yaml
# .github/workflows/test.yml
- uses: actions/setup-python@v5
  with:
    python-version: '3.11'
    cache: 'pip'
    cache-dependency-path: 'requirements/dev.txt'
- run: pip install -r requirements/dev.txt
- run: pip-audit -r requirements/prod.txt --strict
- run: ruff check .
- run: pytest --cov=app --cov-report=xml
```

#### 生产环境
```bash
# 方式 A: 直接部署
cd /opt/qor_recorder
python -m venv venv
source venv/bin/activate
pip install --require-hashes -r requirements/prod.txt   # 强制哈希
flask db upgrade
sudo systemctl restart qor_recorder

# 方式 B: Docker 部署 (推荐)
docker build -t qor_recorder:1.0.0 .
docker run -d --name qor_recorder \
    -p 5000:5000 \
    --env-file .env \
    -v /opt/qor/data:/app/data \
    qor_recorder:1.0.0

# 方式 C: Kubernetes
kubectl apply -f deploy/k8s/
kubectl rollout status deployment/qor-recorder
```

---

## 8. CI/CD 集成

### 8.1 GitHub Actions 完整工作流

```yaml
# .github/workflows/ci.yml
name: ci

on:
  push:
    branches: [main]
    paths: ['requirements/**', 'app/**', 'routes/**', 'services/**']
  pull_request:
    paths: ['requirements/**', 'app/**', 'routes/**', 'services/**']

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: test
          MYSQL_DATABASE: qor_test
        ports: ['3306:3306']
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: 'requirements/dev.txt'

      # 1. 安装依赖
      - name: Install deps
        run: pip install -r requirements/dev.txt

      # 2. 哈希完整性校验
      - name: Verify hashes
        run: pip install --require-hashes --dry-run -r requirements/prod.txt

      # 3. 漏洞扫描
      - name: Security audit
        run: |
          pip-audit -r requirements/prod.txt --strict

      # 4. Lint
      - name: Lint
        run: ruff check .

      # 5. 类型检查
      - name: Type check
        run: mypy app/ routes/ services/ core/

      # 6. 单元测试
      - name: Test
        env:
          SECRET_KEY: test-secret
          DATABASE_URL: mysql+pymysql://root:test@localhost:3306/qor_test
        run: |
          flask db upgrade
          pytest --cov=app --cov-fail-under=60
```

### 8.2 预提交 Hook (pre-commit)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pip-audit
        name: pip-audit
        entry: pip-audit -r requirements/prod.txt
        language: system
        pass_filenames: false
        types: [python]

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff
        args: [--fix]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: check-yaml
      - id: end-of-file-fixer
      - id: trailing-whitespace
```

```bash
pip install pre-commit
pre-commit install
# 之后每次 git commit 自动跑 ruff + pip-audit
```

---

## 9. 项目改造步骤 (零侵入迁移)

> 本项目当前只有 `requirements.txt` (松散版本), 下面是 **零侵入** 迁移到 lockfile + 哈希校验的步骤.

### 步骤 1: 备份当前环境 (作为 lockfile 起点)
```bash
# 激活当前 venv 后
pip freeze > requirements/freeze.bak.txt
# 复制当前真实版本作为参考
pip freeze | sort > /tmp/current.txt
```

### 步骤 2: 创建 requirements/ 目录
```bash
mkdir -p requirements
# 移动现有文件
git mv requirements.txt requirements/base.in
# 创建 dev.in
cat > requirements/dev.in <<'EOF'
-r base.in
pytest>=7.4.0
pytest-cov>=4.1.0
pytest-flask>=1.3.0
ruff>=0.1.0
mypy>=1.7.0
pip-audit>=2.6.0
EOF
```

### 步骤 3: 安装 pip-tools
```bash
pip install -U pip-tools
```

### 步骤 4: 生成首个 lockfile
```bash
pip-compile --output-file=requirements/prod.txt \
            --generate-hashes \
            --strip-extras \
            requirements/base.in
pip-compile --output-file=requirements/dev.txt \
            --generate-hashes \
            --strip-extras \
            requirements/dev.in
```

### 步骤 5: 验证新 lockfile 可用
```bash
# 干净 venv
python -m venv /tmp/test_venv
source /tmp/test_venv/bin/activate
pip install --require-hashes -r requirements/prod.txt
python -c "import flask, pandas, pymysql; print('OK')"
```

### 步骤 6: 更新 deploy/README.md 与 systemd 服务
```ini
# /etc/systemd/system/qor_recorder.service 中 ExecStart 改为
ExecStart=/opt/qor_recorder/venv/bin/gunicorn -c deploy/gunicorn.conf.py app:app
```

### 步骤 7: 更新 .gitignore
```text
# 已废弃的旧 requirements.txt
# requirements.txt   # 不要删除, 改 symlink 兼容老脚本
```

为兼容 Makefile / 旧脚本, 顶层 `requirements.txt` 改为**符号链接**:
```bash
cd QoR_Recorder
ln -s requirements/prod.txt requirements.txt
```

### 步骤 8: 提交
```bash
git add requirements/ requirements.txt
git commit -m "deps: 引入 pip-compile lockfile + 哈希校验"
```

### 步骤 9: 后续维护节奏
- **每月 1 号**: `pip-compile --upgrade` 更新 lockfile
- **每周一 06:00 (CI)**: `pip-audit` 自动扫描
- **CVE 紧急**: 立即改 `.in` + 重编译 + 紧急发布

---

## 10. 常见故障排查

| 错误                                            | 原因                                       | 解决                                                          |
|------------------------------------------------|--------------------------------------------|---------------------------------------------------------------|
| `ERROR: Could not find a version that satisfies the requirement` | 锁文件中版本在当前 Python 不存在 | 检查 `python --version`, 升级到 lockfile 要求的版本         |
| `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES` | 包内容被篡改 / 上游重新发布未更新 hash     | 重新 `pip-compile` 生成最新 hash, 或 `safety` 检查           |
| `ResolutionTooMany` 找不到兼容版本              | 多个包版本冲突                             | 调整 `.in` 中版本范围; 用 `uv pip compile` 通常更智能         |
| `ModuleNotFoundError: No module named 'pandas'` | 漏装 dev 依赖但用了 dev 工具               | 检查 `pip list` 是否在 venv 中, 或安装 `dev.txt`              |
| `pip install` 慢 / 超时                         | 默认源被限速                               | 换源: `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| Docker 构建 `pip install` 总是从零开始           | lockfile 改动导致 cache 失效              | 严格保证 `requirements/prod.txt` 单独 COPY, 不与代码混层     |
| `pip-audit` 误报 dev 工具 CVE                   | 扫描未区分 prod/dev                        | CI 只审计 `prod.txt`; dev 工具可放宽                          |
| Alpine 镜像 `cannot find -lssl`                 | musl 与 glibc 不兼容                       | 改用 `slim` 镜像 或安装 `apk add openssl-dev musl-dev`       |
| `MySQLdb` / `mysqlclient` 编译失败              | 缺 C 头文件                                | 用纯 Python 驱动 `PyMySQL` (本项目已选)                      |
| `MongoClient` 连接超时                          | `DB_TYPE=mongodb` 但 `MONGODB_URI` 未配   | 改 `.env` 或回退 `DB_TYPE=sqlite`                            |

---

## 11. 附录: Python vs Node 生态工具对照

> 本项目**无 Node.js 依赖**, 但若未来引入前端构建 / TypeScript 编译, 可参考下表.

| 维度       | Python 生态 (本项目)              | Node 生态 (如未来扩展)            |
|------------|----------------------------------|-----------------------------------|
| 包管理器    | pip / uv / pip-tools / poetry   | npm / yarn / pnpm / bun           |
| 锁文件      | `requirements/*.txt` (with hash) | `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` |
| 输入文件    | `*.in` (手写)                    | `package.json` (手写)             |
| 安装速度    | uv 极快, pip 中等                | bun 极快, pnpm 快, npm 慢          |
| 哈希校验    | `--require-hashes` + `pip-audit` | `npm ci` (自动) + `npm audit`     |
| 漏洞扫描    | `pip-audit` / `safety`           | `npm audit` / `snyk`              |
| 体积优化    | `pipdeptree` / slim 镜像         | tree-shaking / bundlephobia       |
| 多阶段构建  | Docker multi-stage               | Docker multi-stage (相同)         |
| 私有源      | `pip.conf` `index-url`           | `.npmrc` `registry=`              |

### 常用 npm → pnpm 命令对照 (若引入)
```bash
npm install            →  pnpm install
npm install <pkg>      →  pnpm add <pkg>
npm uninstall <pkg>    →  pnpm remove <pkg>
npm update             →  pnpm update
npm ci                 →  pnpm install --frozen-lockfile
npm audit              →  pnpm audit
```

### pnpm 优势 (vs npm/yarn, 若引入)
- 共享 store, 节省磁盘 (内容寻址存储)
- 严格依赖隔离 (phantom dependency 防护)
- monorepo 友好 (workspace)
- 安装速度比 npm 快 2-3x

---

## 速查表 (TL;DR)

| 场景              | 命令                                                            |
|-------------------|-----------------------------------------------------------------|
| 安装所有生产依赖  | `pip install --require-hashes -r requirements/prod.txt`         |
| 安装开发依赖      | `pip install -r requirements/dev.txt`                          |
| 同步 venv 到 lockfile | `pip-sync requirements/dev.txt`                             |
| 编译 lockfile     | `pip-compile --generate-hashes --output-file=requirements/prod.txt requirements/base.in` |
| 升级某包          | `pip-compile --upgrade-package flask requirements/base.in`       |
| 升级全部          | `pip-compile --upgrade requirements/base.in`                    |
| 漏洞扫描          | `pip-audit -r requirements/prod.txt --strict`                   |
| 许可证扫描        | `pip-licenses --fail-on="GPL;AGPL"`                             |
| 生成 SBOM         | `cyclonedx-py environment -o sbom.json`                         |
| Docker 构建        | `DOCKER_BUILDKIT=1 docker build -t qor:1.0 .`                  |
| 离线安装          | `pip install --no-index --find-links=/opt/wheels -r req.txt`   |

---

## 检查清单 (CI 必过)

- [ ] `requirements/prod.txt` 含 `--hash=sha256:...` 行
- [ ] `pip install --require-hashes --dry-run -r requirements/prod.txt` 成功
- [ ] `pip-audit -r requirements/prod.txt --strict` 无严重 CVE
- [ ] `pip-licenses --fail-on="GPL"` 通过
- [ ] Dockerfile 多阶段构建, 最终镜像 < 200 MB
- [ ] pre-commit hook 跑 ruff + pip-audit
- [ ] CI 缓存命中 (lockfile 不变时构建 < 30s)
- [ ] 升级流程演练: `pip-compile --upgrade` + `pytest` + 回滚验证

---

*本文档是项目 [deploy/README.md](../deploy/README.md) §5.7 和 [DATA_FORMAT.md](DATA_FORMAT.md) §20 的依赖管理补充. 配合 [user_guide.md](user_guide.md) 形成完整部署指南.*
