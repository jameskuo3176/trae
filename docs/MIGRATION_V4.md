# 迁移指南：SQLite → MongoDB + 按项目分库

> 本文档说明如何将 QoR Recorder 从 v3.x 单库 SQLite 架构迁移到 v4.0 按项目分库 + MongoDB dual-write 架构。

## 1. 升级架构概览

### 1.1 v3.x → v4.0 变化

| 维度         | v3.x                       | v4.0                                       |
|--------------|----------------------------|--------------------------------------------|
| 数据库文件   | 单文件 `qor_recorder.db`   | 主库 + 每个项目独立 `qor_p_<id>.db`         |
| 后端类型     | 仅 SQLite                  | SQLite / MySQL / PostgreSQL / MongoDB      |
| 切换方式     | 改 URI                      | `DB_TYPE=sqlite\|sql\|mongodb`            |
| MongoDB 模式 | 不支持                      | dual-write（写 Mongo + SQLite 兜底）       |
| 项目锁       | 应用层 status 标记          | 应用层 + 物理 chmod 0444                   |

### 1.2 兼容性保证

- 所有现有 API 端点保持兼容（`/api/*`, `/api/v1/*`）
- 现有数据 CSV 格式不变
- `seed_demo_data.py` / `init_db.py` 等脚本接口不变（推荐改用 `db_init.py`）
- 用户主题/Review/项目等业务数据迁移后行为一致

## 2. 第一步：升级代码

```bash
cd QoR_Recorder
git pull origin main  # 拉取 v4.0 代码
# 包含分库路由、MongoDB 抽象层、迁移脚本等
```

## 3. 第二步：备份现有数据

```bash
# 备份主库
cp qor_recorder.db qor_recorder.db.bak.v3.$(date +%Y%m%d)
# 备份上传目录
cp -r uploads/ uploads.bak.v3.$(date +%Y%m%d)
# 备份自动备份目录
cp -r backups/ backups.bak.v3.$(date +%Y%m%d)
```

## 4. 第三步：升级主库 schema

```bash
# 1. 验证配置
python db_init.py --check

# 2. 跑 alembic 迁移（增加 projects.db_path, hidden_*, locked_* 字段）
flask db upgrade

# 3. 验证主库表结构
sqlite3 qor_recorder.db ".schema projects"
# 确认有 status / locked_at / hidden_at / db_path 等字段
```

## 5. 第四步：迁移业务数据到项目库

```bash
# 1. 预览迁移 (dry-run)
python migrate_to_per_project_db.py --dry-run
# 预期看到每个项目的 modules / qor_records / review 等表的行数

# 2. 实际迁移
python migrate_to_per_project_db.py
# 输出示例:
#   [项目 1] MyChip
#   DB: D:\...\qor_p_1.db
#   modules: 6 条
#   qor_records: 32 条
#   ...
#   [项目 2] OtherChip
#   ...

# 3. 验证项目库
ls -la qor_p_*.db
# 预期每个项目一个 .db 文件

# 4. 清理主库残留（可选，节省空间）
python migrate_to_per_project_db.py --clean
```

**注意**：
- `--clean` 后主库的 `modules` / `qor_records` / `violation_paths` 等业务表为 0 条
- 主库仅保留 `users` / `projects` / `api_keys` 等系统级数据
- 误执行 `--clean` 后用备份恢复

## 6. 第五步（可选）：迁移到 MongoDB

如果团队规模扩大，需要切换到 MongoDB：

```bash
# 1. 启动 MongoDB
mongod --dbpath /var/lib/mongodb

# 2. 设置环境变量
export DB_TYPE=mongodb
export MONGODB_URI=mongodb://localhost:27017
export MONGODB_DB=qor_recorder

# 3. 验证 MongoDB 连接
python db_init.py --check
# 预期: [MONGO] 已创建索引 (users.username unique, ...)

# 4. 迁移业务数据到 Mongo
python migrate_sqlite_to_mongo.py --dry-run
python migrate_sqlite_to_mongo.py

# 5. 启动应用（自动 dual-write 模式）
python app.py
```

**MongoDB dual-write 模式**：

