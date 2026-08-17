import json

import pytest
from django.core.management import call_command
from django.db import connections

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import (
    GroupReview,
    Project,
    ProjectMember,
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_DRAFT,
    REVIEW_STATUS_SUBMITTED,
    ReviewGroup,
    SubsystemReview,
    User,
)


@pytest.fixture
def scoped_review_env(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    aliases = []
    with django_db_blocker.unblock():
        admin = User.objects.create_user('scope-admin', role='admin')
        creator = User.objects.create_user('scope-creator', role='owner')
        owner = User.objects.create_user('scope-owner', role='owner')
        outsider = User.objects.create_user('scope-outsider', role='owner')
        projects = [
            Project.objects.create(name='Scope project A'),
            Project.objects.create(name='Scope project B'),
        ]
        for project in projects:
            ReviewGroup.objects.create(
                project=project, name=f'Group {project.id}', owner=creator,
            )
            ProjectMember.objects.create(project=project, user=owner, role='owner')
            get_project_engine(project.id)
            alias = _get_project_db_alias(project.id)
            aliases.append(alias)
            call_command('migrate', database=alias, verbosity=0, interactive=False)

        group_reviews = []
        project_reviews = []
        for project, alias in zip(projects, aliases):
            group_reviews.append(
                GroupReview.objects.using(alias).create(
                    id=1,
                    project_id=project.id,
                    group_name=f'Group {project.id}',
                    title=f'Group review {project.name}',
                    leader_id=creator.id,
                    status=REVIEW_STATUS_DRAFT,
                )
            )
            project_reviews.append(
                SubsystemReview.objects.using(alias).create(
                    id=1,
                    project_id=project.id,
                    subsystem=project.name,
                    title=f'Project review {project.name}',
                    manager_id=creator.id,
                    status=REVIEW_STATUS_DRAFT,
                )
            )

    yield {
        'admin': admin,
        'creator': creator,
        'owner': owner,
        'outsider': outsider,
        'projects': projects,
        'aliases': aliases,
        'group_reviews': group_reviews,
        'project_reviews': project_reviews,
    }

    with django_db_blocker.unblock():
        for alias in aliases:
            connections[alias].close()
            connections.databases.pop(alias, None)


def post_json(client, url, payload):
    return client.post(url, json.dumps(payload), content_type='application/json')


@pytest.mark.django_db(transaction=True, databases='__all__')
@pytest.mark.parametrize('review_type', ['group', 'project'])
def test_detail_uses_explicit_project_when_local_ids_collide(
    client, scoped_review_env, review_type,
):
    env = scoped_review_env
    client.force_login(env['admin'])

    response = client.get(
        f'/api/reviews/{review_type}/1',
        {'project_id': env['projects'][1].id},
    )

    assert response.status_code == 200
    assert response.json()['project_id'] == env['projects'][1].id
    assert 'project B' in response.json()['title']


@pytest.mark.django_db(transaction=True, databases='__all__')
@pytest.mark.parametrize('review_type', ['group', 'project'])
def test_workflow_actions_cannot_cross_project_databases(
    client, scoped_review_env, review_type,
):
    env = scoped_review_env
    client.force_login(env['admin'])
    first = env[f'{review_type}_reviews'][0]
    second = env[f'{review_type}_reviews'][1]

    response = post_json(
        client,
        f'/api/reviews/{review_type}/{first.id}/submit',
        {'project_id': env['projects'][1].id},
    )

    assert response.status_code == 200
    first.refresh_from_db(using=env['aliases'][0])
    second.refresh_from_db(using=env['aliases'][1])
    assert first.status == REVIEW_STATUS_DRAFT
    assert second.status == REVIEW_STATUS_SUBMITTED


@pytest.mark.django_db(transaction=True, databases='__all__')
@pytest.mark.parametrize('review_type', ['group', 'project'])
@pytest.mark.parametrize(
    ('action', 'expected_status'),
    [('approve', 'approved'), ('reject', 'rejected')],
)
def test_review_decisions_cannot_cross_project_databases(
    client, scoped_review_env, review_type, action, expected_status,
):
    env = scoped_review_env
    client.force_login(env['admin'])
    first = env[f'{review_type}_reviews'][0]
    second = env[f'{review_type}_reviews'][1]
    first.status = REVIEW_STATUS_SUBMITTED
    second.status = REVIEW_STATUS_SUBMITTED
    first.save(using=env['aliases'][0])
    second.save(using=env['aliases'][1])

    response = post_json(
        client,
        f'/api/reviews/{review_type}/{first.id}/review',
        {
            'project_id': env['projects'][1].id,
            'action': action,
            'comment': 'scoped decision',
        },
    )

    assert response.status_code == 200
    first.refresh_from_db(using=env['aliases'][0])
    second.refresh_from_db(using=env['aliases'][1])
    assert first.status == REVIEW_STATUS_SUBMITTED
    assert second.status == expected_status
    assert second.review_comment == 'scoped decision'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_submitted_group_capabilities_and_existing_admin_row_recovery(
    client, scoped_review_env,
):
    env = scoped_review_env
    review = env['group_reviews'][0]
    review.leader_id = env['admin'].id
    review.status = REVIEW_STATUS_SUBMITTED
    review.save(using=env['aliases'][0])
    url = '/api/reviews/group'
    params = {'project_id': env['projects'][0].id}

    client.force_login(env['admin'])
    admin_item = client.get(url, params).json()['items'][0]
    assert admin_item['can_review'] is True
    assert admin_item['can_submit'] is False
    response = post_json(
        client,
        f'/api/reviews/group/{review.id}/review',
        {'project_id': review.project_id, 'action': 'approve', 'comment': 'ready'},
    )
    assert response.status_code == 200
    assert response.json()['status'] == REVIEW_STATUS_APPROVED
    assert response.json()['review_comment'] == 'ready'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_group_capability_matrix_and_duplicate_submit_error(
    client, scoped_review_env,
):
    env = scoped_review_env
    review = env['group_reviews'][0]
    client.force_login(env['creator'])
    detail_url = f'/api/reviews/group/{review.id}'
    params = {'project_id': review.project_id}

    draft = client.get(detail_url, params).json()
    assert draft | {
        'can_view': True, 'can_edit': True, 'can_submit': True, 'can_review': False,
    } == draft

    first_submit = post_json(
        client, f'{detail_url}/submit', {'project_id': review.project_id},
    )
    assert first_submit.status_code == 200
    submitted = client.get(detail_url, params).json()
    assert submitted['can_edit'] is False
    assert submitted['can_submit'] is False
    assert submitted['can_review'] is False

    duplicate = post_json(
        client, f'{detail_url}/submit', {'project_id': review.project_id},
    )
    assert duplicate.status_code == 400
    assert '不可提交' in duplicate.json()['error']

    client.force_login(env['owner'])
    assert client.get(detail_url, params).json()['can_review'] is True
    client.force_login(env['outsider'])
    assert client.get(detail_url, params).json()['can_review'] is False

    review.status = REVIEW_STATUS_APPROVED
    review.save(using=env['aliases'][0])
    client.force_login(env['admin'])
    approved = client.get(detail_url, params).json()
    assert approved['can_edit'] is False
    assert approved['can_submit'] is False
    assert approved['can_review'] is False


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_missing_project_id_fails_closed(client, scoped_review_env):
    env = scoped_review_env
    client.force_login(env['admin'])

    detail = client.get('/api/reviews/group/1')
    submit = post_json(client, '/api/reviews/project/1/submit', {})

    assert detail.status_code == 400
    assert detail.json() == {'error': 'project_id is required'}
    assert submit.status_code == 400
    assert submit.json() == {'error': 'project_id is required'}
