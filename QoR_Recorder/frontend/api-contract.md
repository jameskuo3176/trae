# QoR Recorder API v2 契约

> API v2 is the stable SPA contract. Existing `/api/*` and `/api/v1/*`
> endpoints remain compatibility surfaces.

## 认证

两种认证方式 (任选其一):

| 方式 | 请求头 | 场景 |
|------|--------|------|
| API Key | `X-API-Key: qor_xxxxxxxxxxxx` 或 `Authorization: Bearer qor_xxx` | 自动化、SPA |
| Session | Django session cookie | 浏览器 |

Session-authenticated unsafe requests (`POST`, `PUT`, `PATCH`, `DELETE`) must
send the `csrftoken` cookie value in `X-CSRFToken`. API v2 does not disable
Django CSRF protection.

### 获取 API Key (登录)
```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "admin", "password": "admin@2026"}
```
响应:
```json
{
  "api_key": "qor_abc123...",
  "api_key_id": 1,
  "user": {"id": 1, "username": "admin", "role": "admin", "display_name": "管理员"}
}
```

### 查看当前用户
```http
GET /api/v1/auth/me
X-API-Key: qor_xxx
```

---

## v2 conventions

- Every success is `{"ok": true, "data": ...}`.
- Every error is
  `{"ok": false, "error": {"code": "...", "message": "...", "details": {}}}`.
- Record, violation, report and note IDs are opaque strings. Never parse them
  as integers; ORM IDs and Mongo ObjectIds share this representation.
- Heavy-data requests always carry an explicit `project_id` (query parameter or
  project path segment). IDs are not globally unique in legacy project DBs.
- Collections use `page` (1-based) and `page_size` (1..200), returning
  `pagination: {page, page_size, total, pages}`.
- Record list/detail omit raw DC text. Fetch it lazily from `/raw`.
- `version` is server-derived only from normalized `full_dir`: a valid
  `regr_*` directly before `main` wins, otherwise the last valid `regr_*`
  segment wins. New imports have no `v1` or request-field fallback.

## Health

`GET /health` is unauthenticated and reports independent SQL and Mongo
readiness. Mongo is considered ready-but-disabled in ORM mode. A failed enabled
dependency returns HTTP 503 with `status: "degraded"`.

## Global modules

`GET /api/v2/modules?project_id={id}` returns canonical global module IDs plus
the explicit project association:

```json
{"ok":true,"data":[{"id":12,"name":"cpu_top","normalized_name":"cpu_top","project_id":3}]}
```

Names are NFKC-normalized, trimmed, case-folded, whitespace-collapsed, and
globally unique. A module can be associated with many projects. During
migration, `LegacyModuleMapping` preserves each `(project_id, local_module_id)`
for rollback and old APIs.

## Versions

`GET /api/v2/versions?project_id={id}` returns path-derived values. `meta`
reports records whose old paths cannot produce a version.

## Records

`GET /api/v2/records?project_id={id}&module_id={global_id}&version={value}&page=1&page_size=50`

```json
{
  "ok": true,
  "data": [{"id":"663e...","project_id":3,"module_id":12,"version":"regr_20260810"}],
  "pagination": {"page":1,"page_size":50,"total":1,"pages":1}
}
```

- `GET /api/v2/projects/{project_id}/records/{record_id}`
- `GET /api/v2/projects/{project_id}/records/{record_id}/raw`
- `GET /api/v2/projects/{project_id}/records/{record_id}/violations`
- `GET /api/v2/projects/{project_id}/records/{record_id}/notes`

Violation objects consistently use string `id` and `record_id`, include
`project_id`, and expose `timing_group`, `startpoint`, `endpoint`, `slack`,
`depth`, `pure_depth`, `cell_delay`, `net_delay`, fan-in/fan-out fields and
`source_file`. They do not expose the old `qor_record_id` key.

## Persistence and migration

Relational SQL remains authoritative for users, projects, global modules,
project-module associations, mappings, reviews, and configuration. QoR records,
raw reports, violation paths, and run notes are accessed only through the
repository layer. `PERSISTENCE_MODE=orm|mongo|hybrid` selects the adapter;
hybrid reads Mongo first and falls back to ORM.

Migration commands are non-destructive and dry-run by default:

