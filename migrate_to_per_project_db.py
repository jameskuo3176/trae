"""按项目分库数据迁移脚本

将 qor_recorder.db 主库中已有项目的数据切到独立的 qor_p_<id>.db
每个项目得到自己的 DB 文件, 互不干扰

用法:
  python migrate_to_per_project_db.py --dry-run   # 只统计, 不实际迁移
  python migrate_to_per_project_db.py             # 实际迁移
  python migrate_to_per_project_db.py --clean     # 迁移后从主库删除已迁移数据

注意:
  脚本使用独立的 SQLAlchemy engine 操作 (不走 ORM bind 路由),
  避免被 core.db_routing 拦截.
"""
import argparse
import os
import sys
import json

# 让脚本可被任何目录调用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_config():
    """加载环境, 强制 sqlite 模式"""
    os.environ.setdefault('DB_TYPE', 'sqlite')
    os.environ.setdefault('SECRET_KEY', 'dev-only-secret-key-please-change-in-prod')
    os.environ.setdefault('DEBUG', '1')


def _serialize(obj):
    """处理 datetime 等不可直接 JSON 序列化的字段"""
    from datetime import datetime, date
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    return str(obj)


# =========================================================================
# 直接 SQL 操作 (不依赖 ORM bind 路由)
# =========================================================================
def _get_master_engine():
    """获取主库 engine, 不通过 db.session"""
    from sqlalchemy import create_engine
    from config import BASE_DIR
    master_path = os.path.join(BASE_DIR, 'qor_recorder.db')
    return create_engine(f'sqlite:///{master_path}', echo=False)


def _read_table_from_master(table_name, where=None, params=None):
    """从主库读表全部行, 返回 list[dict]"""
    from sqlalchemy import text
    engine = _get_master_engine()
    sql = f'SELECT * FROM {table_name}'
    if where:
        sql += f' WHERE {where}'
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params or {}).fetchall()
        cols = rows[0]._fields if rows else []
        result = [dict(zip(cols, row)) for row in rows]
    engine.dispose()
    return result


def _count_table_from_master(table_name, where=None, params=None):
    """统计主库表行数"""
    from sqlalchemy import text
    engine = _get_master_engine()
    sql = f'SELECT COUNT(*) FROM {table_name}'
    if where:
        sql += f' WHERE {where}'
    with engine.connect() as conn:
        n = conn.execute(text(sql), params or {}).scalar()
    engine.dispose()
    return n


def _delete_from_master(table_name, where, params):
    """从主库删除满足条件的行"""
    from sqlalchemy import text
    engine = _get_master_engine()
    with engine.begin() as conn:
        conn.execute(text(f'DELETE FROM {table_name} WHERE {where}'), params)
    engine.dispose()


