from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
import yaml
from django.core.management import call_command

from django_app.core.models import (
    GlobalModule,
    Project,
    ProjectMember,
    ProjectModule,
    ReviewGroup,
    ReviewGroupModule,
    ReviewHierarchySyncState,
    User,
)
from django_app.services.review_hierarchy import (
    build_sync_plan,
    get_effective_risk_thresholds,
    hierarchy_status,
    load_hierarchy,
    sync_hierarchy,
    validate_hierarchy,
)
from django_app.services.risk_rating import rate_record, shanghai_week_window
from django_app.services.weekly_review import _record_payload


def test_shanghai_week_starts_on_monday():
    start, end = shanghai_week_window(
        datetime(2026, 8, 12, 11, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
    )
    assert start.isoformat() == '2026-08-10T00:00:00+08:00'
    assert (end - start).days == 7


def test_risk_rating_uses_worst_relative_regression():
    result = rate_record(
        {'tns_setup': -12, 'area_total': 108, 'utilization': 71},
        {'tns_setup': -10, 'area_total': 100, 'utilization': 70},
    )
    assert result['rating'] == 'medium'
    assert {item['metric'] for item in result['details']} == {
        'tns_setup', 'area_total', 'utilization',
    }


def test_review_payload_exposes_all_timing_analysis_types():
    class Record:
        raw_dc_report = None

        @staticmethod
        def to_dict():
            return {
                'raw_dc_report': {'large': 'payload'},
                'extra_fields': {
                    'timing_sections': {
                        'default': {'corner': {'FUNCCLK': {'wns': -10}}},
                        'final': {'corner': {'FUNCCLK': {'wns': -5}}},
                    },
                },
            }

    payload = _record_payload(Record())

    assert set(payload['timing_sections']) == {'default', 'final'}
    assert 'raw_dc_report' not in payload


@pytest.mark.django_db
def test_yaml_hierarchy_syncs_owners_and_groups(tmp_path):
    project_owner = User.objects.create_user(username='project-owner')
    group_owner = User.objects.create_user(username='group-owner')
    release_owner = User.objects.create_user(username='release-owner')
    project = Project.objects.create(name='projectA')
    module = GlobalModule.objects.create(name='moduleA', normalized_name='ignored')
    project_module = ProjectModule.objects.create(project=project, module=module)
    config = tmp_path / 'hierarchy.yaml'
    config.write_text(
        """
version: "1"
risk_thresholds: {}
projects:
  projectA:
    owner: project-owner
    groups:
      groupA:
        owner: group-owner
        modules:
          moduleA:
            release_owner: release-owner
""",
        encoding='utf-8',
    )
    data, version = load_hierarchy(config)
    errors, _ = validate_hierarchy(data)
    assert errors == []
    plan = sync_hierarchy(data, version, config)
    assert plan['desired'] == {'projects': 1, 'groups': 1, 'modules': 1}
    assert plan['total_changes'] == 4
    assert ProjectMember.objects.get(
        project=project, user=project_owner,
    ).role == 'owner'
    project_module.refresh_from_db()
    assert project_module.owner_id == release_owner.id
    group = ReviewGroup.objects.get(project=project, name='groupA')
    assert group.owner_id == group_owner.id
    assert group.module_links.get().project_module_id == project_module.id


def _config(project='projectA', owner='project-owner', group='groupA',
            group_owner='group-owner', module='moduleA', release_owner='release-owner',
            **extra):
    data = {
        'version': '1',
        'risk_thresholds': {},
        'projects': {
            project: {
                'owner': owner,
                'groups': {
                    group: {
                        'owner': group_owner,
                        'modules': {
                            module: {'release_owner': release_owner},
                        },
                    },
                },
            },
        },
    }
    data.update(extra)
    return data


@pytest.fixture
def hierarchy_env(db):
    users = {
        name: User.objects.create_user(username=name)
        for name in (
            'project-owner', 'old-owner', 'group-owner', 'old-group-owner',
            'release-owner', 'old-release-owner', 'collaborator',
        )
    }
    project = Project.objects.create(name='projectA')
    other_project = Project.objects.create(name='unrelated')
    module = GlobalModule.objects.create(name='moduleA', normalized_name='ignored')
    stale_module = GlobalModule.objects.create(name='staleModule', normalized_name='ignored')
    other_module = GlobalModule.objects.create(name='otherModule', normalized_name='ignored')
    project_module = ProjectModule.objects.create(
        project=project,
        module=module,
        owner_id=users['old-release-owner'].id,
        collaborators='[7, 8]',
    )
    stale_project_module = ProjectModule.objects.create(
        project=project, module=stale_module,
    )
    other_project_module = ProjectModule.objects.create(
        project=other_project, module=other_module,
    )
    ProjectMember.objects.create(
        project=project, user=users['old-owner'], role='owner',
    )
    ProjectMember.objects.create(
        project=project, user=users['collaborator'], role='editor',
    )
    existing_group = ReviewGroup.objects.create(
        project=project,
        name='groupA',
        owner=users['old-group-owner'],
        config_version='old',
    )
    ReviewGroupModule.objects.create(
        group=existing_group, project_module=stale_project_module,
    )
    ReviewGroup.objects.create(
        project=project,
        name='stale',
        owner=users['old-group-owner'],
        config_version='old',
    )
    other_group = ReviewGroup.objects.create(
        project=other_project,
        name='keep',
        owner=users['old-group-owner'],
        config_version='old',
    )
    ReviewGroupModule.objects.create(
        group=other_group, project_module=other_project_module,
    )
    return {
        'users': users,
        'project': project,
        'other_project': other_project,
        'project_module': project_module,
        'other_group': other_group,
    }


@pytest.mark.django_db
def test_threshold_schema_and_project_override_merge(hierarchy_env):
    data = _config()
    data['risk_thresholds'] = {
        'tns_setup': {'medium_percent': 12, 'high_percent': 30},
    }
    data['projects']['projectA']['risk_thresholds'] = {
        'tns_setup': {'high_percent': 40},
        'area_total': {'medium_percent': 7},
    }

    errors, _ = validate_hierarchy(data)
    effective = get_effective_risk_thresholds(data, 'projectA')

    assert errors == []
    assert effective['tns_setup'] == {'medium_percent': 12, 'high_percent': 40}
    assert effective['area_total'] == {'medium_percent': 7, 'high_percent': 10.0}
    assert effective['utilization'] == {'medium_percent': 3.0, 'high_percent': 8.0}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('thresholds', 'message'),
    [
        ({'unknown': {'medium_percent': 1}}, 'unsupported metric'),
        ({'tns_setup': {'low_percent': 1}}, 'unsupported level'),
        ({'tns_setup': {'medium_percent': True}}, 'finite number'),
        ({'tns_setup': {'medium_percent': -1}}, 'nonnegative'),
        (
            {'tns_setup': {'medium_percent': 30, 'high_percent': 20}},
            'must not exceed high_percent',
        ),
    ],
)
def test_threshold_validation_rejects_invalid_types_levels_and_order(
    hierarchy_env, thresholds, message,
):
    data = _config()
    data['risk_thresholds'] = thresholds
    errors, _ = validate_hierarchy(data)
    assert any(message in error for error in errors)


