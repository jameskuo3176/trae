"""备份服务

封装 DB 备份、校验等业务逻辑（Django 版本）。
"""
import hashlib
import json
import os
import sqlite3
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import PurePosixPath

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from django_app.core.models import BackupRecord
from django_app.core.db_routing import list_all_project_dbs


BACKUP_FORMAT_VERSION = 1
_HASH_CHUNK_SIZE = 1024 * 1024
MAINTENANCE_LOCK_NAME = 'qor_restore.lock'


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _migration_versions():
    """Return applied Django migration names keyed by app label."""
    versions = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT app, name FROM django_migrations ORDER BY app ASC, id ASC'
            )
            for app, name in cursor.fetchall():
                versions[str(app)] = str(name)
    except Exception:
        return {}
    return versions


def maintenance_lock_path():
    backup_dir = getattr(settings, 'BACKUP_DIR', 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return os.path.join(backup_dir, MAINTENANCE_LOCK_NAME)


class MaintenanceLock:
    """Exclusive lock file used while restore --apply replaces databases."""

    def __init__(self, path=None):
        self.path = path or maintenance_lock_path()
        self._fd = None

    def __enter__(self):
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self._fd = os.open(self.path, flags)
        except FileExistsError as exc:
            raise RuntimeError(f'maintenance lock held: {self.path}') from exc
        payload = (
            f'pid={os.getpid()}\n'
            f'created_at={timezone.now().isoformat()}\n'
            'purpose=restore_backup\n'
        ).encode('utf-8')
        os.write(self._fd, payload)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        return False


def _sqlite_record_count(path):
    """Count records in a snapshot without relying on Django DB routing."""
    connection = sqlite3.connect(f'file:{os.path.abspath(path)}?mode=ro', uri=True)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='qor_records'"
        ).fetchone()
        if not exists:
            return 0
        return int(connection.execute('SELECT COUNT(*) FROM qor_records').fetchone()[0])
    finally:
        connection.close()


def _snapshot_sqlite(source, destination):
    """Create a transactionally consistent SQLite snapshot, including WAL data."""
    source_connection = sqlite3.connect(os.path.abspath(source))
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def _database_sources(db_path):
    data_dir = os.path.dirname(os.path.abspath(db_path))
    sources = [('main', None, os.path.abspath(db_path), 'sql/qor_recorder.db')]
    seen = {os.path.abspath(db_path)}
    try:
        for info in list_all_project_dbs():
            path = os.path.abspath(info['path'])
            if path in seen or os.path.dirname(path) != data_dir:
                continue
            seen.add(path)
            sources.append((
                'project',
                info['project_id'],
                path,
                f"sql/{os.path.basename(path)}",
            ))
    except Exception:
        pass
    for name in sorted(os.listdir(data_dir)):
        path = os.path.abspath(os.path.join(data_dir, name))
        if path in seen or not name.endswith('.db'):
            continue
        project_id = name[len('qor_p_'):-len('.db')] if name.startswith('qor_p_') else ''
        if (name.startswith('qor_p_') and project_id.isdigit()) or name.endswith('_syn_qor.db'):
            seen.add(path)
            sources.append((
                'project',
                int(project_id) if project_id.isdigit() else None,
                path,
                f'sql/{name}',
            ))
    return sources


def _manifest_file(path, archive_path):
    return {
        'archive_path': archive_path,
        'size': os.path.getsize(path),
        'sha256': _sha256(path),
    }


