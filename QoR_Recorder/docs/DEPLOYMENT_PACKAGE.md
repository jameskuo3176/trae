# QoR Recorder 部署交付清单（交 IT）

> 本文档回答"到底要把哪些文件拷到 Ubuntu 服务器"的问题，并给出逐项清单。
> 完整部署步骤以 `docs/IT_DEPLOYMENT_UBUNTU_Python310.md` 为准，本清单只负责"拷什么、不拷什么"。

## 0. 核心结论（先看这句）

**`frontend-vue/node_modules/` 不需要、也不应该拷贝到 Ubuntu 服务器。**

- `node_modules` 只是前端**本地开发/构建**时用的 npm 依赖（体积通常 300MB+、数万个小文件），生产运行完全用不到；
- 生产机上的前端是**已构建好的静态文件**（`dist/`），由 Nginx 直接托管，**不需要 Node.js 运行时**，也**不要**启动 Vite（`npm run dev` / 端口 5173）；
- Windows 开发机上的 `node_modules` 含平台相关二进制，拷到 Ubuntu **不能用**；
- 把 `node_modules` 拷上服务器只会拖慢传输、占用磁盘、增加出错概率，务必排除。

前端交付的正确姿势：**在"有网络的构建机"上执行 `npm ci && npm run build`，只把生成的 `dist/` 目录交付给服务器。**

---

## 1. 交付方式总览

| 组件 | 交付内容 | 落地路径 | 说明 |
|---|---|---|---|
| 前端（Vue） | `frontend-vue/dist/`（构建产物） | `/var/www/qor-recorder/` | 构建机 `npm ci && npm run build` 后拷出 |
| 后端（Django） | `QoR_Recorder/` 下源码 + 配置 | `/opt/qor_recorder/` | 不含运行时数据目录 |
| 反向代理 | `deploy/nginx.conf`（改 1 处 upstream） | `/etc/nginx/sites-available/` | 见 IT_DEPLOYMENT 文档 4.9 节 |
| 系统服务 | `deploy/qor_recorder.service` | `/etc/systemd/system/` | 方式 B 使用 |

---

## 2. 需要拷贝到服务器的文件清单

### 2.1 前端（构建机产出，只拷这一个目录）

构建机准备（需要网络，一次性）：

```bash
cd frontend-vue
npm ci          # 按 package-lock.json 精确安装依赖
npm run build   # 产出 dist/（内含 index.html + assets/）
```

> 若构建机也无法联网，可先 `npm ci` 一次并保留本地 `node_modules` 缓存，再按
> `deploy/README.md` "Air-gapped workflow" 一节在断网前预热 npm 缓存后离线构建。

需要拷贝：

```
frontend-vue/dist/          # 整目录 → /var/www/qor-recorder/
```

`dist/` 典型内容（实际以构建输出为准）：

```
dist/
├── index.html
└── assets/
    ├── index-*.js          # 业务代码（可能按 vue-vendor / echarts-vendor / axios-vendor 分包）
    └── index-*.css
```

### 2.2 后端（Django 源码，拷整目录再删排除项）

以下目录/文件需要拷到 `/opt/qor_recorder/`：

```
QoR_Recorder/
├── manage.py                     # Django 入口
├── django_app/                   # 应用代码（settings / urls / views / api / core / services / templates / static）
├── requirements.txt              # Python 依赖清单（venv 安装用）
├── start.sh                      # systemd 启动脚本（自动 migrate + gunicorn）
├── .env.example                  # 环境变量模板（服务器上复制为 .env 并修改）
├── deploy/
│   ├── nginx.conf                # Nginx 站点配置（改 upstream 为本机 127.0.0.1:8000）
│   └── qor_recorder.service      # systemd unit 文件
├── wheelhouse/                   # （可选）离线 Python 依赖包，见 wheelhouse/README.md
├── config/                       # 评审层级配置（review_hierarchy.yaml）
├── schemas/                      # 上传 JSON Schema
├── scripts/                      # 数据上传脚本（csv_to_json / dc_report_to_json 等）
├── examples/                     # 示例数据（可选，演示用）
└── docs/                         # 部署/使用/开发文档（可选）
```

> 需要运行时创建、**不要手动建**的空目录（`start.sh` 会自动创建）：
> `data/`、`uploads/`、`backups/`、`logs/`、`mongodbdir/`、`staticfiles/`。

