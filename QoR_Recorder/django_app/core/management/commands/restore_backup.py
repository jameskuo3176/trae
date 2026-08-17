import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile
from pathlib import PurePosixPath

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from django_app.services.backup_service import BACKUP_FORMAT_VERSION, MaintenanceLock, perform_backup


_PROJECT_DB_RE = re.compile(r'^qor_p_(\d+)\.db$')
_SYN_QOR_RE = re.compile(r'^[A-Za-z0-9._-]+_syn_qor\.db$')
_HASH_CHUNK_SIZE = 1024 * 1024


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_name(name):
    """Return a canonical ZIP path or reject paths unsafe on Windows/POSIX."""
    if not name or '\x00' in name or '\\' in name:
        raise CommandError(f'unsafe archive path: {name!r}')
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ('', '.', '..') for part in path.parts):
        raise CommandError(f'unsafe archive path: {name!r}')
    if path.parts and (':' in path.parts[0] or path.parts[0].startswith('~')):
        raise CommandError(f'unsafe archive path: {name!r}')
    return path.as_posix()


def _validate_members(archive):
    names = {}
    for info in archive.infolist():
        name = _safe_archive_name(info.filename.rstrip('/'))
        if info.is_dir():
            continue
        folded = name.casefold()
        if folded in names:
            raise CommandError(f'duplicate archive path: {name}')
        names[folded] = name
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise CommandError(f'symlink is not allowed in backup: {name}')
    return names


def _extract_safely(archive, destination):
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = _safe_archive_name(info.filename)
        target = os.path.join(destination, *PurePosixPath(name).parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with archive.open(info) as source, open(target, 'wb') as output:
            shutil.copyfileobj(source, output)


def _verify_sqlite(path, archive_path):
    try:
        connection = sqlite3.connect(f'file:{os.path.abspath(path)}?mode=ro', uri=True)
        try:
            result = connection.execute('PRAGMA integrity_check').fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise CommandError(f'invalid SQLite database {archive_path}: {exc}') from exc
    if not result or result[0] != 'ok':
        detail = result[0] if result else 'no result'
        raise CommandError(f'SQLite integrity check failed for {archive_path}: {detail}')


def _load_and_verify(backup_path, extraction_dir):
    try:
        archive = zipfile.ZipFile(backup_path, 'r')
    except (OSError, zipfile.BadZipFile) as exc:
        raise CommandError(f'cannot open backup: {exc}') from exc

    with archive:
        members = _validate_members(archive)
        bad_member = archive.testzip()
        if bad_member:
            raise CommandError(f'ZIP CRC check failed: {bad_member}')
        _extract_safely(archive, extraction_dir)

    manifest_path = os.path.join(extraction_dir, 'manifest.json')
    legacy = not os.path.exists(manifest_path)
    if legacy:
        sqlite_entries = sorted(
            name for name in members.values()
            if name.startswith('sql/') and name.endswith('.db')
        )
        if not sqlite_entries:
            raise CommandError('legacy backup contains no SQLite database')
        manifest = None
    else:
        try:
            with open(manifest_path, encoding='utf-8') as stream:
                manifest = json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f'invalid manifest.json: {exc}') from exc
        if not isinstance(manifest, dict):
            raise CommandError('manifest.json must contain an object')
        if manifest.get('version') != BACKUP_FORMAT_VERSION:
            raise CommandError(
                f'unsupported backup manifest version: {manifest.get("version")!r}'
            )
        files = manifest.get('files')
        databases = manifest.get('databases')
        if not isinstance(files, list) or not isinstance(databases, list):
            raise CommandError('manifest files/databases must be lists')

        listed = set()
        for item in files:
            if not isinstance(item, dict):
                raise CommandError('invalid file entry in manifest')
            archive_path = _safe_archive_name(item.get('archive_path', ''))
            if archive_path.casefold() in listed:
                raise CommandError(f'duplicate manifest file: {archive_path}')
            listed.add(archive_path.casefold())
            if archive_path.casefold() not in members:
                raise CommandError(f'manifest file is missing: {archive_path}')
            extracted = os.path.join(extraction_dir, *PurePosixPath(archive_path).parts)
            if os.path.getsize(extracted) != item.get('size'):
                raise CommandError(f'file size mismatch: {archive_path}')
            expected_hash = item.get('sha256')
            if not isinstance(expected_hash, str) or _sha256(extracted) != expected_hash:
                raise CommandError(f'checksum mismatch: {archive_path}')

        archived_files = {
            name.casefold() for name in members.values()
            if name != 'manifest.json' and not name.endswith('/')
        }
        if listed != archived_files:
            raise CommandError('manifest does not describe every archived file')

        sqlite_entries = []
        for database in databases:
            if not isinstance(database, dict):
                raise CommandError('invalid database entry in manifest')
            if database.get('type') == 'sqlite':
                archive_path = _safe_archive_name(database.get('archive_path', ''))
                if archive_path.casefold() not in listed:
                    raise CommandError(f'database is absent from file list: {archive_path}')
                sqlite_entries.append(archive_path)
        if len({path.casefold() for path in sqlite_entries}) != len(sqlite_entries):
            raise CommandError('duplicate SQLite database in inventory')
        archived_sqlite = {
            item['archive_path'] for item in files
            if (
                isinstance(item, dict)
                and isinstance(item.get('archive_path'), str)
                and item['archive_path'].startswith('sql/')
                and item['archive_path'].endswith('.db')
            )
        }
        if set(sqlite_entries) != archived_sqlite:
            raise CommandError('SQLite database inventory does not match archived files')
        if 'sql/qor_recorder.db' not in sqlite_entries:
            raise CommandError('main SQLite database is missing from inventory')

    for archive_path in sqlite_entries:
        extracted = os.path.join(extraction_dir, *PurePosixPath(archive_path).parts)
        _verify_sqlite(extracted, archive_path)

    has_mongo = any(name.startswith('mongo/') for name in members.values())
    if manifest:
        has_mongo = has_mongo or any(
            isinstance(item, dict) and item.get('type') == 'mongodb'
            for item in manifest.get('databases', [])
        )
    return {
        'legacy': legacy,
        'manifest': manifest,
        'sqlite_entries': sqlite_entries,
        'has_mongo': has_mongo,
    }


