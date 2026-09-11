# QoR Recorder MySQL 迁移故障重新部署方案

## 1. 适用范围

本方案用于处理安装或升级时出现以下错误的环境：

```text
django.db.utils.OperationalError:
(1054, "Unknown column 'projects.locked_by' in 'field list'")
```

故障原因是原 `0002_global_modules` 迁移使用了 SQLite 专属的表结构探测语句，未能在 MySQL 中正确将以下外键列改名：

- `projects.locked_by_id` → `projects.locked_by`
- `projects.hidden_by_id` → `projects.hidden_by`
- `data_locks.locked_by_id` → `data_locks.locked_by`

修复包同时支持以下两种现场状态：

1. `0002_global_modules` 尚未成功执行；
2. `0002_global_modules` 已有迁移记录，但数据库列名仍未修正。

## 2. 修复包要求

部署包必须包含：

- 更新后的 `django_app/core/migrations/0002_global_modules.py`
- 新增的 `django_app/core/migrations/0011_repair_foreign_key_column_names.py`

`tests/test_migration_commands.py` 是研发测试文件，生产部署不依赖该文件。

不要删除、修改或伪造 `django_migrations` 表中的迁移记录，也不要使用 `migrate --fake`。

## 3. 部署前检查

以下命令默认安装目录为 `/opt/qor_recorder`，服务名为 `qor_recorder`。如果现场目录或服务名不同，请替换为实际值。

```bash
cd /opt/qor_recorder

# 确认 MySQL 正常运行；本项目生产部署要求 MySQL 8
mysql --version
systemctl is-active mysql

# 确认修复文件已放入部署目录
test -f django_app/core/migrations/0002_global_modules.py
test -f django_app/core/migrations/0011_repair_foreign_key_column_names.py
```

预期：

- `mysql --version` 显示 MySQL 8.x；
- `systemctl is-active mysql` 输出 `active`；
- 两条 `test -f` 命令均无报错。

## 4. 备份数据库

必须先备份，再执行迁移：

```bash
sudo mkdir -p /opt/qor_recorder/backups

mysqldump -h 127.0.0.1 -u qor -p \
  --single-transaction \
  --routines \
  --triggers \
  qor_recorder \
  | gzip > "/opt/qor_recorder/backups/qor_recorder-before-column-fix-$(date +%F-%H%M%S).sql.gz"

ls -lh /opt/qor_recorder/backups/qor_recorder-before-column-fix-*.sql.gz
```

确认备份文件存在且大小不为 0。不要把数据库密码写入命令行、日志或工单。

## 5. 停止应用并更新代码

```bash
sudo systemctl stop qor_recorder
systemctl is-active qor_recorder
```

预期服务状态为 `inactive`。随后按照现有发布流程覆盖后端代码，并再次确认第 2 节中的两个迁移文件存在。

本次修复未增加 Python 依赖；如果部署的是完整新版本，仍应按照常规发布流程执行依赖安装。

## 6. 执行主数据库迁移

```bash
cd /opt/qor_recorder

sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate --noinput'
```

迁移必须正常结束，不应再出现 `Unknown column`、SQL 语法错误或 Traceback。

检查迁移状态：

```bash
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py showmigrations core'
```

确认至少包含：

```text
[X] 0002_global_modules
[X] 0011_repair_foreign_key_column_names
```

## 7. 验证 MySQL 列结构

```bash
mysql -h 127.0.0.1 -u qor -p qor_recorder -e \
  "SHOW COLUMNS FROM projects WHERE Field IN ('locked_by','locked_by_id','hidden_by','hidden_by_id');"

mysql -h 127.0.0.1 -u qor -p qor_recorder -e \
  "SHOW COLUMNS FROM data_locks WHERE Field IN ('locked_by','locked_by_id');"
```

预期结果：

- `projects` 存在 `locked_by` 和 `hidden_by`；
- `projects` 不存在 `locked_by_id` 和 `hidden_by_id`；
- 如果存在 `data_locks` 表，该表应存在 `locked_by`，不存在 `locked_by_id`。

## 8. 初始化数据和升级项目数据库

必须在主数据库迁移成功后执行：

```bash
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py init_default_data'

sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate_project_databases --check'

sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py migrate_project_databases'
```

注意检查 `init_default_data` 的完整输出。出现“初始化完成”之前的警告也必须处理，不能只依据最后一行判断成功。

## 9. 启动和验收

```bash
sudo -u qor bash -c \
  'set -a; source /opt/qor_recorder/.env; set +a; /opt/qor_recorder/venv/bin/python manage.py check'

sudo systemctl start qor_recorder
sudo systemctl status qor_recorder --no-pager
sudo journalctl -u qor_recorder -n 100 --no-pager
```

验收要求：

- `manage.py check` 无错误；
- `qor_recorder` 服务状态为 `active (running)`；
- 服务日志中无数据库字段不存在、迁移失败或持续 500/503 错误；
- 管理员能够登录；
- 项目列表能够正常打开；
- 能够正常进入至少一个已有项目。

## 10. 失败处理

如果第 6～9 节任一步骤失败：

1. 不要启动或继续使用应用；
2. 保存完整命令输出和 Traceback；
3. 保留本次迁移前的 `.sql.gz` 备份；
4. 不要使用 `--fake`，不要手工修改 `django_migrations`；
5. 将以下信息提供给研发：
   - `manage.py showmigrations core` 输出；
   - 第 7 节的列结构查询结果；
   - `journalctl -u qor_recorder -n 200 --no-pager` 输出；
   - 实际部署版本和修复文件校验结果。

如需回滚数据库，应由数据库管理员在确认备份有效后停止应用、重建目标数据库并恢复第 4 节的完整备份；不要把备份直接覆盖导入到可能已发生部分迁移的数据库中。