### 2.3 若交付到已有服务器（升级/迁移数据）

若目标环境已有历史数据，需一并迁移以下运行时数据（**须停服后拷贝，保持一致**）：

```
data/        # SQLite 主库 qor_recorder.db + 各项目库（首次部署可空）
uploads/     # 上传/评审附件
backups/     # 应用备份
mongodbdir/  # MongoDB 数据（启用 hybrid/mongo 时才需要，或另行 mongodump）
```

---

## 3. 明确【不要】拷贝的内容

| 目录/文件 | 原因 |
|---|---|
| `frontend-vue/node_modules/` | 前端构建依赖，生产机不需要（见第 0 节） |
| `frontend-vue/dist/` | 本地构建产物，应由服务器侧统一交付；避免旧产物混入 |
| `frontend-vue/src/`、`frontend-vue/package.json` 等源码 | 生产机不需要前端源码（除非 IT 要在服务器上重新构建） |
| `.git/` | 版本库元数据，不随发布包 |
| `venv/`、`.venv/`、`env/` | Python 虚拟环境，应在服务器上按 3.10 新建 |
| `__pycache__/`、`*.pyc` | Python 缓存 |
| `data/`、`uploads/`、`backups/`、`logs/`、`mongodbdir/` | 运行时数据，首次部署由应用创建；已有数据按 2.3 节单独备份迁移 |
| `.env` | 含密钥的本地环境变量，不随包；服务器上用 `.env.example` 生成 |
| 各类测试/临时文件 | `tests/`、`pytest.ini`、`*_out.txt`、`demo_batch_upload/` 等（可按需取舍） |

---

## 4. 服务器侧目录规划（方式 B：Ubuntu + Python 3.10）

```text
/opt/qor_recorder/         # 后端（对应 2.2 节清单）
├── venv/                  # python3.10 -m venv，随后 pip install -r requirements.txt
├── .env                   # 由 .env.example 复制并修改
├── data/  uploads/  backups/  logs/  mongodbdir/  staticfiles/
└── ...（源码同 2.2）

/var/www/qor-recorder/     # 前端（对应 2.1 节 dist/）
└── index.html + assets/
```

权限：`/opt/qor_recorder` 属主 `qor:qor`；`/var/www/qor-recorder` 属主 `www-data:www-data`。

---

## 5. 最小拷贝操作示例

构建机（前端）：

```bash
cd frontend-vue
npm ci && npm run build
```

将发布包整理为如下结构后整体上传服务器：

```text
release-YYYYMMDD/
├── backend/                # 即 2.2 节 QoR_Recorder/ 筛选后的内容
└── web/
    └── dist/               # 即 2.1 节构建产物
```

服务器上（以 root 或 sudo）：

```bash
# 后端
sudo cp -r backend/* /opt/qor_recorder/
# 前端
sudo cp -r web/dist/* /var/www/qor-recorder/
# 之后按 IT_DEPLOYMENT_UBUNTU_Python310.md 4.4~4.10 节
# 建 venv、装依赖、配 .env、collectstatic、注册 systemd、配 Nginx
```

---

## 6. 常见疑问

- **为什么 node_modules 不能拷？** 它只是构建期依赖。生产机由 Nginx 托管静态文件，连 Node.js 都不需要安装。从 Windows 拷到 Ubuntu 还会因原生模块不兼容而失败。
- **`start.sh` 会不会起前端？** 不会。它只 `migrate` 再启动 Gunicorn。前端升级只替换 `/var/www/qor-recorder/` 后 reload Nginx。
- **为什么不在服务器上直接 npm install？** 允许，但要求服务器能访问 npm registry（或内网镜像），且会白白引入 Node 工具链。更推荐构建机出 `dist/`。
- **dist 会不会因为打包方式不同导致页面白屏？** `dist/` 是 `vite build` 的标准产物，内部资源用相对/绝对路径按 `VITE_API_BASE_URL=/api` 生成，Nginx 按 `deploy/nginx.conf` 反代 `/api` 等路径即可正常访问。
- **前端怎么知道我改了接口地址？** 前端通过 `VITE_API_BASE_URL=/api`（`.env.production`）走同源相对路径，由 Nginx 转发到后端，服务器上无需改前端配置。