@pytest.mark.django_db
def test_schema_rejects_unknown_entities_duplicate_modules_and_bad_version(hierarchy_env):
    data = _config()
    data['version'] = 1
    data['projects']['projectA']['owner'] = 'missing'
    data['projects']['projectA']['groups']['groupB'] = {
        'owner': 'group-owner',
        'modules': {'moduleA': {'release_owner': 'release-owner'}},
    }
    data['projects']['projectA']['groups']['groupC'] = {
        'owner': 'group-owner',
        'modules': {'missingModule': {'release_owner': 'missing-release'}},
    }
    data['projects']['missing-project'] = {
        'owner': 'project-owner',
        'groups': {},
    }
    errors, _ = validate_hierarchy(data)
    assert any('version must be' in error for error in errors)
    assert any("owner 'missing' does not exist" in error for error in errors)
    assert any('more than one group' in error for error in errors)
    assert any('missing-project: project does not exist' in error for error in errors)
    assert any('missingModule: no ProjectModule mapping' in error for error in errors)
    assert any("release owner 'missing-release' does not exist" in error for error in errors)


@pytest.mark.django_db
def test_sync_reconciles_stale_rows_and_preserves_unrelated_and_collaborators(
    hierarchy_env,
):
    data = _config()
    plan = sync_hierarchy(data, 'checksum', 'hierarchy.yaml')

    project = hierarchy_env['project']
    project_module = hierarchy_env['project_module']
    project_module.refresh_from_db()
    assert plan['changes']['group_deletes'] == 1
    assert plan['changes']['module_link_deletes'] == 1
    assert not ReviewGroup.objects.filter(project=project, name='stale').exists()
    assert ReviewGroup.objects.filter(project=project, name='groupA').exists()
    assert ReviewGroup.objects.filter(pk=hierarchy_env['other_group'].pk).exists()
    assert project_module.collaborators == '[7, 8]'
    assert ProjectMember.objects.get(
        project=project, user=hierarchy_env['users']['collaborator'],
    ).role == 'editor'
    assert ProjectMember.objects.get(
        project=project, user=hierarchy_env['users']['old-owner'],
    ).role == 'editor'


