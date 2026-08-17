import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import (
    GlobalModule,
    LegacyModuleMapping,
    Module,
    Project,
    ProjectModule,
    QorRecord,
    User,
)


@pytest.fixture
def record_projects(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        admin = User.objects.create_user('records-admin', password='x', role='admin')
        owner = User.objects.create_user('module-owner', password='x', role='owner')
        collaborator = User.objects.create_user('module-collab', password='x', role='owner')
        outsider = User.objects.create_user('module-outsider', password='x', role='owner')
        viewer = User.objects.create_user('records-viewer', password='x', role='viewer')
        projects = [Project.objects.create(name='Alpha'), Project.objects.create(name='Beta')]
        now = timezone.now()
        for project in projects:
            alias = _get_project_db_alias(project.id)
            if alias in connections.databases:
                connections[alias].close()
                connections.databases.pop(alias, None)
            get_project_engine(project.id)
            call_command('migrate', database=alias, verbosity=0, interactive=False)
            module = Module.objects.using(alias).create(
                id=1,
                project_id=project.id,
                name=f'core-{project.name.lower()}',
                owner_id=owner.id,
                collaborators=json.dumps([collaborator.id]),
            )
            global_module = GlobalModule.objects.create(
                name=module.name,
                normalized_name=f'core-{project.name.lower()}',
            )
            ProjectModule.objects.create(
                project=project,
                module=global_module,
                owner_id=owner.id,
            )
            LegacyModuleMapping.objects.create(
                project=project,
                legacy_module_id=module.id,
                module=global_module,
                legacy_name=module.name,
            )
            QorRecord.objects.using(alias).create(
                id=1,
                module=module,
                owner_id=outsider.id,
                version=project.name,
                recorded_at=now - timedelta(minutes=5),
                released_at=now - timedelta(days=1),
                is_released=True,
            )
        alpha_alias = _get_project_db_alias(projects[0].id)
        alpha_module = Module.objects.using(alpha_alias).get(pk=1)
        QorRecord.objects.using(alpha_alias).create(
            id=2,
            module=alpha_module,
            owner_id=owner.id,
            version='new-unreleased',
            recorded_at=now,
        )
        for record_id in range(10, 14):
            QorRecord.objects.using(alpha_alias).create(
                id=record_id,
                module=alpha_module,
                owner_id=owner.id,
                version=f'delete-{record_id}',
                recorded_at=now - timedelta(days=2),
            )
    yield {
        'admin': admin,
        'owner': owner,
        'collaborator': collaborator,
        'outsider': outsider,
        'viewer': viewer,
        'projects': projects,
        'blocker': django_db_blocker,
    }
    with django_db_blocker.unblock():
        for project in projects:
            alias = _get_project_db_alias(project.id)
            connections[alias].close()
            connections.databases.pop(alias, None)


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_cross_project_enrichment_release_sort_and_pagination(record_projects, client):
    env = record_projects
    with env['blocker'].unblock():
        client.force_login(env['owner'])
        response = client.get('/api/qor_data', {
            'project_ids': ','.join(str(project.id) for project in env['projects']),
            'page': 1,
            'page_size': 2,
        })
        assert response.status_code == 200
        body = response.json()
        assert body['pagination']['total'] == 7
        assert body['pagination']['page_size'] == 2
        assert body['records'][0]['version'] == 'new-unreleased'
        for row in body['records']:
            assert row['project_name']
            assert row['module_name']
            assert 'uploader_username' in row
            assert 'uploader_display_name' in row
            assert row['recorded_at'].count(':') >= 2
            assert row['recorded_at_display'].split('+', 1)[0].count(':') == 1
            assert row['can_manage'] is True
            assert row['global_module_id']
            assert row['review_week_start']
            assert row['can_select_review_star'] is True


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_admin_owner_viewer_dashboard_read_the_same_record_scope(record_projects, client):
    env = record_projects
    project = env['projects'][0]
    params = {'project_ids': str(project.id), 'page': 1, 'page_size': 50}
    with env['blocker'].unblock():
        client.force_login(env['admin'])
        admin_projects = client.get('/api/projects').json()
        admin_rows = client.get('/api/qor_data', params).json()['records']
        admin_module_rows = client.get(
            f'/api/modules/{project.id}/1/records'
        ).json()

        client.force_login(env['owner'])
        owner_projects = client.get('/api/projects').json()
        owner_rows = client.get('/api/qor_data', params).json()['records']
        owner_module_rows = client.get(
            f'/api/modules/{project.id}/1/records'
        ).json()

        client.force_login(env['viewer'])
        viewer_projects = client.get('/api/projects').json()
        viewer_rows = client.get('/api/qor_data', params).json()['records']
        viewer_module_rows = client.get(
            f'/api/modules/{project.id}/1/records'
        ).json()
        unreleased_detail = client.get(
            '/api/qor/record/2/', {'project_id': project.id}
        )
        config_list = client.get('/api/dashboard/list')
        config_write = client.post(
            '/api/dashboard/save',
            json.dumps({'name': 'viewer write', 'config': {}}),
            content_type='application/json',
        )
        config_get_write = client.get('/api/dashboard/save')

    assert admin_projects == owner_projects == viewer_projects
    assert [row['id'] for row in admin_rows] == [
        row['id'] for row in owner_rows
    ] == [row['id'] for row in viewer_rows]
    assert any(row['id'] == 2 and not row['is_released'] for row in viewer_rows)
    assert [row['id'] for row in admin_module_rows] == [
        row['id'] for row in owner_module_rows
    ] == [row['id'] for row in viewer_module_rows]
    assert unreleased_detail.status_code == 200
    assert unreleased_detail.json()['record']['id'] == 2
    assert all(not row['can_manage'] for row in viewer_rows)
    assert config_list.status_code == 200
    assert config_write.status_code == 403
    assert config_get_write.status_code == 405


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_record_owner_filter_matches_uploader(record_projects, client):
    env = record_projects
    project = env['projects'][0]
    with env['blocker'].unblock():
        client.force_login(env['owner'])
        owners = client.get('/api/admin/records/owners', {
            'project_ids': str(project.id),
        })
        assert owners.status_code == 200
        owner_rows = owners.json()
        assert {row['username'] for row in owner_rows} == {
            'module-owner',
            'module-outsider',
        }

        filtered = client.get('/api/qor_data', {
            'project_ids': str(project.id),
            'owner_id': env['owner'].id,
            'page': 1,
            'page_size': 50,
        }).json()['records']
        assert filtered
        assert all(row['uploader_username'] == 'module-owner' for row in filtered)
        assert all(row['owner_id'] == env['owner'].id for row in filtered)

        outsider_only = client.get('/api/qor_data', {
            'project_ids': str(project.id),
            'owner_id': env['outsider'].id,
            'page': 1,
            'page_size': 50,
        }).json()['records']
        assert [row['id'] for row in outsider_only] == [1]
        assert outsider_only[0]['uploader_username'] == 'module-outsider'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_record_management_star_round_trip(record_projects, client):
    env = record_projects
    project = env['projects'][0]
    with env['blocker'].unblock():
        client.force_login(env['owner'])
        initial = client.get('/api/qor_data', {
            'project_ids': str(project.id),
            'page': 1,
            'page_size': 20,
        }).json()['records']
        target = next(row for row in initial if row['id'] == 2)
        assert target['review_star'] is False

        response = client.post(
            '/api/reviews/weekly/star',
            json.dumps({
                'project_id': project.id,
                'module_id': target['global_module_id'],
                'record_id': str(target['id']),
                'week_start': target['review_week_start'],
            }),
            content_type='application/json',
        )
        assert response.status_code == 200

        refreshed = client.get('/api/qor_data', {
            'project_ids': str(project.id),
            'page': 1,
            'page_size': 20,
        }).json()['records']
        selected = [row for row in refreshed if row['review_star']]
        assert [(row['id'], row['version']) for row in selected] == [(2, 'new-unreleased')]

        response = client.delete(
            '/api/reviews/weekly/star',
            json.dumps({
                'project_id': project.id,
                'module_id': target['global_module_id'],
                'record_id': str(target['id']),
                'week_start': target['review_week_start'],
            }),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['cleared'] is True
        after_clear = client.get('/api/qor_data', {
            'project_ids': str(project.id),
            'page': 1,
            'page_size': 20,
        }).json()['records']
        assert not any(row['review_star'] for row in after_clear)


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_delete_matches_release_module_permissions(record_projects, client):
    env = record_projects
    project = env['projects'][0]
    with env['blocker'].unblock():
        for user, record_id, expected in (
            (env['owner'], 10, 200),
            (env['collaborator'], 11, 200),
            (env['outsider'], 12, 403),
            (env['viewer'], 13, 403),
        ):
            client.force_login(user)
            response = client.delete(
                f'/api/admin/records/{record_id}?project_id={project.id}'
            )
            assert response.status_code == expected
        alias = _get_project_db_alias(project.id)
        assert not QorRecord.objects.using(alias).filter(pk__in=(10, 11)).exists()
        assert QorRecord.objects.using(alias).filter(pk__in=(12, 13)).count() == 2


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_release_permissions_and_composite_batch_isolation(record_projects, client):
    env = record_projects
    alpha, beta = env['projects']
    with env['blocker'].unblock():
        for user, expected in (
            (env['owner'], 200),
            (env['collaborator'], 200),
            (env['outsider'], 403),
            (env['viewer'], 403),
        ):
            client.force_login(user)
            response = client.post(
                '/api/admin/qor/2/release',
                json.dumps({'project_id': alpha.id}),
                content_type='application/json',
            )
            assert response.status_code == expected

        client.force_login(env['admin'])
        ambiguous = client.post(
            '/api/admin/qor/batch_release',
            json.dumps({'record_ids': [1], 'released': False}),
            content_type='application/json',
        )
        assert ambiguous.status_code == 409

        exact = client.post(
            '/api/admin/qor/batch_release',
            json.dumps({
                'items': [{'project_id': beta.id, 'record_id': 1}],
                'released': False,
            }),
            content_type='application/json',
        )
        assert exact.status_code == 200
        assert exact.json()['updated'] == 1
        assert QorRecord.objects.using(_get_project_db_alias(alpha.id)).get(pk=1).is_released
        assert not QorRecord.objects.using(_get_project_db_alias(beta.id)).get(pk=1).is_released
