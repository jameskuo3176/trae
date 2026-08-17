import json

import pytest
from django.core.management import call_command
from django.db import connections
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import Project, ReviewGroup, User


@pytest.fixture
def review_csrf_env(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        admin = User.objects.create_user(
            'review-csrf-admin', password='secret', role='admin'
        )
        outsider = User.objects.create_user(
            'review-csrf-outsider', password='secret', role='owner'
        )
        project = Project.objects.create(name='Review CSRF project')
        ReviewGroup.objects.create(
            project=project, name='Review CSRF group', owner=admin
        )
        get_project_engine(project.id)
        alias = _get_project_db_alias(project.id)
        call_command('migrate', database=alias, verbosity=0, interactive=False)

    yield {
        'admin': admin,
        'outsider': outsider,
        'project': project,
        'alias': alias,
    }

    with django_db_blocker.unblock():
        connections[alias].close()
        connections.databases.pop(alias, None)


def _post(client, path, payload, token=None):
    kwargs = {'HTTP_X_CSRFTOKEN': token} if token else {}
    return client.post(
        path, json.dumps(payload), content_type='application/json', **kwargs
    )


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_admin_creates_all_review_levels_with_login_csrf_cookie(review_csrf_env):
    client = Client(enforce_csrf_checks=True)
    login_response = _post(
        client,
        '/api/v1/auth/login',
        {'username': 'review-csrf-admin', 'password': 'secret'},
    )
    assert login_response.status_code == 200
    assert 'csrftoken' in login_response.cookies
    assert login_response.cookies['csrftoken']['httponly'] == ''
    token = client.cookies['csrftoken'].value
    project = review_csrf_env['project']

    snapshot = _post(
        client,
        '/api/reviews/snapshots',
        {'project_id': project.id, 'description': 'frozen'},
        token,
    )
    assert snapshot.status_code == 201, snapshot.content
    week_start = snapshot.json()['week_start']
    group = _post(
        client,
        '/api/reviews/group',
        {
            'project_id': project.id,
            'group_name': 'Review CSRF group',
            'week_start': week_start,
        },
        token,
    )
    project_review = _post(
        client,
        '/api/reviews/project',
        {'project_id': project.id, 'week_start': week_start},
        token,
    )

    assert group.status_code == 201, group.content
    assert project_review.status_code == 201, project_review.content


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_review_writes_reject_missing_and_invalid_csrf(review_csrf_env):
    client = Client(enforce_csrf_checks=True)
    client.force_login(review_csrf_env['admin'])
    payload = {'project_id': review_csrf_env['project'].id}

    assert _post(client, '/api/reviews/project', payload).status_code == 403
    client.cookies['csrftoken'] = _get_new_csrf_string()
    assert _post(
        client,
        '/api/reviews/project',
        payload,
        _get_new_csrf_string(),
    ).status_code == 403


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_non_owner_gets_json_403_after_passing_csrf(review_csrf_env):
    client = Client(enforce_csrf_checks=True)
    client.force_login(review_csrf_env['outsider'])
    token = _get_new_csrf_string()
    client.cookies['csrftoken'] = token

    response = _post(
        client,
        '/api/reviews/project',
        {'project_id': review_csrf_env['project'].id},
        token,
    )

    assert response.status_code == 403
    assert response['Content-Type'].startswith('application/json')
    assert response.json() == {'error': 'forbidden'}


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_me_restores_csrf_cookie_for_existing_session(review_csrf_env):
    client = Client(enforce_csrf_checks=True)
    client.force_login(review_csrf_env['admin'])
    client.cookies.pop('csrftoken', None)

    response = client.get('/api/v1/auth/me')

    assert response.status_code == 200
    assert response.json()['must_change_password'] is False
    assert 'csrftoken' in response.cookies
    token = client.cookies['csrftoken'].value
    snapshot = _post(
        client,
        '/api/reviews/snapshots',
        {'project_id': review_csrf_env['project'].id},
        token,
    )
    assert snapshot.status_code == 201, snapshot.content
    created = _post(
        client,
        '/api/reviews/group',
        {
            'project_id': review_csrf_env['project'].id,
            'group_name': 'Review CSRF group',
            'week_start': snapshot.json()['week_start'],
        },
        token,
    )
    assert created.status_code == 201, created.content
    logged_out = _post(client, '/api/v1/auth/logout', {}, token)
    assert logged_out.status_code == 200
    assert client.get('/api/v1/auth/me').status_code == 401