@pytest.mark.django_db
def test_check_is_zero_write_and_repeated_apply_is_noop(hierarchy_env, tmp_path):
    config = tmp_path / 'hierarchy.yaml'
    config.write_text(
        """
version: "1"
risk_thresholds: {}
projects:
  projectA:
    owner: project-owner
    groups:
      groupA:
        owner: group-owner
        modules:
          moduleA:
            release_owner: release-owner
""",
        encoding='utf-8',
    )
    before = {
        'groups': ReviewGroup.objects.count(),
        'links': ReviewGroupModule.objects.count(),
        'members': ProjectMember.objects.count(),
        'states': ReviewHierarchySyncState.objects.count(),
        'owner': hierarchy_env['project_module'].owner_id,
    }
    output = StringIO()
    call_command('sync_review_hierarchy', '--check', '--config', str(config), stdout=output)
    after = {
        'groups': ReviewGroup.objects.count(),
        'links': ReviewGroupModule.objects.count(),
        'members': ProjectMember.objects.count(),
        'states': ReviewHierarchySyncState.objects.count(),
        'owner': ProjectModule.objects.get(pk=hierarchy_env['project_module'].pk).owner_id,
    }
    assert after == before
    assert 'zero writes' in output.getvalue()

    data, checksum = load_hierarchy(config)
    first = sync_hierarchy(data, checksum, config)
    state_time = ReviewHierarchySyncState.objects.get().applied_at
    group_time = ReviewGroup.objects.get(
        project=hierarchy_env['project'], name='groupA',
    ).updated_at
    second = sync_hierarchy(data, checksum, config)
    assert first['total_changes'] > 0
    assert second['total_changes'] == 0
    assert ReviewHierarchySyncState.objects.get().applied_at == state_time
    assert ReviewGroup.objects.get(
        project=hierarchy_env['project'], name='groupA',
    ).updated_at == group_time


