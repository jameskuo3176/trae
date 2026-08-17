import json

import pytest
from django.core.management import call_command
from django.db import connections

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import (
    GroupReview,
    Project,
    ProjectMember,
    REVIEW_STATUS_SUBMITTED,
    ReviewGroup,
    User,
)


@pytest.fixture
def group_review_policy_env(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        admin = User.objects.create_user('policy-admin', role='admin')
        creator = User.objects.create_user('policy-creator', role='owner')
        project_owner = User.objects.create_user('policy-project-owner', role='owner')
        unauthorized = User.objects.create_user('policy-editor', role='owner')
        project = Project.objects.create(name='Group review policy project')
        ReviewGroup.objects.create(
            project=project, name='Group review policy group', owner=creator,
        )
        ProjectMember.objects.create(
            project=project, user=project_owner, role='owner',
        )
        ProjectMember.objects.create(
            project=project, user=unauthorized, role='editor',
        )
        get_project_engine(project.id)
        alias = _get_project_db_alias(project.id)
        call_command('migrate', database=alias, verbosity=0, interactive=False)

        def make_review(leader):
            return GroupReview.objects.using(alias).create(
                project_id=project.id,
                group_name='Group review policy group',
                title='Submitted review',
                leader_id=leader.id,
                status=REVIEW_STATUS_SUBMITTED,
            )

    yield {
        'admin': admin,
        'creator': creator,
        'project_owner': project_owner,
        'unauthorized': unauthorized,
        'project': project,
        'alias': alias,
        'make_review': make_review,
    }

    with django_db_blocker.unblock():
        connections[alias].close()
        connections.databases.pop(alias, None)


def decide(client, review, action):
    return client.post(
        f'/api/reviews/group/{review.id}/review',
        json.dumps({'project_id': review.project_id, 'action': action}),
        content_type='application/json',
    )


@pytest.mark.django_db(transaction=True, databases='__all__')
@pytest.mark.parametrize(
    ('action', 'expected_status'),
    [('approve', 'approved'), ('reject', 'rejected')],
)
def test_admin_can_review_own_group_review(
    client, group_review_policy_env, action, expected_status,
):
    env = group_review_policy_env
    review = env['make_review'](env['admin'])
    client.force_login(env['admin'])

    response = decide(client, review, action)

    assert response.status_code == 200
    assert response.json()['status'] == expected_status
    assert response.json()['reviewed_by'] == env['admin'].id


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_non_admin_creator_cannot_review_own_group_review(
    client, group_review_policy_env,
):
    env = group_review_policy_env
    review = env['make_review'](env['creator'])
    client.force_login(env['creator'])

    response = decide(client, review, 'approve')

    assert response.status_code == 400
    assert response.json() == {'error': '不能审核自己创建的 review'}


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_project_owner_can_review_another_creators_group_review(
    client, group_review_policy_env,
):
    env = group_review_policy_env
    review = env['make_review'](env['creator'])
    client.force_login(env['project_owner'])

    response = decide(client, review, 'approve')

    assert response.status_code == 200
    assert response.json()['status'] == 'approved'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_unauthorized_user_gets_json_403_for_group_review(
    client, group_review_policy_env,
):
    env = group_review_policy_env
    review = env['make_review'](env['creator'])
    client.force_login(env['unauthorized'])

    response = decide(client, review, 'reject')

    assert response.status_code == 403
    assert response['Content-Type'].startswith('application/json')
    assert response.json() == {'error': 'forbidden'}


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_group_review_list_exposes_backend_review_permission(
    client, group_review_policy_env,
):
    env = group_review_policy_env
    own_review = env['make_review'](env['creator'])

    client.force_login(env['creator'])
    creator_item = client.get(
        '/api/reviews/group', {'project_id': env['project'].id},
    ).json()['items'][0]
    assert creator_item['id'] == own_review.id
    assert creator_item['can_review'] is False

    client.force_login(env['project_owner'])
    owner_item = client.get(
        '/api/reviews/group', {'project_id': env['project'].id},
    ).json()['items'][0]
    assert owner_item['can_review'] is True

    client.force_login(env['admin'])
    admin_item = client.get(
        '/api/reviews/group', {'project_id': env['project'].id},
    ).json()['items'][0]
    assert admin_item['can_review'] is True