# =========================================================================
# 项目库直接写入
# =========================================================================
def _get_project_engine(project_id):
    """获取项目库 engine"""
    from sqlalchemy import create_engine, event
    from config import BASE_DIR
    path = os.path.join(BASE_DIR, f'qor_p_{project_id}.db')

    if not os.path.exists(path):
        # 自动创建项目库
        from core.project_db import create_project_db
        create_project_db(project_id)

    engine = create_engine(f'sqlite:///{path}', echo=False)

    @event.listens_for(engine, 'connect')
    def _set_pragma(dbapi_conn, conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()
    return engine


def _insert_rows_to_project(project_id, table_name, rows):
    """批量插入行到项目库"""
    if not rows:
        return 0
    from sqlalchemy import text
    engine = _get_project_engine(project_id)
    cols = list(rows[0].keys())
    placeholders = ', '.join([f':{c}' for c in cols])
    col_list = ', '.join(cols)
    sql = f'INSERT OR IGNORE INTO {table_name} ({col_list}) VALUES ({placeholders})'
    with engine.begin() as conn:
        for row in rows:
            # 处理 datetime / None
            data = {}
            for k, v in row.items():
                data[k] = v
            try:
                conn.execute(text(sql), data)
            except Exception as e:
                print(f'  [WARN] {table_name} 插入失败 row_id={row.get("id")}: {e}')
    engine.dispose()
    return len(rows)


# =========================================================================
# 迁移主逻辑
# =========================================================================
# 模型对应的实际表名 (主库当前结构)
TABLE_MODULE = 'modules'
TABLE_QOR_RECORD = 'qor_records'
TABLE_VIOLATION_PATH = 'violation_paths'
TABLE_RUN_NOTE = 'run_notes'
TABLE_DASHBOARD_GROUP = 'dashboard_groups'
TABLE_ALERT_RULE = 'alert_rules'
TABLE_ALERT_EVENT = 'alert_events'
TABLE_DATA_SNAPSHOT = 'data_snapshots'
TABLE_TILE_REVIEW = 'tile_reviews'
TABLE_GROUP_REVIEW = 'group_reviews'
TABLE_SUBSYSTEM_REVIEW = 'subsystem_reviews'
TABLE_REVIEW_SNAPSHOT = 'review_snapshots'
TABLE_REVIEW_FILE = 'review_files'

# 直接带 project_id 的表 (可按 project_id 过滤)
TABLES_WITH_PROJECT_ID = [
    (TABLE_DASHBOARD_GROUP, TABLE_DASHBOARD_GROUP, 'project_id'),
    (TABLE_ALERT_RULE, TABLE_ALERT_RULE, 'project_id'),
    (TABLE_DATA_SNAPSHOT, TABLE_DATA_SNAPSHOT, 'project_id'),
    (TABLE_TILE_REVIEW, TABLE_TILE_REVIEW, 'project_id'),
    (TABLE_GROUP_REVIEW, TABLE_GROUP_REVIEW, 'project_id'),
    (TABLE_SUBSYSTEM_REVIEW, TABLE_SUBSYSTEM_REVIEW, 'project_id'),
    (TABLE_REVIEW_SNAPSHOT, TABLE_REVIEW_SNAPSHOT, 'project_id'),
]

# 关联表 (没有 project_id, 但有 FK 到主表)
# 通过父表 ID 间接迁
RELATED_TABLES = {
    # (table, parent_table, fk_column)
    (TABLE_QOR_RECORD, TABLE_MODULE, 'module_id'),
    (TABLE_VIOLATION_PATH, TABLE_QOR_RECORD, 'qor_record_id'),
    (TABLE_RUN_NOTE, TABLE_QOR_RECORD, 'qor_record_id'),
    (TABLE_ALERT_EVENT, TABLE_ALERT_RULE, 'rule_id'),
    (TABLE_REVIEW_FILE, TABLE_REVIEW_SNAPSHOT, 'snapshot_id'),
}


def migrate_one_project(project, dry_run=True, clean=False):
    """迁移单个项目的数据到独立 DB"""
    from config import BASE_DIR
    from sqlalchemy import text

    pid = project['id']
    name = project['name']
    print(f'\n[项目 {pid}] {name} (status={project["status"]})')

    # 1. 创建项目库文件 (实际模式)
    if not dry_run:
        from core.project_db import create_project_db, project_db_path
        path = create_project_db(pid)
        print(f'  DB: {path}')
    else:
        path = os.path.join(BASE_DIR, f'qor_p_{pid}.db')
        print(f'  DB (待创建): {path}')

    counter = {}
    total = 0

    # 2. Modules (主表, 必有 project_id)
    rows = _read_table_from_master(TABLE_MODULE, 'project_id = :pid', {'pid': pid})
    n_mod = len(rows)
    counter['modules'] = n_mod
    if not dry_run:
        _insert_rows_to_project(pid, TABLE_MODULE, rows)
    print(f'  modules: {n_mod} 条')
    total += n_mod

    # 3. 直接带 project_id 的其他表
    for tbl_name, _, col in TABLES_WITH_PROJECT_ID:
        rows = _read_table_from_master(tbl_name, f'{col} = :pid', {'pid': pid})
        n = len(rows)
        if n > 0:
            if not dry_run:
                _insert_rows_to_project(pid, tbl_name, rows)
            counter[tbl_name] = n
            print(f'  {tbl_name}: {n} 条')
            total += n

    # 4. 关联表 (通过父表 project_id 过滤)
    # 先取该项目所有 module_id 和 review_id / rule_id, 再过滤
    if n_mod > 0:
        # qor_records: 通过 modules.project_id 过滤
        rows = _read_table_from_master(
            TABLE_QOR_RECORD,
            'module_id IN (SELECT id FROM modules WHERE project_id = :pid)',
            {'pid': pid},
        )
        n = len(rows)
        if n > 0:
            if not dry_run:
                _insert_rows_to_project(pid, TABLE_QOR_RECORD, rows)
            counter[TABLE_QOR_RECORD] = n
            print(f'  {TABLE_QOR_RECORD}: {n} 条')
            total += n

            # violation_paths / run_notes 依赖 qor_records
            record_ids = [r['id'] for r in rows]
            if record_ids:
                placeholders = ', '.join([f':id_{i}' for i in range(len(record_ids))])
                params = {f'id_{i}': rid for i, rid in enumerate(record_ids)}

                for tbl in [TABLE_VIOLATION_PATH, TABLE_RUN_NOTE]:
                    rows2 = _read_table_from_master(
                        tbl, f'qor_record_id IN ({placeholders})', params,
                    )
                    n2 = len(rows2)
                    if n2 > 0:
                        if not dry_run:
                            _insert_rows_to_project(pid, tbl, rows2)
                        counter[tbl] = n2
                        print(f'  {tbl}: {n2} 条')
                        total += n2

        # alert_events: 通过 alert_rules.project_id 过滤
        rule_rows = _read_table_from_master(
            TABLE_ALERT_RULE, 'project_id = :pid', {'pid': pid},
        )
        if rule_rows:
            rule_ids = [r['id'] for r in rule_rows]
            placeholders = ', '.join([f':id_{i}' for i in range(len(rule_ids))])
            params = {f'id_{i}': rid for i, rid in enumerate(rule_ids)}
            rows3 = _read_table_from_master(
                TABLE_ALERT_EVENT, f'rule_id IN ({placeholders})', params,
            )
            n3 = len(rows3)
            if n3 > 0:
                if not dry_run:
                    _insert_rows_to_project(pid, TABLE_ALERT_EVENT, rows3)
                counter[TABLE_ALERT_EVENT] = n3
                print(f'  {TABLE_ALERT_EVENT}: {n3} 条')
                total += n3

        # review_files: 通过 review_snapshots.project_id 过滤
        snap_rows = _read_table_from_master(
            TABLE_REVIEW_SNAPSHOT, 'project_id = :pid', {'pid': pid},
        )
        if snap_rows:
            snap_ids = [r['id'] for r in snap_rows]
            placeholders = ', '.join([f':id_{i}' for i in range(len(snap_ids))])
            params = {f'id_{i}': sid for i, sid in enumerate(snap_ids)}
            rows4 = _read_table_from_master(
                TABLE_REVIEW_FILE, f'snapshot_id IN ({placeholders})', params,
            )
            n4 = len(rows4)
            if n4 > 0:
                if not dry_run:
                    _insert_rows_to_project(pid, TABLE_REVIEW_FILE, rows4)
                counter[TABLE_REVIEW_FILE] = n4
                print(f'  {TABLE_REVIEW_FILE}: {n4} 条')
                total += n4

    # 5. clean 模式: 从主库删除已迁数据
    if clean and not dry_run:
        print(f'  [clean] 从主库删除已迁数据...')
        from sqlalchemy import text as sa_text
        engine = _get_master_engine()
        with engine.begin() as conn:
            # qor_records 先 (依赖 modules)
            conn.execute(sa_text(
                f'DELETE FROM qor_records WHERE module_id IN '
                f'(SELECT id FROM modules WHERE project_id = :pid)'
            ), {'pid': pid})
            conn.execute(sa_text(
                f'DELETE FROM modules WHERE project_id = :pid'
            ), {'pid': pid})
            # review 类
            for tbl in ['dashboard_groups', 'alert_rules', 'data_snapshots',
                        'tile_reviews', 'group_reviews', 'subsystem_reviews',
                        'review_snapshots']:
                conn.execute(sa_text(
                    f'DELETE FROM {tbl} WHERE project_id = :pid'
                ), {'pid': pid})
        engine.dispose()
        print(f'  [clean] ✓ 主库残留已清理')

    return total, counter


def update_project_db_path(project_id, db_path):
    """更新主库 Project.db_path 字段"""
    from sqlalchemy import text
    engine = _get_master_engine()
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE projects SET db_path = :path WHERE id = :pid'),
            {'path': db_path, 'pid': project_id},
        )
    engine.dispose()


