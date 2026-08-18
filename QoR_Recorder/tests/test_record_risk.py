import json
from unittest.mock import Mock, patch

import pytest

from django_app.core.models import (
    GlobalModule,
    Project,
    ProjectMember,
    ProjectModule,
    RecordRiskAssessment,
    User,
)
from django_app.services.risk_rating import assess_versions, rate_version


def _record(record_id, when, groups):
    return {
        'id': str(record_id),
        'recorded_at': when,
        'extra_fields': {
            'timing_sections': {
                'final': {'corner': groups},
            },
        },
    }


def test_absolute_path_group_policy_excludes_io_groups_and_prioritizes_high():
    result = rate_version(_record('1', '2026-08-10T00:00:00Z', {
        'I2C': {'wns': -999, 'tns': -999999},
        'C2O': {'wns': -1000, 'tns': -1000000},
        'CORE': {'wns': -101, 'tns': -31000},
        'DSP': {'wns': -55, 'tns': -60000},
    }))

    assert result['rating'] == 'high'
    assert result['summary']['eligible_path_group_count'] == 2
    assert {detail['path_group'] for detail in result['details']} == {'CORE', 'DSP'}


@pytest.mark.parametrize(
    ('groups', 'expected'),
    [
        ({'CORE': {'wns': -100, 'tns': -50000}}, 'medium'),
        ({'CORE': {'wns': -50, 'tns': -30000}}, 'low'),
        ({'CORE': {'wns': -50.01, 'tns': 0}}, 'medium'),
    ],
)
def test_absolute_policy_boundaries_are_strict(groups, expected):
    assert rate_version(_record('1', '2026-08-10T00:00:00Z', groups))['rating'] == expected


def test_user_judgement_caps_better_versions_and_floors_worse_versions():
    baseline = _record('1', '2026-08-10T00:00:00Z', {
        'CORE': {'wns': -60, 'tns': -31000},
    })
    better = _record('2', '2026-08-11T00:00:00Z', {
        'CORE': {'wns': -55, 'tns': -30500},
    })
    worse = _record('3', '2026-08-12T00:00:00Z', {
        'CORE': {'wns': -80, 'tns': -35000},
    })

    capped = assess_versions([baseline, better], {'1': 'low'})
    floored = assess_versions([baseline, worse], {'1': 'high'})

    assert capped['2']['auto_rating'] == 'medium'
    assert capped['2']['rating'] == 'low'
    assert capped['2']['source'] == 'user_guardrail'
    assert floored['3']['auto_rating'] == 'medium'
    assert floored['3']['rating'] == 'high'
    assert floored['3']['trend_from_user_judgement'] == 'worse'


def test_mixed_timing_movement_keeps_automatic_rating():
    baseline = _record('1', '2026-08-10T00:00:00Z', {
        'CORE': {'wns': -80, 'tns': -35000},
    })
    mixed = _record('2', '2026-08-11T00:00:00Z', {
        'CORE': {'wns': -40, 'tns': -60000},
    })

    result = assess_versions([baseline, mixed], {'1': 'low'})
    assert result['2']['rating'] == 'high'
    assert result['2']['trend_from_user_judgement'] == 'mixed'


@pytest.mark.django_db
def test_risk_api_persists_authorized_manual_rating_and_allows_reset(client):
    user = User.objects.create_user('risk-editor', password='x', role='owner')
    project = Project.objects.create(name='Risk project')
    module = GlobalModule.objects.create(name='CPU', normalized_name='ignored')
    ProjectModule.objects.create(project=project, module=module)
    ProjectMember.objects.create(project=project, user=user, role='editor')
    client.force_login(user)
    repository = Mock()
    repository.get_record.return_value = {
        **_record('mongo-record', '2026-08-10T00:00:00Z', {
            'CORE': {'wns': -60, 'tns': -1000},
        }),
        'project_id': project.id,
        'module_id': module.id,
    }

    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        response = client.put(
            f'/api/v2/projects/{project.id}/records/mongo-record/risk',
            data=json.dumps({'rating': 'high'}),
            content_type='application/json',
        )
        assert response.status_code == 200
        assert response.json()['data']['rating'] == 'high'
        assert response.json()['data']['source'] == 'manual'
        assert RecordRiskAssessment.objects.get().manual_rating == 'high'

        reset = client.delete(
            f'/api/v2/projects/{project.id}/records/mongo-record/risk',
        )
        assert reset.status_code == 200
        assert reset.json()['data']['rating'] == 'medium'
        assert not RecordRiskAssessment.objects.exists()


@pytest.mark.django_db
def test_viewer_cannot_edit_risk(client):
    viewer = User.objects.create_user('risk-viewer', password='x', role='viewer')
    project = Project.objects.create(name='Read only risk')
    module = GlobalModule.objects.create(name='GPU', normalized_name='ignored')
    ProjectModule.objects.create(project=project, module=module)
    client.force_login(viewer)
    repository = Mock()
    repository.get_record.return_value = {
        **_record('1', '2026-08-10T00:00:00Z', {'CORE': {'wns': 0, 'tns': 0}}),
        'project_id': project.id,
        'module_id': module.id,
    }
    with patch('django_app.api_v2.get_record_repository', return_value=repository):
        response = client.put(
            f'/api/v2/projects/{project.id}/records/1/risk',
            data=json.dumps({'rating': 'high'}),
            content_type='application/json',
        )
    assert response.status_code == 403
