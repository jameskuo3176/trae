import json

import pytest
from django.core.management import call_command
from django.db import connections

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import Module, Project, QorRecord, User


def _discard_dynamic_connection(alias):
    if alias in connections.databases:
        connections[alias].close()
        connections.databases.pop(alias, None)
    if hasattr(connections._connections, alias):
        delattr(connections._connections, alias)


@pytest.fixture
def release_dir_projects(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        admin = User.objects.create_user('release-dir-admin', password='x', role='admin')
        viewer = User.objects.create_user('release-dir-viewer', password='x', role='viewer')
        projects = [
            Project.objects.create(name='Release Dir A'),
            Project.objects.create(name='Release Dir B'),
        ]
        for project in projects:
            alias = _get_project_db_alias(project.id)
            _discard_dynamic_connection(alias)
            get_project_engine(project.id)
            call_command('migrate', database=alias, verbosity=0, interactive=False)
            module = Module.objects.using(alias).create(
                id=1,
                project_id=project.id,
                name=f'module-{project.id}',
                owner_id=admin.id,
            )
            QorRecord.objects.using(alias).create(
                id=1,
                module=module,
                version=f'v{project.id}',
                full_dir=f'/upload/project-{project.id}/run',
                release_dir=f'/release/project-{project.id}/old',
                is_released=True,
            )
    yield {'admin': admin, 'viewer': viewer, 'projects': projects, 'blocker': django_db_blocker}
    with django_db_blocker.unblock():
        for project in projects:
            alias = _get_project_db_alias(project.id)
            _discard_dynamic_connection(alias)


def _update(client, project_id, release_dir):
    return client.post(
        '/api/admin/qor/1/release_dir',
        data=json.dumps({'project_id': project_id, 'release_dir': release_dir}),
        content_type='application/json',
    )


def _batch_update(client, items, release_dir):
    return client.post(
        '/api/admin/qor/batch_release_dir',
        data=json.dumps({'items': items, 'release_dir': release_dir}),
        content_type='application/json',
    )


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_release_dir_persists_in_explicit_project_and_refetches(release_dir_projects, client):
    env = release_dir_projects
    first, second = env['projects']
    with env['blocker'].unblock():
        client.force_login(env['admin'])
        response = _update(client, second.id, ' /release/project-b/new ')
        assert response.status_code == 200
        assert response.json() == {
            'ok': True,
            'id': 1,
            'project_id': second.id,
            'release_dir': '/release/project-b/new',
            'release_dir_effective': '/release/project-b/new',
        }

        first_alias = _get_project_db_alias(first.id)
        second_alias = _get_project_db_alias(second.id)
        assert QorRecord.objects.using(first_alias).get(pk=1).release_dir == (
            f'/release/project-{first.id}/old'
        )
        assert QorRecord.objects.using(second_alias).get(pk=1).release_dir == '/release/project-b/new'

        # Simulate navigation/refresh with a fresh SQLite connection.
        connections[second_alias].close()
        listed = client.get('/api/qor_data', {'project_ids': str(second.id)})
        assert listed.status_code == 200
        assert listed.json()[0]['release_dir'] == '/release/project-b/new'
        detail = client.get('/api/qor/record/1/', {'project_id': second.id})
        assert detail.status_code == 200
        assert detail.json()['record']['release_dir'] == '/release/project-b/new'
        assert detail.json()['record']['release_dir_effective'] == '/release/project-b/new'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_release_dir_clear_preserves_upload_path_and_uses_fallback(release_dir_projects, client):
    env = release_dir_projects
    project = env['projects'][0]
    with env['blocker'].unblock():
        client.force_login(env['admin'])
        response = _update(client, project.id, '   ')
        assert response.status_code == 200
        assert response.json()['release_dir'] == ''
        assert response.json()['release_dir_effective'] == f'/upload/project-{project.id}/run'

        record = QorRecord.objects.using(_get_project_db_alias(project.id)).get(pk=1)
        assert record.release_dir == ''
        assert record.full_dir == f'/upload/project-{project.id}/run'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_release_dir_rejects_unauthorized_and_invalid_requests(release_dir_projects, client):
    env = release_dir_projects
    project = env['projects'][0]
    with env['blocker'].unblock():
        client.force_login(env['viewer'])
        denied = _update(client, project.id, '/not/allowed')
        assert denied.status_code == 403

        client.force_login(env['admin'])
        missing_project = client.post(
            '/api/admin/qor/1/release_dir',
            data=json.dumps({'release_dir': '/ambiguous'}),
            content_type='application/json',
        )
        assert missing_project.status_code == 400
        too_long = _update(client, project.id, 'x' * 501)
        assert too_long.status_code == 400
        wrong_project = _update(client, 999999, '/wrong/project')
        assert wrong_project.status_code == 404

        record = QorRecord.objects.using(_get_project_db_alias(project.id)).get(pk=1)
        assert record.release_dir == f'/release/project-{project.id}/old'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_batch_release_dir_updates_composite_records_across_projects(
    release_dir_projects, client,
):
    env = release_dir_projects
    first, second = env['projects']
    items = [
        {'project_id': first.id, 'record_id': 1},
        {'project_id': second.id, 'record_id': 1},
    ]
    with env['blocker'].unblock():
        client.force_login(env['admin'])
        response = _batch_update(client, items, ' /release/shared/new ')
        assert response.status_code == 200
        assert response.json() == {
            'ok': True,
            'updated': 2,
            'skipped': 0,
            'failed': [],
            'release_dir': '/release/shared/new',
        }
        for project in (first, second):
            record = QorRecord.objects.using(
                _get_project_db_alias(project.id)
            ).get(pk=1)
            assert record.release_dir == '/release/shared/new'

        cleared = _batch_update(client, items, '   ')
        assert cleared.status_code == 200
        assert cleared.json()['updated'] == 2
        for project in (first, second):
            record = QorRecord.objects.using(
                _get_project_db_alias(project.id)
            ).get(pk=1)
            assert record.release_dir == ''


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_batch_release_dir_supports_independent_per_row_values(
    release_dir_projects, client,
):
    env = release_dir_projects
    first, second = env['projects']
    with env['blocker'].unblock():
        client.force_login(env['admin'])
        response = client.post(
            '/api/admin/qor/batch_release_dir',
            data=json.dumps({
                'items': [
                    {
                        'project_id': first.id,
                        'record_id': 1,
                        'release_dir': '/release/first/only',
                    },
                    {
                        'project_id': second.id,
                        'record_id': 1,
                        'release_dir': '/release/second/independent',
                    },
                ],
            }),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['updated'] == 2
        assert response.json()['release_dir'] is None
        assert QorRecord.objects.using(
            _get_project_db_alias(first.id)
        ).get(pk=1).release_dir == '/release/first/only'
        assert QorRecord.objects.using(
            _get_project_db_alias(second.id)
        ).get(pk=1).release_dir == '/release/second/independent'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_batch_release_dir_rejects_viewer_and_invalid_payload(
    release_dir_projects, client,
):
    env = release_dir_projects
    project = env['projects'][0]
    items = [{'project_id': project.id, 'record_id': 1}]
    with env['blocker'].unblock():
        client.force_login(env['viewer'])
        denied = _batch_update(client, items, '/not/allowed')
        assert denied.status_code == 403

        client.force_login(env['admin'])
        too_long = _batch_update(client, items, 'x' * 501)
        assert too_long.status_code == 400
        malformed = _batch_update(
            client, [{'project_id': project.id}], '/invalid',
        )
        assert malformed.status_code == 400
