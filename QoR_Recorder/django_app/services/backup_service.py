"""备份服务

封装 DB 备份、校验等业务逻辑（Django 版本）。
"""
import hashlib
import os
import shutil
import subprocess
import zipfile
from datetime import datetime

from django.conf import settings
from django.db import transaction

from django_app.core.models import QorRecord, BackupRecord


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

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'qor_recorder_{ts}.zip')
        mongo_enabled = getattr(settings, 'PERSISTENCE_MODE', 'orm') != 'orm'
        mongo_dump_dir = os.path.join(backup_dir, f'.mongo_{ts}')
        if mongo_enabled:
            command = [
                'mongodump', '--uri', settings.MONGODB_URI,
                '--db', settings.MONGODB_DB, '--out', mongo_dump_dir,
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
            if completed.returncode:
                raise RuntimeError(f'mongodump failed: {completed.stderr.strip()}')
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(db_path, 'sql/qor_recorder.db')
                data_dir = os.path.dirname(db_path)
                for name in os.listdir(data_dir):
                    if name.startswith('qor_p_') and name.endswith('.db'):
                        archive.write(os.path.join(data_dir, name), f'sql/{name}')
                if mongo_enabled:
                    for root, _, files in os.walk(mongo_dump_dir):
                        for name in files:
                            path = os.path.join(root, name)
                            archive.write(path, os.path.join('mongo', os.path.relpath(path, mongo_dump_dir)))
        finally:
            shutil.rmtree(mongo_dump_dir, ignore_errors=True)

        h = hashlib.sha256()
        with open(backup_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        checksum = h.hexdigest()
        file_size = os.path.getsize(backup_path)

        try:
            record_count = QorRecord.objects.count()
        except Exception:
            record_count = 0

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
                results['details'].append({'id': rec.id, 'status': 'ok'})
            else:
                results['corrupted'] += 1
                results['details'].append({'id': rec.id, 'status': 'corrupted'})
        except Exception as e:
            results['details'].append({'id': rec.id, 'status': 'error', 'error': str(e)})
    return results