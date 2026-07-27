"""一次性迁移脚本: SQLite → MongoDB

用法:
    1. 启动 MongoDB
    2. 配置 .env:
         DATABASE_BACKEND=mongo
         MONGO_URI=mongodb://localhost:27017
         MONGO_DB=qor_recorder
    3. python migrate_sqlite_to_mongo.py [--dry-run] [--tables projects,modules,qor_records,...]

特性:
  - 幂等: 已存在的 _id 用 upsert 覆盖 (开发/测试可重复跑)
  - 增量: 只同步 SQLite 中存在但 MongoDB 中没有的 (默认), 也可 --full 强制全量
  - 安全: 不会删除 MongoDB 已有数据 (只新增/更新)
  - 校验: 迁移后自动 count 对比, 不一致会报警

不修改源数据, 不删除 SQLite 文件 (回滚保障)。
"""
import os
import sys
import argparse
import logging
from datetime import datetime

# 让脚本可作为模块被 app 上下文调用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as app_module
from models import Project, Module, QorRecord, User, ViolationPath, UserDashboard, DashboardGroup, ApiKey
import repo

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('migrate')


TABLES = {
    'users': (User, 'id', lambda r: {**(r.to_dict() if hasattr(r, 'to_dict') else {'id': r.id}), **{'_skip_password': True}}),
    'projects': (Project, 'id', None),
    'modules': (Module, 'id', None),
    'qor_records': (QorRecord, 'id', None),
    'violation_paths': (ViolationPath, 'id', None),
    'user_dashboards': (UserDashboard, 'id', None),
    'dashboard_groups': (DashboardGroup, 'id', None),
    'api_keys': (ApiKey, 'id', None),
}


def _to_doc(row, table_name, transformer):
    if transformer:
        return transformer(row)
    if hasattr(row, 'to_dict'):
        return row.to_dict()
    return {'id': row.id}


def migrate_table(table_name: str, full: bool = False, dry_run: bool = False) -> int:
    cls, key_field, transformer = TABLES[table_name]
    log.info(f'--- migrating {table_name} ---')
    all_rows = cls.query.all()
    if not full and repo.is_mongo_enabled():
        existing_ids = set(
            d.get(key_field) for d in repo.mongo_find(table_name, {}, {key_field: 1})
        )
        rows = [r for r in all_rows if getattr(r, key_field) not in existing_ids]
        log.info(f'  incremental: {len(rows)} new rows (existing {len(existing_ids)}/{len(all_rows)})')
    else:
        rows = all_rows
        log.info(f'  full mode: {len(rows)} rows')
    if dry_run:
        log.info(f'  [DRY-RUN] would upsert {len(rows)} rows')
        return len(rows)
    n = 0
    for r in rows:
        d = _to_doc(r, table_name, transformer)
        if table_name == 'users':
            d.pop('password_hash', None)
        if repo.mongo_upsert(table_name, d, key_field):
            n += 1
    log.info(f'  upserted {n} rows')
    return n


def verify(table_name: str) -> bool:
    cls, key_field, _ = TABLES[table_name]
    sqlite_n = cls.query.count()
    mongo_n = repo.mongo_count(table_name)
    ok = sqlite_n == mongo_n
    log.info(f'  verify {table_name}: sqlite={sqlite_n} mongo={mongo_n} {"OK" if ok else "MISMATCH"}')
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tables', default=','.join(TABLES.keys()),
                   help='comma-separated table list')
    p.add_argument('--full', action='store_true', help='full overwrite instead of incremental')
    p.add_argument('--dry-run', action='store_true', help='only count, do not write')
    p.add_argument('--verify-only', action='store_true', help='only verify counts')
    p.add_argument('--skip-verify', action='store_true', help='skip count check')
    args = p.parse_args()

    if not repo.is_mongo_enabled():
        log.error('MongoDB not enabled; check DATABASE_BACKEND / MONGO_URI in .env')
        sys.exit(1)

    tables = [t.strip() for t in args.tables.split(',') if t.strip()]
    for t in tables:
        if t not in TABLES:
            log.error(f'unknown table: {t}; valid: {list(TABLES.keys())}')
            sys.exit(1)

    log.info(f'backend: {repo.BACKEND}; mongo: {repo.MONGO_URI}/{repo.MONGO_DB}')
    log.info(f'mode: {"full" if args.full else "incremental"}, '
             f'{"dry-run" if args.dry_run else "write"}, '
             f'tables: {tables}')

    with app_module.app.app_context():
        if args.verify_only:
            all_ok = all(verify(t) for t in tables)
            sys.exit(0 if all_ok else 2)

        total = 0
        for t in tables:
            total += migrate_table(t, full=args.full, dry_run=args.dry_run)
        log.info(f'TOTAL upserted: {total}')

        if not args.skip_verify and not args.dry_run:
            log.info('--- verification ---')
            all_ok = all(verify(t) for t in tables)
            if not all_ok:
                log.warning('verification mismatch; check log above')
                sys.exit(2)
    log.info('done.')


if __name__ == '__main__':
    main()
