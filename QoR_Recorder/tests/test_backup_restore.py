import json
import os
import sqlite3
import zipfile
from contextlib import nullcontext
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_app.services import backup_service


def _create_sqlite(path, values):
    connection = sqlite3.connect(path)
    try:
        connection.execute('CREATE TABLE qor_records (id INTEGER PRIMARY KEY, value TEXT)')
        connection.executemany(
            'INSERT INTO qor_records(value) VALUES (?)',
            [(value,) for value in values],
        )
        connection.commit()
    finally:
        connection.close()


def _values(path):
    connection = sqlite3.connect(path)
    try:
        return [
            row[0] for row in connection.execute(
                'SELECT value FROM qor_records ORDER BY id'
            )
        ]
    finally:
        connection.close()


def _configure_backup(monkeypatch, data_dir, backup_dir):
    monkeypatch.setattr(
        backup_service.settings,
        'DATABASES',
        {'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(data_dir / 'qor_recorder.db'),
        }},
    )
    monkeypatch.setattr(backup_service.settings, 'DATA_DIR', data_dir, raising=False)
    monkeypatch.setattr(backup_service.settings, 'BACKUP_DIR', str(backup_dir))
    monkeypatch.setattr(backup_service.settings, 'MAX_BACKUPS', 10, raising=False)
    monkeypatch.setattr(backup_service.settings, 'PERSISTENCE_MODE', 'orm')

    class FakeBackupRecord:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.id = 1

        def save(self):
            return None

    monkeypatch.setattr(backup_service, 'BackupRecord', FakeBackupRecord)
    monkeypatch.setattr(backup_service.transaction, 'atomic', nullcontext)