def _destination_for(archive_path):
    name = PurePosixPath(archive_path).name
    if archive_path == 'sql/qor_recorder.db':
        return os.path.abspath(settings.DATABASES['default']['NAME'])
    data_dir = os.path.abspath(str(getattr(
        settings, 'DATA_DIR', os.path.dirname(settings.DATABASES['default']['NAME'])
    )))
    if archive_path != f'sql/{name}':
        raise CommandError(f'unsupported SQLite archive path: {archive_path}')
    if _PROJECT_DB_RE.fullmatch(name) or _SYN_QOR_RE.fullmatch(name):
        return os.path.join(data_dir, name)
    raise CommandError(f'unsupported SQLite archive path: {archive_path}')


def _replace_with_retry(source, destination):
    last_error = None
    for delay in (0, 0.1, 0.25, 0.5):
        if delay:
            time.sleep(delay)
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            last_error = exc
    raise last_error


def _apply_sqlite(extraction_dir, sqlite_entries):
    """Replace databases from same-directory staging files and roll back on error."""
    token = uuid.uuid4().hex
    operations = []
    connections.close_all()
    try:
        for archive_path in sqlite_entries:
            source = os.path.join(extraction_dir, *PurePosixPath(archive_path).parts)
            destination = _destination_for(archive_path)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            staged = f'{destination}.restore-new-{token}'
            operation = {'destination': destination, 'staged': staged, 'moved': []}
            operations.append(operation)
            shutil.copy2(source, staged)
            _verify_sqlite(staged, archive_path)
            for current in (destination, f'{destination}-wal', f'{destination}-shm'):
                if os.path.exists(current):
                    rollback = f'{current}.restore-old-{token}'
                    _replace_with_retry(current, rollback)
                    operation['moved'].append((current, rollback))
            _replace_with_retry(staged, destination)
    except Exception:
        connections.close_all()
        for operation in reversed(operations):
            destination = operation['destination']
            try:
                if os.path.exists(destination):
                    os.remove(destination)
            except OSError:
                pass
            for original, rollback in reversed(operation['moved']):
                try:
                    if os.path.exists(rollback):
                        _replace_with_retry(rollback, original)
                except OSError:
                    pass
            try:
                if os.path.exists(operation['staged']):
                    os.remove(operation['staged'])
            except OSError:
                pass
        raise
    else:
        for operation in operations:
            for _, rollback in operation['moved']:
                try:
                    os.remove(rollback)
                except OSError:
                    pass
    finally:
        connections.close_all()


