import json
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from django_app.core.models import Project, User


@pytest.fixture
def lifecycle_env(db):
    admin = User.objects.create_user('lifecycle-admin', password='x', role='admin')
    owner = User.objects.create_user('lifecycle-owner', password='x', role='owner')
    project = Project.objects.create(name='LifecycleProj', description='lifecycle')
    return {'admin': admin, 'owner': owner, 'project': project}


@pytest.mark.django_db
def test_hide_restore_and_hard_delete_project(lifecycle_env, client):
    env = lifecycle_env
    project = env['project']
    client.force_login(env['admin'])

    hidden = client.delete(f'/api/admin/projects/{project.id}')
    assert hidden.status_code == 200
    project.refresh_from_db()
    assert project.status == 'hidden'

    listed = client.get('/api/admin/projects/hidden')
    assert listed.status_code == 200
    assert any(row['id'] == project.id for row in listed.json())

    visible = client.get('/api/projects').json()
    assert all(row['id'] != project.id for row in visible)

    restored = client.post(f'/api/admin/projects/{project.id}/restore')
    assert restored.status_code == 200
    project.refresh_from_db()
    assert project.status == 'active'
    assert project.hidden_at is None
    assert project.lock_reason == ''

    client.delete(f'/api/admin/projects/{project.id}')
    hard = client.delete(
        f'/api/admin/projects/{project.id}/hard_delete?confirm=true',
    )
    assert hard.status_code == 200
    assert not Project.objects.filter(pk=project.id).exists()


@pytest.mark.django_db
def test_lock_blocks_upload_but_keeps_project_visible(lifecycle_env, client):
    env = lifecycle_env
    project = env['project']
    client.force_login(env['admin'])

    locked = client.post(
        f'/api/admin/projects/{project.id}/lock',
        json.dumps({'reason': 'freeze for review'}),
        content_type='application/json',
    )
    assert locked.status_code == 200
    body = locked.json()
    assert body['status'] == 'locked'
    assert body['is_writable'] is False
    assert body['lock_reason'] == 'freeze for review'

    projects = client.get('/api/projects').json()
    assert any(row['id'] == project.id and row['status'] == 'locked' for row in projects)

    client.force_login(env['owner'])
    upload = client.post(
        '/api/admin/upload',
        {
            'project_id': str(project.id),
            'version': 'v1',
            'files': SimpleUploadedFile(
                'demo.csv',
                b'module_name,version,area_total\nm1,v1,1.0\n',
                content_type='text/csv',
            ),
        },
    )
    assert upload.status_code == 403
    assert '不可写' in upload.json()['error']

    client.force_login(env['admin'])
    unlocked = client.post(f'/api/admin/projects/{project.id}/unlock')
    assert unlocked.status_code == 200
    assert unlocked.json()['status'] == 'active'
    assert unlocked.json()['is_writable'] is True


@pytest.mark.django_db
def test_legacy_admin_sends_django_csrf_header_for_lock_and_restore(lifecycle_env):
    env = lifecycle_env
    project = env['project']
    client = Client(enforce_csrf_checks=True)
    client.force_login(env['admin'])

    page = client.get('/admin/')
    assert page.status_code == 200
    html = page.content.decode()
    assert "const CSRF_HEADER = 'X-CSRFToken'" in html
    token = re.search(
        r'<meta name="csrf-token" content="([^"]+)">', html,
    ).group(1)

    locked = client.post(
        f'/api/admin/projects/{project.id}/lock',
        json.dumps({'reason': 'csrf-check'}),
        content_type='application/json',
        HTTP_X_CSRFTOKEN=token,
    )
    assert locked.status_code == 200

    hidden = client.delete(
        f'/api/admin/projects/{project.id}',
        HTTP_X_CSRFTOKEN=token,
    )
    assert hidden.status_code == 200
    restored = client.post(
        f'/api/admin/projects/{project.id}/restore',
        HTTP_X_CSRFTOKEN=token,
    )
    assert restored.status_code == 200
