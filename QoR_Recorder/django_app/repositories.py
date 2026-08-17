"""Persistence boundary for heavy QoR data.

Reviews and configuration intentionally remain in Django's relational ORM.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Protocol

from django.conf import settings

from django_app.core.db_routing import _get_project_db_alias, get_project_engine

log = logging.getLogger(__name__)

COLLECTIONS = ('qor_records', 'raw_reports', 'violation_paths', 'run_notes')


class RepositoryError(RuntimeError):
    pass


class RecordRepository(Protocol):
    def list_records(self, project_id: int, *, module_id: int | None = None,
                     version: str | None = None, offset: int = 0,
                     limit: int = 50, release_only: bool = False) -> tuple[list[dict], int]: ...
    def get_record(self, project_id: int, record_id: str) -> dict | None: ...
    def get_raw_report(self, project_id: int, record_id: str) -> dict | None: ...
    def list_violations(self, project_id: int, record_id: str) -> list[dict]: ...
    def list_notes(self, project_id: int, record_id: str) -> list[dict]: ...
    def upsert_record(self, document: Mapping[str, Any]) -> str: ...
    def upsert_violation(self, document: Mapping[str, Any]) -> str: ...
    def upsert_note(self, document: Mapping[str, Any]) -> str: ...


def _global_id(project_id: int, legacy_module_id: int) -> int | None:
    from django_app.core.models import LegacyModuleMapping
    return LegacyModuleMapping.objects.filter(
        project_id=project_id, legacy_module_id=legacy_module_id
    ).values_list('module_id', flat=True).first()


class ORMRecordRepository:
    """Compatibility adapter over existing per-project SQLite rows."""
    def _alias(self, project_id: int) -> str:
        get_project_engine(project_id)
        return _get_project_db_alias(project_id)

    def _document(self, project_id: int, record) -> dict:
        value = record.to_dict()
        value['id'] = str(record.pk)
        value['project_id'] = project_id
        value['legacy_module_id'] = record.module_id
        value['module_id'] = _global_id(project_id, record.module_id)
        value.pop('raw_dc_report', None)  # raw data is lazy in API v2
        return value

    def list_records(self, project_id, *, module_id=None, version=None, offset=0, limit=50,
                     release_only=False):
        from django_app.core.models import LegacyModuleMapping, QorRecord
        from django.db.models.functions import Coalesce
        qs = QorRecord.objects.using(self._alias(project_id)).all()
        if module_id is not None:
            legacy_ids = LegacyModuleMapping.objects.filter(
                project_id=project_id, module_id=module_id
            ).values_list('legacy_module_id', flat=True)
            qs = qs.filter(module_id__in=list(legacy_ids))
        if version:
            qs = qs.filter(version=version)
        if release_only:
            qs = qs.filter(is_released=True)
        total = qs.count()
        rows = (
            qs.annotate(_effective_at=Coalesce('released_at', 'recorded_at'))
            .order_by('-_effective_at', '-id')[offset:offset + limit]
        )
        return [self._document(project_id, row) for row in rows], total

    def get_record(self, project_id, record_id):
        from django_app.core.models import QorRecord
        try:
            row = QorRecord.objects.using(self._alias(project_id)).get(pk=int(record_id))
        except (QorRecord.DoesNotExist, TypeError, ValueError):
            return None
        return self._document(project_id, row)

    def get_raw_report(self, project_id, record_id):
        from django_app.core.models import QorRecord
        try:
            row = QorRecord.objects.using(self._alias(project_id)).only('raw_dc_report').get(
                pk=int(record_id)
            )
        except (QorRecord.DoesNotExist, TypeError, ValueError):
            return None
        return {'record_id': str(row.pk), 'project_id': project_id, 'content': row.raw_dc_report}

    def list_violations(self, project_id, record_id):
        from django_app.core.models import ViolationPath
        rows = ViolationPath.objects.using(self._alias(project_id)).filter(
            qor_record_id=int(record_id)
        ).order_by('slack', 'id')
        values = [row.to_dict() for row in rows]
        for value in values:
            value['id'] = str(value['id'])
            value['record_id'] = str(value.pop('qor_record_id'))
            value['project_id'] = project_id
        return values

    def list_notes(self, project_id, record_id):
        from django_app.core.models import RunNote
        rows = RunNote.objects.using(self._alias(project_id)).filter(
            qor_record_id=int(record_id)
        ).order_by('seq', 'id')
        values = [row.to_dict() for row in rows]
        for value in values:
            value['id'] = str(value['id'])
            value['record_id'] = str(value.pop('qor_record_id'))
            value['project_id'] = project_id
        return values

    def upsert_record(self, document):
        raise RepositoryError('ORM writes must use the existing import service transaction')

    def upsert_violation(self, document):
        raise RepositoryError('ORM writes must use the existing import service transaction')

    def upsert_note(self, document):
        raise RepositoryError('ORM writes must use the existing import service transaction')


_mongo_client = None


def get_mongo_client():
    """Build the client lazily; importing Django settings never opens a socket."""
    global _mongo_client
    if _mongo_client is None:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RepositoryError('pymongo is required for MongoDB persistence') from exc
        _mongo_client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=getattr(settings, 'MONGODB_TIMEOUT_MS', 2000),
            connect=False,
        )
    return _mongo_client


def get_mongo_database():
    return get_mongo_client()[settings.MONGODB_DB]


def ensure_mongo_indexes(database=None):
    db = database or get_mongo_database()
    db.qor_records.create_index([('project_id', 1), ('module_id', 1), ('version', 1)])
    db.qor_records.create_index([('project_id', 1), ('recorded_at', -1)])
    db.qor_records.create_index([('project_id', 1), ('full_dir', 1)])
    db.raw_reports.create_index([('project_id', 1), ('record_id', 1)], unique=True)
    db.violation_paths.create_index([('project_id', 1), ('record_id', 1), ('slack', 1)])
    db.run_notes.create_index([('project_id', 1), ('record_id', 1), ('seq', 1)])


class MongoRecordRepository:
    def __init__(self, database=None):
        self.db = database or get_mongo_database()

    @staticmethod
    def _clean(document):
        if not document:
            return document
        value = dict(document)
        value['id'] = str(value.pop('_id', value.get('id', '')))
        return value

    def list_records(self, project_id, *, module_id=None, version=None, offset=0, limit=50,
                     release_only=False):
        query: dict[str, Any] = {'project_id': project_id}
        if module_id is not None:
            query['module_id'] = module_id
        if version:
            query['version'] = version
        if release_only:
            query['is_released'] = True
        collection = self.db.qor_records
        total = collection.count_documents(query)
        cursor = collection.find(query, {'raw_dc_report': 0}).sort(
            [('recorded_at', -1), ('_id', -1)]
        ).skip(offset).limit(limit)
        return [self._clean(row) for row in cursor], total

    def get_record(self, project_id, record_id):
        from bson import ObjectId
        query = {'project_id': project_id}
        try:
            query['_id'] = ObjectId(record_id)
        except Exception:
            query['legacy_id'] = record_id
        return self._clean(self.db.qor_records.find_one(query, {'raw_dc_report': 0}))

    def get_raw_report(self, project_id, record_id):
        return self._clean(self.db.raw_reports.find_one(
            {'project_id': project_id, 'record_id': record_id}
        ))

    def list_violations(self, project_id, record_id):
        return [self._clean(row) for row in self.db.violation_paths.find(
            {'project_id': project_id, 'record_id': record_id}
        ).sort([('slack', 1), ('_id', 1)])]

    def list_notes(self, project_id, record_id):
        return [self._clean(row) for row in self.db.run_notes.find(
            {'project_id': project_id, 'record_id': record_id}
        ).sort([('seq', 1), ('_id', 1)])]

    def upsert_record(self, document):
        value = dict(document)
        raw = value.pop('raw_dc_report', None)
        identity = {
            'project_id': value['project_id'],
            'legacy_id': str(value.get('legacy_id') or value.get('id')),
        }
        value.pop('id', None)
        result = self.db.qor_records.update_one(identity, {'$set': value}, upsert=True)
        row = self.db.qor_records.find_one(identity, {'_id': 1})
        record_id = str(row['_id'])
        if raw is not None:
            self.db.raw_reports.update_one(
                {'project_id': value['project_id'], 'record_id': record_id},
                {'$set': {'content': raw}}, upsert=True,
            )
        return record_id

    def _record_reference(self, project_id, value):
        row = self.db.qor_records.find_one(
            {'project_id': project_id, 'legacy_id': str(value)}, {'_id': 1}
        )
        return str(row['_id']) if row else str(value)

    def _upsert_child(self, collection_name, document):
        value = dict(document)
        value['record_id'] = self._record_reference(value['project_id'], value['record_id'])
        legacy_id = str(value.pop('id', value.get('legacy_id', '')))
        value['legacy_id'] = legacy_id
        result = self.db[collection_name].update_one(
            {'project_id': value['project_id'], 'legacy_id': legacy_id},
            {'$set': value}, upsert=True,
        )
        row = self.db[collection_name].find_one(
            {'project_id': value['project_id'], 'legacy_id': legacy_id}, {'_id': 1}
        )
        return str(row['_id'])

    def upsert_violation(self, document):
        return self._upsert_child('violation_paths', document)

    def upsert_note(self, document):
        return self._upsert_child('run_notes', document)


class HybridRecordRepository:
    """Mongo-primary reads and dual writes with explicit failure reporting."""
    def __init__(self, orm=None, mongo=None):
        self.orm = orm or ORMRecordRepository()
        self.mongo = mongo or MongoRecordRepository()

    def _read(self, method, *args, **kwargs):
        try:
            result = getattr(self.mongo, method)(*args, **kwargs)
            if result and result != ([], 0):
                return result
        except Exception:
            log.exception('Mongo read failed; using ORM fallback')
        return getattr(self.orm, method)(*args, **kwargs)

    def list_records(self, *args, **kwargs): return self._read('list_records', *args, **kwargs)
    def get_record(self, *args, **kwargs): return self._read('get_record', *args, **kwargs)
    def get_raw_report(self, *args, **kwargs): return self._read('get_raw_report', *args, **kwargs)
    def list_violations(self, *args, **kwargs): return self._read('list_violations', *args, **kwargs)
    def list_notes(self, *args, **kwargs): return self._read('list_notes', *args, **kwargs)

    def upsert_record(self, document):
        # Existing import code owns the relational transaction. This method
        # mirrors its committed document to Mongo and never hides a failure.
        return self.mongo.upsert_record(document)

    def upsert_violation(self, document):
        return self.mongo.upsert_violation(document)

    def upsert_note(self, document):
        return self.mongo.upsert_note(document)


def get_record_repository(mode=None) -> RecordRepository:
    mode = (mode or settings.PERSISTENCE_MODE).strip().lower()
    if mode == 'orm':
        return ORMRecordRepository()
    if mode == 'mongo':
        return MongoRecordRepository()
    if mode == 'hybrid':
        return HybridRecordRepository()
    raise RepositoryError(f'unsupported PERSISTENCE_MODE: {mode}')


def mongo_readiness() -> dict:
    if settings.PERSISTENCE_MODE == 'orm':
        return {'enabled': False, 'ready': True}
    try:
        get_mongo_client().admin.command('ping')
        return {'enabled': True, 'ready': True}
    except Exception as exc:
        return {'enabled': True, 'ready': False, 'error': str(exc)}