def main():
    parser = argparse.ArgumentParser(description='按项目分库数据迁移')
    parser.add_argument('--dry-run', action='store_true', help='只统计, 不实际迁移')
    parser.add_argument('--clean', action='store_true', help='迁移后从主库删除已迁移数据')
    parser.add_argument('--project-id', type=int, help='只迁移指定项目 (默认全部)')
    args = parser.parse_args()

    _load_config()

    print('=' * 60)
    print('按项目分库 - 数据迁移工具')
    print('=' * 60)

    # 1. 从主库直接读项目列表
    from config import BASE_DIR
    master_path = os.path.join(BASE_DIR, 'qor_recorder.db')
    if not os.path.exists(master_path):
        print(f'[ERR] 主库不存在: {master_path}')
        sys.exit(1)

    projects = _read_table_from_master('projects')
    if args.project_id:
        projects = [p for p in projects if p['id'] == args.project_id]
    projects.sort(key=lambda x: x['id'])

    print(f'待处理项目数: {len(projects)}')
    if args.dry_run:
        print('模式: DRY-RUN (不写盘, 仅统计)')

    grand_total = 0
    for p in projects:
        n, counter = migrate_one_project(p, dry_run=args.dry_run, clean=args.clean)
        grand_total += n

        # 更新 Project.db_path
        if not args.dry_run:
            from core.project_db import project_db_path
            update_project_db_path(p['id'], project_db_path(p['id']))

    print('\n' + '=' * 60)
    print(f'总计: {grand_total} 条记录')
    if args.dry_run:
        print('(DRY-RUN 模式, 实际未写入)')
        print('取消 --dry-run 参数执行真实迁移')
    else:
        print('迁移完成!')
    print('=' * 60)


if __name__ == '__main__':
    main()