@pytest.mark.django_db
def test_hierarchy_status_api_allows_owner_read_only_access(
    hierarchy_env, tmp_path, client, monkeypatch,
):
    config = tmp_path / 'hierarchy.yaml'
    config.write_text(
        """
version: "1"
risk_thresholds: {}
projects:
  projectA:
    owner: project-owner
    groups:
      groupA:
        owner: group-owner
        modules:
          moduleA:
            release_owner: release-owner
""",
        encoding='utf-8',
    )
    monkeypatch.setattr(
        'django_app.services.review_hierarchy.DEFAULT_CONFIG_PATH',
        config,
    )
    viewer = User.objects.create_user(username='viewer-status', role='viewer')
    client.force_login(viewer)
    assert client.get('/api/admin/review-hierarchy/status').status_code == 403

    owner = User.objects.create_user(username='owner-status', role='owner')
    client.force_login(owner)
    response = client.get('/api/admin/review-hierarchy/status')
    assert response.status_code == 200
    assert response.json()['validation'] == {'valid': True, 'errors': []}
    assert response.json()['permissions']['can_edit_module_owner'] is False
    assert response.json()['owner_options'] == []
    assert client.post('/api/admin/review-hierarchy/status').status_code == 405

    admin = User.objects.create_user(username='admin-status', role='admin')
    client.force_login(admin)
    response = client.get('/api/admin/review-hierarchy/status')
    assert response.status_code == 200
    assert response.json()['validation'] == {'valid': True, 'errors': []}
    assert response.json()['projects'][0]['effective_thresholds']['tns_setup']
    assert response.json()['permissions']['can_edit_module_owner'] is True
    assert any(
        option['username'] == 'release-owner'
        for option in response.json()['owner_options']
    )
    assert client.post('/api/admin/review-hierarchy/status').status_code == 405


def _write_hierarchy_config(path):
    path.write_text(
        """
version: "1"
risk_thresholds: {}
projects:
  projectA:
    owner: project-owner
    custom_project_field: keep-project
    groups:
      groupA:
        owner: group-owner
        description: Keep this description
        modules:
          moduleA:
            release_owner: release-owner
            custom_module_field: keep-module
""",
        encoding='utf-8',
    )


@pytest.mark.django_db
def test_admin_can_update_module_owner_in_database_and_yaml(
    hierarchy_env, tmp_path, client, monkeypatch,
):
    config = tmp_path / 'hierarchy.yaml'
    _write_hierarchy_config(config)
    data, checksum = load_hierarchy(config)
    sync_hierarchy(data, checksum, config)
    data['projects']['deleted-project-kept-in-yaml'] = {
        'owner': 'project-owner',
        'groups': {
            'retained': {
                'owner': 'group-owner',
                'modules': {
                    'retained-module': {'release_owner': 'release-owner'},
                },
            },
        },
    }
    config.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding='utf-8',
    )
    _data_with_deleted_project, checksum = load_hierarchy(config)
    new_owner = User.objects.create_user(username='new-release-owner', role='owner')
    admin = User.objects.create_user(username='hierarchy-admin', role='admin')
    monkeypatch.setattr(
        'django_app.services.review_hierarchy.DEFAULT_CONFIG_PATH',
        config,
    )
    client.force_login(admin)

    response = client.post(
        '/api/admin/review-hierarchy/module-owner',
        data={
            'project': 'projectA',
            'group': 'groupA',
            'module': 'moduleA',
            'owner_id': new_owner.id,
            'config_checksum': checksum,
        },
        content_type='application/json',
    )

    assert response.status_code == 200
    hierarchy_env['project_module'].refresh_from_db()
    assert hierarchy_env['project_module'].owner_id == new_owner.id
    saved = yaml.safe_load(config.read_text(encoding='utf-8'))
    module = saved['projects']['projectA']['groups']['groupA']['modules']['moduleA']
    assert module['release_owner'] == 'new-release-owner'
    assert module['custom_module_field'] == 'keep-module'
    assert saved['projects']['projectA']['custom_project_field'] == 'keep-project'
    assert 'deleted-project-kept-in-yaml' in saved['projects']
    assert response.json()['status']['current_db_diff']['in_sync'] is True


@pytest.mark.django_db
@pytest.mark.parametrize('role', ['owner', 'viewer'])
def test_non_admin_cannot_update_hierarchy_owner(
    hierarchy_env, tmp_path, client, monkeypatch, role,
):
    config = tmp_path / 'hierarchy.yaml'
    _write_hierarchy_config(config)
    original = config.read_bytes()
    monkeypatch.setattr(
        'django_app.services.review_hierarchy.DEFAULT_CONFIG_PATH',
        config,
    )
    actor = User.objects.create_user(username=f'{role}-actor', role=role)
    client.force_login(actor)

    response = client.post(
        '/api/admin/review-hierarchy/module-owner',
        data={
            'project': 'projectA',
            'group': 'groupA',
            'module': 'moduleA',
            'owner_id': hierarchy_env['users']['old-release-owner'].id,
        },
        content_type='application/json',
    )

    assert response.status_code == 403
    assert config.read_bytes() == original