def perform_backup(backup_type='auto', user=None):
    """执行数据库备份

    Args:
        backup_type: 备份类型 ('auto' / 'manual')
        user: 触发用户 (manual 时)

    Returns:
        dict: 备份结果
    """
    try:
        db_config = settings.DATABASES.get('default', {})
        db_path = db_config.get('NAME', '')
        engine = db_config.get('ENGINE', '')
        if 'sqlite' not in engine:
            return {'ok': False, 'error': '非 SQLite SQL 备份需由部署平台的原生备份工具执行'}
        if not os.path.exists(db_path):
            return {'ok': False, 'error': f'数据库文件不存在: {db_path}'}

        backup_dir = getattr(settings, 'BACKUP_DIR', 'backups')
        max_backups = getattr(settings, 'MAX_BACKUPS', 10)
        os.makedirs(backup_dir, exist_ok=True)

        ts = timezone.now().strftime('%Y%m%d_%H%M%S_%f')
        backup_path = os.path.join(backup_dir, f'qor_recorder_{ts}.zip')
        mongo_enabled = getattr(settings, 'PERSISTENCE_MODE', 'orm') != 'orm'
        mongo_dump_dir = os.path.join(backup_dir, f'.mongo_{ts}')
        migration_versions = _migration_versions()
        manifest = {
            'version': BACKUP_FORMAT_VERSION,
            'created_at': timezone.now().isoformat(),
            'persistence_mode': getattr(settings, 'PERSISTENCE_MODE', 'orm'),
            'schema': {
                'backup_format_version': BACKUP_FORMAT_VERSION,
                'django_migrations': migration_versions,
                'migration_apps': sorted(migration_versions.keys()),
            },
            'files': [],
            'databases': [],
        }
        record_count = 0
        with tempfile.TemporaryDirectory(prefix='.backup_', dir=backup_dir) as staging_dir:
            sql_staging_dir = os.path.join(staging_dir, 'sql')
            os.makedirs(sql_staging_dir)
            for role, project_id, source, archive_path in _database_sources(db_path):
                snapshot = os.path.join(sql_staging_dir, os.path.basename(archive_path))
                _snapshot_sqlite(source, snapshot)
                count = _sqlite_record_count(snapshot)
                record_count += count
                file_info = _manifest_file(snapshot, archive_path)
                manifest['files'].append(file_info)
                database_info = {
                    'type': 'sqlite',
                    'role': role,
                    'archive_path': archive_path,
                    'record_count': count,
                }
                if role == 'project' and project_id is not None:
                    database_info['project_id'] = project_id
                manifest['databases'].append(database_info)

            try:
                if mongo_enabled:
                    command = [
                        'mongodump', '--uri', settings.MONGODB_URI,
                        '--db', settings.MONGODB_DB, '--out', mongo_dump_dir,
                    ]
                    completed = subprocess.run(
                        command, capture_output=True, text=True, timeout=600
                    )
                    if completed.returncode:
                        raise RuntimeError(f'mongodump failed: {completed.stderr.strip()}')
                with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for file_info in manifest['files']:
                        archive.write(
                            os.path.join(staging_dir, *PurePosixPath(
                                file_info['archive_path']
                            ).parts),
                            file_info['archive_path'],
                        )
                    if mongo_enabled:
                        mongo_files = []
                        for root, _, files in os.walk(mongo_dump_dir):
                            for name in sorted(files):
                                path = os.path.join(root, name)
                                relative = os.path.relpath(path, mongo_dump_dir)
                                archive_path = PurePosixPath('mongo', *relative.split(os.sep)).as_posix()
                                file_info = _manifest_file(path, archive_path)
                                manifest['files'].append(file_info)
                                mongo_files.append(archive_path)
                                archive.write(path, archive_path)
                        manifest['databases'].append({
                            'type': 'mongodb',
                            'database': settings.MONGODB_DB,
                            'archive_paths': mongo_files,
                        })
                    archive.writestr(
                        'manifest.json',
                        json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'),
                    )
            finally:
                shutil.rmtree(mongo_dump_dir, ignore_errors=True)

        checksum = _sha256(backup_path)
        file_size = os.path.getsize(backup_path)

        with transaction.atomic():
            rec = BackupRecord(
                backup_type=backup_type,
                file_path=backup_path,
                file_size=file_size,
                checksum=checksum,
                record_count=record_count,
                status='ok',
                message=f'{"手动" if backup_type == "manual" else "系统启动自动"}备份',
                user_id=user.id if user else None,
            )
            rec.save()

        # 清理旧备份
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith('qor_recorder_') and f.endswith('.zip')],
            reverse=True,
        )
        for old in backups[max_backups:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass

        return {
            'ok': True,
            'id': rec.id,
            'file_path': backup_path,
            'file_size': file_size,
            'checksum': checksum,
            'record_count': record_count,
            'manifest_summary': {
                'version': BACKUP_FORMAT_VERSION,
                'created_at': manifest['created_at'],
                'persistence_mode': manifest['persistence_mode'],
                'schema': manifest['schema'],
                'database_count': len(manifest['databases']),
            },
        }
    except Exception as e:
        try:
            with transaction.atomic():
                fail_record = BackupRecord(
                    backup_type=backup_type,
                    status='failed',
                    message=str(e),
                )
                fail_record.save()
        except Exception:
            pass
        return {'ok': False, 'error': str(e)}


def verify_all_backups():
    """校验所有 ok 状态的备份文件"""
    results = {'total': 0, 'ok': 0, 'missing': 0, 'corrupted': 0, 'details': []}
    records = BackupRecord.objects.filter(status='ok')
    for rec in records:
        results['total'] += 1
        if not rec.checksum or not rec.file_path:
            continue
        if not os.path.exists(rec.file_path):
            results['missing'] += 1
            results['details'].append({'id': rec.id, 'status': 'missing', 'path': rec.file_path})
            continue
        h = hashlib.sha256()
        try:
            with open(rec.file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            actual = h.hexdigest()
            if actual == rec.checksum:
                results['ok'] += 1
                detail = {'id': rec.id, 'status': 'ok'}
                summary = read_backup_manifest_summary(rec.file_path)
                if summary:
                    detail['manifest'] = summary
                results['details'].append(detail)
            else:
                results['corrupted'] += 1
                results['details'].append({'id': rec.id, 'status': 'corrupted'})
        except Exception as e:
            results['details'].append({'id': rec.id, 'status': 'error', 'error': str(e)})
    return results


def read_backup_manifest_summary(backup_path):
    """Best-effort manifest summary for admin UI; returns None for legacy/unreadable."""
    try:
        with zipfile.ZipFile(backup_path, 'r') as archive:
            if 'manifest.json' not in archive.namelist():
                return {
                    'legacy': True,
                    'version': None,
                    'created_at': None,
                    'schema': None,
                    'databases': [],
                }
            manifest = json.loads(archive.read('manifest.json'))
    except Exception:
        return None
    if not isinstance(manifest, dict):
        return None
    databases = []
    for item in manifest.get('databases') or []:
        if not isinstance(item, dict):
            continue
        databases.append({
            'type': item.get('type'),
            'role': item.get('role'),
            'archive_path': item.get('archive_path'),
            'project_id': item.get('project_id'),
            'record_count': item.get('record_count'),
        })
    return {
        'legacy': False,
        'version': manifest.get('version'),
        'created_at': manifest.get('created_at'),
        'persistence_mode': manifest.get('persistence_mode'),
        'schema': manifest.get('schema'),
        'databases': databases,
    }