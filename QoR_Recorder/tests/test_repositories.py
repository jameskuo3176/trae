import mongomock
import pytest
from django.test import override_settings

from django_app.repositories import (
    HybridRecordRepository, MongoRecordRepository, ORMRecordRepository, RepositoryError,
    ensure_mongo_indexes, get_record_repository,
)


def test_mongo_adapter_round_trip_and_indexes():
    db = mongomock.MongoClient().qor_test
    ensure_mongo_indexes(db)
    repository = MongoRecordRepository(db)
    record_id = repository.upsert_record({
        'id': '7', 'project_id': 3, 'module_id': 11,
        'version': 'regr_a', 'raw_dc_report': 'raw',
    })
    rows, total = repository.list_records(3)
    assert total == 1
    assert rows[0]['id'] == record_id
    assert repository.get_raw_report(3, record_id)['content'] == 'raw'
    assert 'raw_dc_report' not in rows[0]
    violation_id = repository.upsert_violation({
        'id': '9', 'project_id': 3, 'record_id': '7', 'slack': -0.1,
    })
    violations = repository.list_violations(3, record_id)
    assert violations[0]['id'] == violation_id
    assert violations[0]['record_id'] == record_id


@override_settings(PERSISTENCE_MODE='orm')
def test_factory_selects_orm():
    assert isinstance(get_record_repository(), ORMRecordRepository)


@override_settings(PERSISTENCE_MODE='mongo')
def test_factory_selects_mongo():
    assert isinstance(get_record_repository(), MongoRecordRepository)


@override_settings(PERSISTENCE_MODE='hybrid')
def test_factory_selects_hybrid():
    assert isinstance(get_record_repository(), HybridRecordRepository)


def test_hybrid_reads_fall_back_and_writes_mirror_to_mongo():
    class BrokenMongo:
        def list_records(self, *args, **kwargs):
            raise RuntimeError('offline')

        def upsert_record(self, document):
            return f"mongo-{document['id']}"

    class ORM:
        def list_records(self, *args, **kwargs):
            return ([{'id': 'orm-1'}], 1)

    repository = HybridRecordRepository(orm=ORM(), mongo=BrokenMongo())
    assert repository.list_records(1) == ([{'id': 'orm-1'}], 1)
    assert repository.upsert_record({'id': '7'}) == 'mongo-7'


def test_factory_rejects_unknown_mode():
    with pytest.raises(RepositoryError):
        get_record_repository('unknown')