@pytest.mark.django_db
def test_yaml_replace_failure_rolls_back_database_owner(
    hierarchy_env, tmp_path, client, monkeypatch,
):
    config = tmp_path / 'hierarchy.yaml'
    _write_hierarchy_config(config)
    data, checksum = load_hierarchy(config)
    sync_hierarchy(data, checksum, config)
    original = config.read_bytes()
    hierarchy_env['project_module'].refresh_from_db()
    old_owner_id = hierarchy_env['project_module'].owner_id
    new_owner = User.objects.create_user(username='failed-release-owner', role='owner')
    admin = User.objects.create_user(username='failed-write-admin', role='admin')
    monkeypatch.setattr(
        'django_app.services.review_hierarchy.DEFAULT_CONFIG_PATH',
        config,
    )

    def fail_replace(_source, _target):
        raise OSError('simulated read-only config directory')

    monkeypatch.setattr(
        'django_app.services.review_hierarchy.os.replace',
        fail_replace,
    )
    client.force_login(admin)
    response = client.post(
        '/api/admin/review-hierarchy/module-owner',
        data={
            'project': 'projectA',
            'group': 'groupA',
            'module': 'moduleA',
            'owner_id': new_owner.id,
            'config_checksum': checksum,
        },
        content_type='application/json',
    )

    assert response.status_code == 500
    assert 'Owner 未保存' in response.json()['error']
    hierarchy_env['project_module'].refresh_from_db()
    assert hierarchy_env['project_module'].owner_id == old_owner_id
    assert config.read_bytes() == original


@pytest.mark.django_db
def test_hierarchy_status_excludes_offline_projects_and_sorts_locked_last(tmp_path):
    owner = User.objects.create_user(username='lifecycle-release-owner', role='owner')

    def configured_project(name, status):
        project = Project.objects.create(name=name, status=status)
        module = GlobalModule.objects.create(
            name=f'{name}-module',
            normalized_name='ignored',
        )
        ProjectModule.objects.create(project=project, module=module, owner_id=owner.id)
        return {
            'owner': owner.username,
            'groups': {
                'default': {
                    'owner': owner.username,
                    'modules': {
                        module.name: {'release_owner': owner.username},
                    },
                },
            },
        }

    config_data = {
        'version': 'lifecycle-status',
        'risk_thresholds': {},
        'projects': {
            'zulu-active': configured_project('zulu-active', 'active'),
            'alpha-locked': configured_project('alpha-locked', 'locked'),
            'alpha-active': configured_project('alpha-active', 'active'),
            'zulu-locked': configured_project('zulu-locked', 'locked'),
            'archived-project': configured_project('archived-project', 'archived'),
            'hidden-project': configured_project('hidden-project', 'hidden'),
            'deleted-project': {
                'owner': owner.username,
                'groups': {
                    'default': {
                        'owner': owner.username,
                        'modules': {
                            'missing-module': {'release_owner': owner.username},
                        },
                    },
                },
            },
        },
    }
    config = tmp_path / 'lifecycle-hierarchy.yaml'
    config.write_text(
        yaml.safe_dump(config_data, sort_keys=False),
        encoding='utf-8',
    )
    original = config.read_bytes()

    result = hierarchy_status(config)

    assert result['validation'] == {'valid': True, 'errors': []}
    assert [
        (project['name'], project['status'])
        for project in result['projects']
    ] == [
        ('alpha-active', 'active'),
        ('zulu-active', 'active'),
        ('alpha-locked', 'locked'),
        ('zulu-locked', 'locked'),
    ]
    assert {
        (project['name'], project['status'])
        for project in result['excluded_projects']
    } == {
        ('archived-project', 'archived'),
        ('hidden-project', 'hidden'),
        ('deleted-project', 'deleted'),
    }
    assert result['current_db_diff']['desired']['projects'] == 4
    assert config.read_bytes() == original