class Command(BaseCommand):
    help = 'Verify or restore a QoR Recorder backup; defaults to dry-run'

    def add_arguments(self, parser):
        parser.add_argument('backup_path')
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--dry-run', action='store_true', help='validate and show restore plan')
        mode.add_argument('--verify', action='store_true', help='validate without restoring')
        mode.add_argument('--apply', action='store_true', help='restore SQLite databases')

    def handle(self, *args, **options):
        backup_path = os.path.abspath(options['backup_path'])
        if not os.path.isfile(backup_path):
            raise CommandError(f'backup does not exist: {backup_path}')

        with tempfile.TemporaryDirectory(prefix='qor_restore_') as extraction_dir:
            result = _load_and_verify(backup_path, extraction_dir)
            if options['verify']:
                self.stdout.write(self.style.SUCCESS(
                    f'VERIFIED files={len(result["sqlite_entries"])} '
                    f'legacy={result["legacy"]}'
                ))
                return

            if not options['apply']:
                targets = [
                    _destination_for(path) for path in result['sqlite_entries']
                ]
                self.stdout.write(
                    f'DRY-RUN verified={len(result["sqlite_entries"])} '
                    f'legacy={result["legacy"]}'
                )
                for target in targets:
                    self.stdout.write(f'would restore: {target}')
                if result['has_mongo']:
                    self.stdout.write(
                        self.style.WARNING('MongoDB content detected; --apply would be refused')
                    )
                return

            if result['has_mongo']:
                raise CommandError(
                    'backup contains MongoDB content; a consistent MongoDB restore cannot '
                    'be guaranteed, so --apply is refused'
                )
            if getattr(settings, 'PERSISTENCE_MODE', 'orm') != 'orm':
                raise CommandError(
                    'Mongo/hybrid persistence mode detected; refuse automatic SQLite-only '
                    '--apply. Restore Mongo separately, or switch to orm mode for SQLite apply.'
                )
            schema = (result.get('manifest') or {}).get('schema') if result.get('manifest') else None
            if schema:
                self.stdout.write(
                    f"manifest schema apps={','.join(schema.get('migration_apps') or [])}"
                )
            pre_restore = perform_backup(backup_type='pre_restore')
            if not pre_restore.get('ok'):
                raise CommandError(
                    f'pre-restore backup failed: {pre_restore.get("error", "unknown error")}'
                )
            try:
                with MaintenanceLock():
                    _apply_sqlite(extraction_dir, result['sqlite_entries'])
            except RuntimeError as exc:
                raise CommandError(str(exc)) from exc
            except Exception as exc:
                raise CommandError(f'restore failed; rollback attempted: {exc}') from exc
            self.stdout.write(self.style.SUCCESS(
                f'APPLIED databases={len(result["sqlite_entries"])} '
                f'pre_restore_backup={pre_restore["file_path"]}'
            ))
