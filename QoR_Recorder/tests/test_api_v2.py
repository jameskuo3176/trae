import json
from unittest.mock import Mock, patch

import pytest
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client, override_settings

from django_app.core.models import (
    GlobalModule, LegacyModuleMapping, Project, ProjectModule, User,
)


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


@pytest.mark.django_db
def test_v2_versions_include_quarter_week_path_versions(client):
    admin = User.objects.create_user('versions-admin', password='x', role='admin')
    project = Project.objects.create(name='Versioned')
    client.force_login(admin)
    repository = Mock()
    repository.list_records.return_value = ([
        {
            'id': '1',
            'project_id': project.id,
            'full_dir': '2026Q3_w3/variant_c/cpu_cfg1',
        },
        {
            'id': '2',
            'project_id': project.id,
            'full_dir': '/workspace/regr_20260814/main/cpu_cfg2',
        },
    ], 2)

    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        response = client.get('/api/v2/versions', {'project_ids': str(project.id)})

    assert response.status_code == 200
    assert response.json()['data'] == ['2026Q3_w3', 'regr_20260814']


@pytest.mark.django_db
def test_v2_all_project_records_keep_global_module_identity(client):
    admin = User.objects.create_user('global-admin', password='x', role='admin')
    first = Project.objects.create(name='First')
    second = Project.objects.create(name='Second')
    module = GlobalModule.objects.create(name='Shared CPU', normalized_name='ignored')
    ProjectModule.objects.create(project=first, module=module)
    ProjectModule.objects.create(project=second, module=module)
    client.force_login(admin)
    repository = Mock()
    repository.list_records.side_effect = [
        ([{
            'id': '1', 'project_id': first.id, 'module_id': module.id,
            'module_name': 'Shared CPU', 'recorded_at': '2026-08-12T08:00:00+00:00',
        }], 1),
        ([{
            'id': '1', 'project_id': second.id, 'module_id': module.id,
            'module_name': 'Shared CPU', 'recorded_at': '2026-08-12T09:00:00+00:00',
        }], 1),
    ]
    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        response = client.get('/api/v2/records', {
            'module_id': module.id, 'page': 1, 'page_size': 50,
        })
    assert response.status_code == 200
    body = response.json()
    assert [(row['project_id'], row['id']) for row in body['data']] == [
        (second.id, '1'), (first.id, '1'),
    ]
    assert all(row['module_id'] == module.id for row in body['data'])
    assert repository.list_records.call_count == 2
    for call in repository.list_records.call_args_list:
        assert call.kwargs['module_id'] == module.id


@pytest.mark.django_db
def test_v2_records_hydrate_mapped_identity_and_report_only_unresolved_rows(client):
    owner = User.objects.create_user('identity-owner', password='x', role='owner')
    project = Project.objects.create(name='Identity project')
    module = GlobalModule.objects.create(name='Mapped CPU', normalized_name='ignored')
    unlinked_module = GlobalModule.objects.create(name='Unlinked CPU', normalized_name='ignored')
    ProjectModule.objects.create(project=project, module=module, owner_id=owner.id)
    LegacyModuleMapping.objects.create(
        project=project,
        legacy_module_id=41,
        module=module,
        legacy_name='Mapped CPU',
    )
    LegacyModuleMapping.objects.create(
        project=project,
        legacy_module_id=43,
        module=unlinked_module,
        legacy_name='Unlinked CPU',
    )
    client.force_login(owner)
    repository = Mock()
    repository.list_records.return_value = ([
        {
            'id': 'mapped',
            'project_id': project.id,
            'legacy_module_id': 41,
            'module_id': 999999,
            'module_name': 'Mapped CPU',
        },
        {
            'id': 'unmapped',
            'project_id': project.id,
            'legacy_module_id': 42,
            'module_id': None,
            'module_name': 'Missing CPU',
        },
        {
            'id': 'unlinked',
            'project_id': project.id,
            'legacy_module_id': 43,
            'module_id': unlinked_module.id,
            'module_name': 'Unlinked CPU',
        },
    ], 3)

    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        response = client.get('/api/v2/records', {'project_id': project.id})

    assert response.status_code == 200
    body = response.json()
    assert body['data'][0]['module_id'] == module.id
    assert 'module_mapping_error' not in body['data'][0]
    assert body['data'][1]['module_id'] is None
    assert body['data'][2]['module_id'] is None
    assert body['meta']['unmapped_modules'] == [
        {
            'project_id': project.id,
            'record_id': 'unmapped',
            'legacy_module_id': 42,
            'module_name': 'Missing CPU',
        },
        {
            'project_id': project.id,
            'record_id': 'unlinked',
            'legacy_module_id': 43,
            'module_name': 'Unlinked CPU',
        },
    ]