```bash
python manage.py migrate_global_modules
python manage.py migrate_global_modules --execute [--project-id 3]
python manage.py migrate_sqlite_to_mongo [--project-id 3]
python manage.py migrate_sqlite_to_mongo --execute [--project-id 3]
```

No command deletes or mutates project-local module/record rows.

## API v1 compatibility

### 列出可访问项目
```http
GET /api/v1/projects
```
返回当前用户可见项目 (admin=全部, 其他=成员项目)。

### 创建项目
```http
POST /api/v1/projects
Content-Type: application/json

{"name": "ChipA", "description": "..."}
```
创建者自动成为 owner。

### 项目详情
```http
GET /api/v1/projects/{project_id}
```

---

## 项目成员 (多用户协作)

| 端点 | 方法 | 说明 | 权限 |
|------|------|------|------|
| `/api/v1/projects/{id}/members` | GET | 成员列表 | view |
| `/api/v1/projects/{id}/members` | POST | 添加/更新成员 | manage |
| `/api/v1/projects/{id}/members/{member_id}` | DELETE | 移除成员 | manage |

角色: `owner` (管理) / `editor` (编辑) / `viewer` (只读)

POST body:
```json
{"username": "user1", "role": "editor"}
```

---

## 数据锁

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/locks` | GET | 查询锁 (可选 `?resource_type=&resource_id=`) |
| `/api/v1/locks` | POST | 加锁 |
| `/api/v1/locks/{lock_id}` | DELETE | 释放锁 |

加锁 body:
```json
{
  "resource_type": "module",
  "resource_id": 5,
  "reason": "正在优化时序",
  "duration_minutes": 30
}
```

---

## API Key 管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/apikeys` | GET | 列出当前用户 keys |
| `/api/v1/apikeys` | POST | 创建 key (明文仅返回一次) |
| `/api/v1/apikeys/{key_id}` | DELETE | 吊销 key |

创建 body:
```json
{"name": "DC-flow", "scopes": "upload,read", "expires_in_days": 90}
```

scopes: `read` / `upload` / `admin`

---

## 数据上传 (自动化集成)

```http
POST /api/v1/upload
X-API-Key: qor_xxx
Content-Type: multipart/form-data

project_id=1
version=v1.0
data_type=qor
files=@qor_report.csv
```

`data_type`: `qor` (默认) / `power` / `violation`

响应:
```json
{
  "ok": true,
  "saved_count": 1,
  "updated_count": 0,
  "alerts_triggered": 1,
  "file_results": [{"filename": "qor_report.csv", "ok": true, "saved": 1}]
}
```

### curl 示例 (DC 流程)
```bash
curl -X POST https://host/api/v1/upload \
  -H "X-API-Key: qor_xxx" \
  -F "project_id=1" \
  -F "version=v1.0" \
  -F "files=@qor_report.csv"
```

---

## 趋势预警

### 规则
| 端点 | 方法 | 说明 | 权限 |
|------|------|------|------|
| `/api/v1/alerts/rules` | GET | 规则列表 (可选 `?project_id=`) | view |
| `/api/v1/alerts/rules` | POST | 创建规则 | manage |
| `/api/v1/alerts/rules/{id}` | PUT | 更新规则 | manage |
| `/api/v1/alerts/rules/{id}` | DELETE | 删除规则 | manage |

创建规则 body:
```json
{
  "project_id": 1,
  "module_id": null,
  "metric": "wns_setup",
  "direction": "worsen",
  "window_size": 1,
  "sensitivity": 0.2
}
```

- `metric`: `wns_setup` / `wns_hold` / `area_total` / `power_total` / ...
- `direction`: `worsen` / `improve` / `threshold`
- `sensitivity`: 变化幅度阈值 (0.2 = 20%)

### 事件
```http
GET /api/v1/alerts/events?project_id=1&acknowledged=false&limit=50
```

确认事件:
```http
POST /api/v1/alerts/events/{event_id}/acknowledge
```

---

## 响应格式约定

- 成功: `{"ok": true, ...}` 或直接数组/对象
- 失败: `{"error": "message"}`, HTTP 4xx/5xx
- 401: 未认证
- 403: 无权限
- 404: 资源不存在
- 409: 资源冲突 (如已被锁定)

---

## 向后兼容

现有 `/api/*` 端点 (如 `/api/qor_data`, `/api/metrics`) 保持不变, 供现有 Jinja2 UI 使用。
`/api/v1/*` 为新 SPA 与自动化集成专用。
