import json
from unittest.mock import Mock, patch

import pytest
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client, override_settings

from django_app.core.models import GlobalModule, Project, ProjectModule, User


@pytest.mark.django_db
@override_settings(PERSISTENCE_MODE='orm')
def test_health_reports_sql_and_disabled_mongo(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['checks']['mongo'] == {'enabled': False, 'ready': True}
    assert client.get('/health/ready').json()['status'] == 'ready'
    assert client.get('/health/live').json() == {'ok': True, 'status': 'alive'}


@pytest.mark.django_db
def test_v2_modules_require_auth_and_explicit_project(client):
    assert client.get('/api/v2/modules').status_code == 401
    admin = User.objects.create_user('admin-test', password='x', role='admin')
    client.force_login(admin)
    project = Project.objects.create(name='P')
    module = GlobalModule.objects.create(name='CPU', normalized_name='ignored')
    ProjectModule.objects.create(project=project, module=module)
    response = client.get('/api/v2/modules', {'project_id': project.id})
    assert response.status_code == 200
    assert response.json()['data'][0]['id'] == module.id


@pytest.mark.django_db
def test_unsafe_legacy_endpoint_uses_x_csrftoken():
    admin = User.objects.create_user('csrf-admin', password='x', role='admin')
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin)
    payload = json.dumps({'name': 'CSRF project'})
    assert client.post('/api/admin/projects', payload, content_type='application/json').status_code == 403
    token = _get_new_csrf_string()
    client.cookies['csrftoken'] = token
    response = client.post(
        '/api/admin/projects', payload, content_type='application/json',
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_v2_records_are_paginated_without_eager_raw_payload(client):
    admin = User.objects.create_user('page-admin', password='x', role='admin')
    project = Project.objects.create(name='Paged')
    client.force_login(admin)
    repository = Mock()
    repository.list_records.return_value = (
        [{'id': '2', 'project_id': project.id, 'version': 'regr_b'}],
        401,
    )
    repository.get_raw_report.return_value = {
        'record_id': '2', 'project_id': project.id, 'content': 'raw report',
    }
    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        response = client.get('/api/v2/records', {
            'project_id': project.id, 'page': 3, 'page_size': 999,
        })
        assert response.status_code == 200
        body = response.json()
        assert body['pagination'] == {
            'page': 3, 'page_size': 200, 'total': 401, 'pages': 3,
        }
        assert 'raw_dc_report' not in body['data'][0]
        repository.list_records.assert_called_once_with(
            project.id, module_id=None, version=None, offset=400, limit=200,
        )

        raw = client.get(f'/api/v2/projects/{project.id}/records/2/raw')
        assert raw.json()['data']['content'] == 'raw report'
        repository.get_raw_report.assert_called_once_with(project.id, '2')