def _make_backup(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    backup_dir = tmp_path / 'backups'
    data_dir.mkdir()
    backup_dir.mkdir()
    _create_sqlite(data_dir / 'qor_recorder.db', ['main-a', 'main-b'])
    _create_sqlite(data_dir / 'qor_p_1.db', ['p1-a', 'p1-b', 'p1-c'])
    _configure_backup(monkeypatch, data_dir, backup_dir)
    result = backup_service.perform_backup('manual')
    assert result['ok'], result
    return data_dir, result


def test_backup_manifest_and_cross_project_record_count(monkeypatch, tmp_path):
    _, result = _make_backup(monkeypatch, tmp_path)

    assert result['record_count'] == 5
    with zipfile.ZipFile(result['file_path']) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['version'] == backup_service.BACKUP_FORMAT_VERSION
        assert manifest['created_at']
        assert 'schema' in manifest
        assert manifest['schema']['backup_format_version'] == backup_service.BACKUP_FORMAT_VERSION
        assert isinstance(manifest['schema'].get('django_migrations'), dict)
        assert {item['archive_path'] for item in manifest['files']} == {
            'sql/qor_recorder.db',
            'sql/qor_p_1.db',
        }
        assert sum(db['record_count'] for db in manifest['databases']) == 5
        for item in manifest['files']:
            payload = archive.read(item['archive_path'])
            assert item['size'] == len(payload)
            assert len(item['sha256']) == 64


def test_backup_and_restore_syn_qor_databases(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    backup_dir = tmp_path / 'backups'
    data_dir.mkdir()
    backup_dir.mkdir()
    _create_sqlite(data_dir / 'qor_recorder.db', ['main-a'])
    _create_sqlite(data_dir / 'demo_syn_qor.db', ['syn-a', 'syn-b'])
    _configure_backup(monkeypatch, data_dir, backup_dir)

    result = backup_service.perform_backup('manual')
    assert result['ok'], result
    with zipfile.ZipFile(result['file_path']) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert 'sql/demo_syn_qor.db' in {item['archive_path'] for item in manifest['files']}
        assert manifest['schema']['backup_format_version'] == backup_service.BACKUP_FORMAT_VERSION

    restore_command = __import__(
        'django_app.core.management.commands.restore_backup',
        fromlist=['restore_backup'],
    )
    monkeypatch.setattr(
        restore_command,
        'perform_backup',
        lambda **kwargs: {'ok': True, 'file_path': str(tmp_path / 'pre-restore.zip')},
    )
    (data_dir / 'demo_syn_qor.db').unlink()
    _create_sqlite(data_dir / 'demo_syn_qor.db', ['changed'])
    (data_dir / 'qor_recorder.db').unlink()
    _create_sqlite(data_dir / 'qor_recorder.db', ['changed-main'])

    call_command('restore_backup', result['file_path'], '--apply', stdout=StringIO())

    assert _values(data_dir / 'qor_recorder.db') == ['main-a']
    assert _values(data_dir / 'demo_syn_qor.db') == ['syn-a', 'syn-b']


def test_restore_apply_fails_when_maintenance_lock_held(monkeypatch, tmp_path):
    data_dir, result = _make_backup(monkeypatch, tmp_path)
    restore_command = __import__(
        'django_app.core.management.commands.restore_backup',
        fromlist=['restore_backup'],
    )
    monkeypatch.setattr(
        restore_command,
        'perform_backup',
        lambda **kwargs: {'ok': True, 'file_path': str(tmp_path / 'pre-restore.zip')},
    )
    lock_path = backup_service.maintenance_lock_path()
    with open(lock_path, 'w', encoding='utf-8') as stream:
        stream.write('held')

    with pytest.raises(CommandError, match='maintenance lock held'):
        call_command('restore_backup', result['file_path'], '--apply', stdout=StringIO())

    assert _values(data_dir / 'qor_recorder.db') == ['main-a', 'main-b']
    assert os.path.exists(lock_path)


def test_restore_defaults_to_verified_dry_run(monkeypatch, tmp_path):
    _, result = _make_backup(monkeypatch, tmp_path)
    output = StringIO()

    call_command('restore_backup', result['file_path'], stdout=output)

    assert 'DRY-RUN verified=2' in output.getvalue()
    assert 'would restore:' in output.getvalue()


def test_restore_apply_replaces_main_and_project_databases(monkeypatch, tmp_path):
    data_dir, result = _make_backup(monkeypatch, tmp_path)
    restore_command = __import__(
        'django_app.core.management.commands.restore_backup',
        fromlist=['restore_backup'],
    )
    monkeypatch.setattr(
        restore_command,
        'perform_backup',
        lambda **kwargs: {
            'ok': True,
            'file_path': str(tmp_path / 'pre-restore.zip'),
        },
    )

    for path, values in (
        (data_dir / 'qor_recorder.db', ['changed-main']),
        (data_dir / 'qor_p_1.db', ['changed-project']),
    ):
        path.unlink()
        _create_sqlite(path, values)

    call_command('restore_backup', result['file_path'], '--apply', stdout=StringIO())

    assert _values(data_dir / 'qor_recorder.db') == ['main-a', 'main-b']
    assert _values(data_dir / 'qor_p_1.db') == ['p1-a', 'p1-b', 'p1-c']
    assert not list(data_dir.glob('*.restore-*'))


def test_restore_rolls_back_all_databases_after_replace_failure(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    extraction_dir = tmp_path / 'extracted'
    (extraction_dir / 'sql').mkdir(parents=True)
    data_dir.mkdir()
    _create_sqlite(data_dir / 'qor_recorder.db', ['original-main'])
    _create_sqlite(data_dir / 'qor_p_1.db', ['original-project'])
    _create_sqlite(extraction_dir / 'sql' / 'qor_recorder.db', ['backup-main'])
    _create_sqlite(extraction_dir / 'sql' / 'qor_p_1.db', ['backup-project'])
    _configure_backup(monkeypatch, data_dir, tmp_path / 'backups')
    restore_command = __import__(
        'django_app.core.management.commands.restore_backup',
        fromlist=['restore_backup'],
    )
    real_replace = restore_command._replace_with_retry
    failed = False

    def fail_second_database(source, destination):
        nonlocal failed
        if (
            not failed
            and '.restore-new-' in source
            and destination.endswith('qor_p_1.db')
        ):
            failed = True
            raise OSError('simulated replacement failure')
        return real_replace(source, destination)

    monkeypatch.setattr(restore_command, '_replace_with_retry', fail_second_database)

    with pytest.raises(OSError, match='simulated replacement failure'):
        restore_command._apply_sqlite(
            str(extraction_dir),
            ['sql/qor_recorder.db', 'sql/qor_p_1.db'],
        )

    assert _values(data_dir / 'qor_recorder.db') == ['original-main']
    assert _values(data_dir / 'qor_p_1.db') == ['original-project']
    assert not list(data_dir.glob('*.restore-*'))


def test_restore_supports_legacy_backup(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    database = data_dir / 'legacy.db'
    _create_sqlite(database, ['legacy'])
    backup = tmp_path / 'legacy.zip'
    with zipfile.ZipFile(backup, 'w') as archive:
        archive.write(database, 'sql/qor_recorder.db')
    _configure_backup(monkeypatch, data_dir, tmp_path / 'unused')
    output = StringIO()

    call_command('restore_backup', str(backup), '--verify', stdout=output)

    assert 'VERIFIED files=1 legacy=True' in output.getvalue()


def test_restore_rejects_zip_slip(tmp_path):
    backup = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(backup, 'w') as archive:
        archive.writestr('../escaped.db', b'not a database')

    with pytest.raises(CommandError, match='unsafe archive path'):
        call_command('restore_backup', str(backup), stdout=StringIO())


def test_restore_rejects_manifest_checksum_mismatch(monkeypatch, tmp_path):
    _, result = _make_backup(monkeypatch, tmp_path)
    corrupt = tmp_path / 'corrupt.zip'
    with zipfile.ZipFile(result['file_path']) as source, zipfile.ZipFile(corrupt, 'w') as target:
        manifest = json.loads(source.read('manifest.json'))
        manifest['files'][0]['sha256'] = '0' * 64
        for info in source.infolist():
            payload = (
                json.dumps(manifest).encode()
                if info.filename == 'manifest.json'
                else source.read(info.filename)
            )
            target.writestr(info.filename, payload)

    with pytest.raises(CommandError, match='checksum mismatch'):
        call_command('restore_backup', str(corrupt), '--verify', stdout=StringIO())


def test_restore_refuses_apply_when_mongo_content_exists(monkeypatch, tmp_path):
    _, result = _make_backup(monkeypatch, tmp_path)
    mongo_backup = tmp_path / 'mongo.zip'
    with zipfile.ZipFile(result['file_path']) as source, zipfile.ZipFile(mongo_backup, 'w') as target:
        manifest = json.loads(source.read('manifest.json'))
        mongo_payload = b'mongo dump'
        import hashlib
        manifest['files'].append({
            'archive_path': 'mongo/qor/records.bson',
            'size': len(mongo_payload),
            'sha256': hashlib.sha256(mongo_payload).hexdigest(),
        })
        manifest['databases'].append({
            'type': 'mongodb',
            'database': 'qor',
            'archive_paths': ['mongo/qor/records.bson'],
        })
        for info in source.infolist():
            if info.filename != 'manifest.json':
                target.writestr(info.filename, source.read(info.filename))
        target.writestr('mongo/qor/records.bson', mongo_payload)
        target.writestr('manifest.json', json.dumps(manifest))

    with pytest.raises(CommandError, match='consistent MongoDB restore'):
        call_command('restore_backup', str(mongo_backup), '--apply', stdout=StringIO())


def test_backup_manifest_includes_migration_version(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    backup_dir = tmp_path / 'backups'
    data_dir.mkdir()
    backup_dir.mkdir()
    _create_sqlite(data_dir / 'qor_recorder.db', ['main'])
    _configure_backup(monkeypatch, data_dir, backup_dir)
    monkeypatch.setattr(
        backup_service,
        '_migration_versions',
        lambda: {'core': '0012_review_snapshot_binding'},
    )

    result = backup_service.perform_backup('manual')
    assert result['ok'], result
    with zipfile.ZipFile(result['file_path']) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    assert manifest['schema']['django_migrations']['core'] == '0012_review_snapshot_binding'
    assert result['manifest_summary']['schema']['django_migrations']['core'] == (
        '0012_review_snapshot_binding'
    )


def test_restore_supports_syn_qor_project_databases(monkeypatch, tmp_path):
    data_dir = tmp_path / 'data'
    backup_dir = tmp_path / 'backups'
    data_dir.mkdir()
    backup_dir.mkdir()
    _create_sqlite(data_dir / 'qor_recorder.db', ['main-a'])
    _create_sqlite(data_dir / 'newproject_syn_qor.db', ['syn-a', 'syn-b'])
    _configure_backup(monkeypatch, data_dir, backup_dir)
    result = backup_service.perform_backup('manual')
    assert result['ok'], result

    restore_command = __import__(
        'django_app.core.management.commands.restore_backup',
        fromlist=['restore_backup'],
    )
    monkeypatch.setattr(
        restore_command,
        'perform_backup',
        lambda **kwargs: {'ok': True, 'file_path': str(tmp_path / 'pre-restore.zip')},
    )

    (data_dir / 'qor_recorder.db').unlink()
    (data_dir / 'newproject_syn_qor.db').unlink()
    _create_sqlite(data_dir / 'qor_recorder.db', ['changed-main'])
    _create_sqlite(data_dir / 'newproject_syn_qor.db', ['changed-syn'])

    call_command('restore_backup', result['file_path'], '--apply', stdout=StringIO())

    assert _values(data_dir / 'qor_recorder.db') == ['main-a']
    assert _values(data_dir / 'newproject_syn_qor.db') == ['syn-a', 'syn-b']


def test_restore_apply_fails_when_maintenance_lock_held(monkeypatch, tmp_path):
    data_dir, result = _make_backup(monkeypatch, tmp_path)
    restore_command = __import__(
        'django_app.core.management.commands.restore_backup',
        fromlist=['restore_backup'],
    )
    monkeypatch.setattr(
        restore_command,
        'perform_backup',
        lambda **kwargs: {'ok': True, 'file_path': str(tmp_path / 'pre-restore.zip')},
    )
    lock_path = backup_service.maintenance_lock_path()
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, 'w', encoding='utf-8') as handle:
        handle.write('held')

    with pytest.raises(CommandError, match='maintenance lock held'):
        call_command('restore_backup', result['file_path'], '--apply', stdout=StringIO())

    assert _values(data_dir / 'qor_recorder.db') == ['main-a', 'main-b']
    assert os.path.exists(lock_path)
