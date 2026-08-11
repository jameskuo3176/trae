"""Repeatable API/payload baseline: pytest -s tests/test_performance_baseline.py."""
import json
from time import perf_counter
from unittest.mock import patch

import pytest

from django_app.core.models import Project, User


class FixtureRepository:
    def __init__(self, records):
        self.records = records

    def list_records(self, project_id, *, module_id=None, version=None, offset=0, limit=50):
        rows = [
            row for row in self.records
            if row['project_id'] == project_id
            and (module_id is None or row['module_id'] == module_id)
            and (version is None or row['version'] == version)
        ]
        return rows[offset:offset + limit], len(rows)

    def get_raw_report(self, project_id, record_id):
        return {
            'record_id': record_id,
            'project_id': project_id,
            'content': 'raw timing report\n' * 1000,
        }


@pytest.mark.django_db
def test_5k_metadata_list_and_lazy_raw_baseline(client):
    admin = User.objects.create_user('benchmark-admin', password='x', role='admin')
    project = Project.objects.create(name='5k benchmark')
    client.force_login(admin)
    records = [{
        'id': str(index),
        'project_id': project.id,
        'module_id': index % 25,
        'module_name': f'module_{index % 25}',
        'version': f'regr_{index % 20:02d}',
        'full_dir': f'/fixtures/regr_{index % 20:02d}/main/run_{index}',
        'wns': -(index % 100) / 100,
    } for index in range(5000)]
    repository = FixtureRepository(records)

    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        started = perf_counter()
        response = client.get('/api/v2/records', {
            'project_id': project.id,
            'page': 1,
            'page_size': 200,
        })
        list_ms = (perf_counter() - started) * 1000
        body = response.json()
        encoded = json.dumps(body, separators=(',', ':')).encode()

        assert response.status_code == 200
        assert body['pagination']['total'] == 5000
        assert len(body['data']) == 200
        assert all('raw_dc_report' not in row and 'content' not in row for row in body['data'])

        started = perf_counter()
        raw = client.get(f'/api/v2/projects/{project.id}/records/0/raw')
        raw_ms = (perf_counter() - started) * 1000
        assert raw.status_code == 200
        assert len(raw.json()['data']['content']) == 18000

    print(
        f'PERF_BASELINE records=5000 page=200 list_ms={list_ms:.2f} '
        f'payload_bytes={len(encoded)} raw_ms={raw_ms:.2f} raw_bytes=18000'
    )
