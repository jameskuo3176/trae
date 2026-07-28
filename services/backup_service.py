"""备份服务

封装 DB 备份、校验等业务逻辑。
"""
import hashlib
import os
import shutil
from datetime import datetime

from flask import current_app

from models import db, QorRecord, BackupRecord


def perform_backup(backup_type='auto', user=None):
    """执行数据库备份

    Args:
        backup_type: 备份类型 ('auto' / 'manual')
        user: 触发用户 (manual 时)

    Returns:
        dict: 备份结果
    """
    try:
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if not db_uri.startswith('sqlite'):
            return {'ok': False, 'error': '仅支持 SQLite 自动备份'}

        # 从 URI 提取 db 路径
        db_path = db_uri.replace('sqlite:///', '')
        if not os.path.exists(db_path):
            return {'ok': False, 'error': f'数据库文件不存在: {db_path}'}

        backup_dir = current_app.config.get('BACKUP_DIR', 'backups')
        max_backups = current_app.config.get('MAX_BACKUPS', 10)
        os.makedirs(backup_dir, exist_ok=True)

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'qor_recorder_{ts}.db')
        shutil.copy2(db_path, backup_path)

        h = hashlib.sha256()
        with open(backup_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        checksum = h.hexdigest()
        file_size = os.path.getsize(backup_path)

        try:
            record_count = QorRecord.query.count()
        except Exception:
            record_count = 0

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
        db.session.add(rec)
        db.session.commit()

        # 清理旧备份
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith('qor_recorder_') and f.endswith('.db')],
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
            fail_record = BackupRecord(
                backup_type=backup_type,
                status='failed',
                message=str(e),
            )
            db.session.add(fail_record)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return {'ok': False, 'error': str(e)}


def verify_all_backups():
    """校验所有 ok 状态的备份文件"""
    results = {'total': 0, 'ok': 0, 'missing': 0, 'corrupted': 0, 'details': []}
    records = BackupRecord.query.filter_by(status='ok').all()
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