@pytest.mark.django_db
def test_v2_admin_owner_viewer_read_the_same_released_and_unreleased_records(client):
    admin = User.objects.create_user('history-admin', password='x', role='admin')
    owner = User.objects.create_user('history-owner', password='x', role='owner')
    viewer = User.objects.create_user('history-viewer', password='x', role='viewer')
    project = Project.objects.create(name='Historical', status='archived')
    module = GlobalModule.objects.create(name='CPU history', normalized_name='ignored')
    ProjectModule.objects.create(project=project, module=module)
    released = {
        'id': 'released',
        'project_id': project.id,
        'module_id': module.id,
        'version': 'published',
        'full_dir': '/workspace/regr_published/main/cpu',
        'is_released': True,
    }
    unreleased = {
        'id': 'draft',
        'project_id': project.id,
        'module_id': module.id,
        'version': 'private',
        'full_dir': '/workspace/regr_private/main/cpu',
        'is_released': False,
    }
    repository = Mock()

    repository.list_records.return_value = ([released, unreleased], 2)
    responses = {}
    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        for user in (admin, owner, viewer):
            client.force_login(user)
            responses[user.role] = {
                'records': client.get(
                    '/api/v2/records', {'project_id': project.id}
                ).json(),
                'versions': client.get(
                    '/api/v2/versions', {'project_id': project.id}
                ).json(),
            }

    assert responses['admin'] == responses['owner'] == responses['viewer']
    assert [row['id'] for row in responses['viewer']['records']['data']] == [
        'released', 'draft'
    ]
    assert responses['viewer']['versions'] == {
        'ok': True,
        'data': ['regr_private', 'regr_published'],
        'meta': {'invalid_path_count': 0, 'invalid_paths': []},
    }
    assert all('release_only' not in call.kwargs for call in repository.list_records.call_args_list)


@pytest.mark.django_db
def test_v2_admin_owner_viewer_read_same_unreleased_children_but_viewer_cannot_write(client):
    admin = User.objects.create_user('readonly-admin', password='x', role='admin')
    owner = User.objects.create_user('readonly-owner', password='x', role='owner')
    viewer = User.objects.create_user('readonly-viewer', password='x', role='viewer')
    project = Project.objects.create(name='Read only')
    repository = Mock()
    repository.get_record.return_value = {
        'id': 'draft',
        'project_id': project.id,
        'is_released': False,
    }
    repository.get_raw_report.return_value = {
        'record_id': 'draft',
        'project_id': project.id,
        'content': 'private draft report',
    }
    repository.list_notes.return_value = [{'record_id': 'draft', 'text': 'draft note'}]
    repository.list_violations.return_value = [{'record_id': 'draft', 'slack': -0.1}]

    responses = {}
    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        for user in (admin, owner, viewer):
            client.force_login(user)
            responses[user.role] = {
                'detail': client.get(
                    f'/api/v2/projects/{project.id}/records/draft'
                ).json(),
                'raw': client.get(
                    f'/api/v2/projects/{project.id}/records/draft/raw'
                ).json(),
                'notes': client.get(
                    f'/api/v2/projects/{project.id}/records/draft/notes'
                ).json(),
                'violations': client.get(
                    f'/api/v2/projects/{project.id}/records/draft/violations'
                ).json(),
            }
        client.force_login(viewer)
        write = client.post(
            f'/api/v2/projects/{project.id}/records/draft/annotation',
            {'text': 'not allowed'},
        )

    assert responses['admin'] == responses['owner'] == responses['viewer']
    assert responses['viewer']['detail']['data']['is_released'] is False
    assert responses['viewer']['raw']['data']['content'] == 'private draft report'
    assert responses['viewer']['notes']['data'] == [
        {'record_id': 'draft', 'text': 'draft note'}
    ]
    assert responses['viewer']['violations']['data'] == [
        {'record_id': 'draft', 'slack': -0.1}
    ]
    assert write.status_code == 403
    assert repository.get_raw_report.call_count == 3


@pytest.mark.django_db
@pytest.mark.parametrize('role', ['admin', 'owner', 'viewer'])
def test_v2_hidden_projects_are_not_dashboard_readable(client, role):
    user = User.objects.create_user(f'hidden-{role}', password='x', role=role)
    project = Project.objects.create(name='Offline', status='hidden')
    client.force_login(user)
    repository = Mock()

    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        response = client.get('/api/v2/records', {'project_id': project.id})
        detail = client.get(f'/api/v2/projects/{project.id}/records/1')

    assert response.status_code == 400
    assert detail.status_code == 403
    repository.list_records.assert_not_called()


@pytest.mark.django_db
def test_legacy_dashboard_does_not_fall_back_to_hidden_projects(client):
    viewer = User.objects.create_user('legacy-hidden-viewer', password='x', role='viewer')
    project = Project.objects.create(name='Legacy offline', status='hidden')
    client.force_login(viewer)

    with patch('django_app.api.views.query_records_by_projects', return_value=[]) as query:
        records = client.get('/api/qor_data', {'project_ids': str(project.id)})
        modules = client.get(f'/api/modules/{project.id}/')

    assert records.status_code == 200
    assert records.json() == []
    assert query.call_args.kwargs['proj_id_list'] == []
    assert modules.status_code == 404