- 写入：同时写 MongoDB + SQLite（任一失败不影响另一份）
- 读取：优先 MongoDB，SQLite 兜底
- 优势：Mongo 故障时系统仍可用；未来可完全切到 Mongo，去掉 dual-write
- 缺点：写入略慢（双写）；存储略多

## 7. 第六步：验证

```bash
# 1. 启动应用
python app.py

# 2. 端到端验证
python _verify_e2e.py
# 预期输出:
#   [1] demo_riscv_soc status=active db_path=D:\...\qor_p_1.db
#   [master] modules: 0 条 (期望 0)
#   ...
#   [2] 项目库内容:
#   [1] demo_riscv_soc: modules=6 records=32 db_size=200KB
#   ...
#   [OK] 端到端验证通过

# 3. 浏览器验证
# 访问 http://localhost:5000
# 登录 admin/admin@2026
# 检查 Dashboard / 项目管理 / 数据上传 / Review 等功能
```

## 8. 回滚方案

如果升级后出现问题：

### 8.1 回滚到 v3.x 单库

```bash
# 1. 停止应用
# 2. 恢复备份
cp qor_recorder.db.bak.v3.YYYYMMDD qor_recorder.db
# 3. 切回 v3.x 代码
git checkout v3.x
# 4. 启动应用
python app.py
```

### 8.2 回滚到 SQLite 模式（不切回 v3.x）

```bash
# 1. 设置 DB_TYPE=sqlite
export DB_TYPE=sqlite

# 2. 启动应用
python app.py
# 系统自动用 SQLite 兜底（业务数据可能不完整，需要从 qor_p_*.db 回填）
```

## 9. 常见问题

### Q1: 升级后 Dashboard 显示 0 条记录？

**A**: 检查项目库文件是否存在：
```bash
ls qor_p_*.db
```
如果不存在，跑 `python migrate_to_per_project_db.py` 迁移。

### Q2: MongoDB 迁移后 `qor_records` 数量不对？

**A**: 用 `migrate_sqlite_to_mongo.py --dry-run` 预览，对比 SQLite 主库 + 项目库的总数。

### Q3: 项目锁（status=locked）后上传失败？

**A**: 这是预期行为。锁定项目物理文件 `chmod 0444`，所有写入被拒绝。解锁：
```python
# 在管理页面解锁
# 或手动 chmod 0644 qor_p_<id>.db
```

### Q4: dual-write 模式下 Mongo 故障怎么办？

**A**: 系统自动降级为 SQLite-only 模式，写入继续可用。读请求会从 SQLite 兜底返回。

### Q5: 如何彻底切到 MongoDB（去掉 dual-write）？

**A**: 修改 `repo.py` 去掉 SQLite 写分支即可。建议先 dual-write 运行一段时间验证数据一致性。

## 10. 性能对比

| 场景                          | v3.x 单库 SQLite | v4.0 分库 SQLite | v4.0 MongoDB dual-write |
|-------------------------------|------------------|------------------|--------------------------|
| 单项目 1w 记录查询            | ~50ms            | ~30ms            | ~80ms (含双写)            |
| 单项目 10w 记录查询           | ~800ms           | ~100ms           | ~150ms                   |
| 多项目并发查询                | 串行 ~5s         | 并行 ~200ms      | 并行 ~300ms              |
| 大项目归档/删除                | 影响全库         | 只影响 1 个文件  | 只删除 1 个 collection    |

## 11. 部署建议

### 11.1 小团队（< 10 人，< 5w 记录/项目）

- 推荐：v4.0 分库 SQLite
- 部署：单进程 `python app.py`
- 备份：每日 `cp qor_*.db backups/`

### 11.2 中团队（10-30 人，5w-50w 记录/项目）

- 推荐：v4.0 分库 SQLite 或 MySQL
- 部署：gunicorn + nginx，单机多 worker
- 备份：主库 cron + 项目库按需

### 11.3 大团队（> 30 人，> 50w 记录/项目）

- 推荐：v4.0 MongoDB dual-write（最终切到 Mongo-only）
- 部署：gunicorn + nginx + MongoDB 副本集
- 备份：MongoDB oplog + 定期 mongodump

---

*文档版本：1.0 | 最后更新：2026-07-28（v4.0 迁移指南首发）*
