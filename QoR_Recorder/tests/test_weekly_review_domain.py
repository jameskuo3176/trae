import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import connections

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import (
    GlobalModule,
    GroupReview,
    LegacyModuleMapping,
    Module,
    Project,
    ProjectMember,
    ProjectModule,
    QorRecord,
    ReviewGroup,
    ReviewGroupModule,
    ReviewSnapshot,
    SubsystemReview,
    User,
    WeeklyRunSelection,
)
from django_app.services.risk_rating import shanghai_week_window
from django_app.services.weekly_review import (
    SnapshotIntegrityError,
    build_weekly_overview,
    create_weekly_snapshot,
    get_weekly_review_input,
    select_weekly_star,
)


SHANGHAI = ZoneInfo('Asia/Shanghai')
WEEK = date(2026, 8, 10)


def _discard_dynamic_connection(alias):
    if alias in connections.databases:
        connections[alias].close()
        connections.databases.pop(alias, None)
    if hasattr(connections._connections, alias):
        delattr(connections._connections, alias)


@pytest.fixture
def weekly_env(tmp_path, settings, django_db_blocker, monkeypatch):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        admin = User.objects.create_user('weekly-admin', role='admin')
        owner = User.objects.create_user('weekly-owner', role='owner')
        project_owner = User.objects.create_user('weekly-project-owner', role='owner')
        outsider = User.objects.create_user('weekly-outsider', role='owner')
        projects = [
            Project.objects.create(name='Weekly Alpha'),
            Project.objects.create(name='Weekly Beta'),
        ]
        config = {
            'version': 'weekly-v1',
            'timezone': 'Asia/Shanghai',
            'risk_thresholds': {},
            'projects': {
                project.name: {
                    'owner': project_owner.username,
                    'risk_thresholds': {
                        'area_total': {'medium_percent': 7, 'high_percent': 14},
                    },
                    'groups': {},
                }
                for project in projects
            },
        }
        monkeypatch.setattr(
            'django_app.services.weekly_review.load_hierarchy',
            lambda: (config, 'c' * 64),
        )
        project_data = []
        for project in projects:
            global_module = GlobalModule.objects.create(
                name=f'core-{project.id}', normalized_name='ignored',
            )
            project_module = ProjectModule.objects.create(
                project=project, module=global_module, owner_id=owner.id,
            )
            group = ReviewGroup.objects.create(
                project=project,
                name=f'group-{project.id}',
                owner=project_owner,
                config_version='weekly-v1',
            )
            ReviewGroupModule.objects.create(group=group, project_module=project_module)
            ProjectMember.objects.create(
                project=project, user=project_owner, role='owner',
            )
            alias = _get_project_db_alias(project.id)
            _discard_dynamic_connection(alias)
            get_project_engine(project.id)
            call_command('migrate', database=alias, verbosity=0, interactive=False)
            local_module = Module.objects.using(alias).create(
                id=1,
                project_id=project.id,
                name=global_module.name,
                owner_id=owner.id,
            )
            LegacyModuleMapping.objects.create(
                project=project,
                legacy_module_id=local_module.id,
                module=global_module,
                legacy_name=local_module.name,
            )
            project_data.append({
                'project': project,
                'global_module': global_module,
                'project_module': project_module,
                'group': group,
                'alias': alias,
                'local_module': local_module,
            })
    yield {
        'admin': admin,
        'owner': owner,
        'project_owner': project_owner,
        'outsider': outsider,
        'projects': project_data,
        'blocker': django_db_blocker,
    }
    with django_db_blocker.unblock():
        for item in project_data:
            _discard_dynamic_connection(item['alias'])


def _record(item, record_id, recorded_at, *, released_at=None, **metrics):
    return QorRecord.objects.using(item['alias']).create(
        id=record_id,
        module=item['local_module'],
        version=f'run-{record_id}',
        recorded_at=recorded_at,
        is_released=released_at is not None,
        released_at=released_at,
        **metrics,
    )


def test_shanghai_window_normalizes_utc_and_has_no_dst_shift():
    start, end = shanghai_week_window(
        datetime(2026, 8, 9, 16, 0, tzinfo=dt_timezone.utc)
    )
    assert start.isoformat() == '2026-08-10T00:00:00+08:00'
    assert end.isoformat() == '2026-08-17T00:00:00+08:00'
    winter_start, winter_end = shanghai_week_window(
        datetime(2026, 1, 14, 12, tzinfo=SHANGHAI)
    )
    assert winter_start.utcoffset() == winter_end.utcoffset() == timedelta(hours=8)


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_weekly_candidates_use_upload_window_and_implicit_latest(weekly_env):
    item = weekly_env['projects'][0]
    with weekly_env['blocker'].unblock():
        start = datetime(2026, 8, 10, tzinfo=SHANGHAI)
        previous_star = _record(
            item, 7, start - timedelta(days=6), released_at=start - timedelta(days=6),
        )
        WeeklyRunSelection.objects.create(
            project=item['project'],
            module=item['global_module'],
            week_start=WEEK - timedelta(days=7),
            record_id=str(previous_star.id),
            selected_by=weekly_env['owner'],
            source='weekly_release',
        )
        boundary = _record(item, 1, start, released_at=start - timedelta(microseconds=1))
        first = _record(
            item, 2, start + timedelta(hours=1), released_at=start,
            area_total=100, tns_setup=-10, utilization=70,
        )
        last = _record(
            item, 3, start + timedelta(days=6), released_at=start + timedelta(days=6),
            area_total=108, tns_setup=-12, utilization=71,
        )
        _record(item, 4, start + timedelta(days=7), released_at=start + timedelta(days=7))
        latest_upload = _record(item, 5, start + timedelta(days=6, hours=1))

        overview = build_weekly_overview(item['project'].id, WEEK)
        module = overview['groups'][0]['modules'][0]
        assert [row['id'] for row in module['candidates']] == [
            boundary.id, first.id, last.id, latest_upload.id,
        ]
        assert module['star']['id'] == latest_upload.id
        assert module['star_source'] == 'implicit_weekly_upload'
        assert module['baseline']['id'] == previous_star.id
        assert overview['effective_thresholds']['area_total']['medium_percent'] == 7
        assert overview['config_version'] == 'weekly-v1'
        assert overview['config_checksum'] == 'c' * 64
        selection = select_weekly_star(
            weekly_env['owner'], item['project'].id,
            item['global_module'].id, first.id, WEEK,
        )
        assert selection.source == 'weekly_upload'
        assert build_weekly_overview(
            item['project'].id, WEEK,
        )['groups'][0]['modules'][0]['star_source'] == 'explicit_weekly_upload'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_star_policy_allows_any_weekly_upload_and_rejects_out_of_week_runs(
    weekly_env,
):
    item = weekly_env['projects'][0]
    with weekly_env['blocker'].unblock():
        start = datetime(2026, 8, 10, tzinfo=SHANGHAI)
        historical = _record(item, 1, start - timedelta(days=2), released_at=start - timedelta(days=2))
        older_upload = _record(item, 2, start + timedelta(hours=1))
        fallback = _record(item, 3, start + timedelta(hours=2))

        with pytest.raises(PermissionError):
            select_weekly_star(
                weekly_env['outsider'], item['project'].id,
                item['global_module'].id, fallback.id, WEEK,
            )
        with pytest.raises(ValueError, match='uploaded inside'):
            select_weekly_star(
                weekly_env['owner'], item['project'].id,
                item['global_module'].id, historical.id, WEEK,
            )

        selection = select_weekly_star(
            weekly_env['owner'], item['project'].id,
            item['global_module'].id, older_upload.id, WEEK,
        )
        updated_at = selection.updated_at
        repeated = select_weekly_star(
            weekly_env['owner'], item['project'].id,
            item['global_module'].id, older_upload.id, WEEK,
        )
        assert repeated.pk == selection.pk
        assert repeated.updated_at == updated_at
        assert repeated.source == 'weekly_upload'
        overview = build_weekly_overview(item['project'].id, WEEK)
        module = overview['groups'][0]['modules'][0]
        assert [row['id'] for row in module['candidates']] == [
            older_upload.id, fallback.id,
        ]
        assert module['star_source'] == 'explicit_weekly_upload'
        assert module['baseline']['id'] == historical.id


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_normal_owner_can_view_review_without_project_mutation_rights(
    weekly_env, client,
):
    item = weekly_env['projects'][0]
    with weekly_env['blocker'].unblock():
        client.force_login(weekly_env['outsider'])

        response = client.get('/api/reviews/weekly', {
            'project_id': item['project'].id,
            'week_start': WEEK.isoformat(),
        })

        assert response.status_code == 200
        payload = response.json()
        assert payload['capabilities']['can_freeze'] is False
        assert payload['capabilities']['can_create_project_review'] is False
        assert payload['groups'][0]['can_create_review'] is False
        assert payload['groups'][0]['modules'][0]['can_select_star'] is False
        assert client.get('/api/reviews/weekly', {
            'project_id': item['project'].id,
            'week_start': WEEK.isoformat(),
            'live_preview': 'true',
        }).status_code == 403


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_selection_identity_isolated_across_projects_with_colliding_local_ids(weekly_env):
    with weekly_env['blocker'].unblock():
        start = datetime(2026, 8, 10, tzinfo=SHANGHAI)
        for item in weekly_env['projects']:
            _record(item, 1, start, released_at=start)
            select_weekly_star(
                weekly_env['owner'], item['project'].id,
                item['global_module'].id, 1, WEEK,
            )
        selections = WeeklyRunSelection.objects.filter(week_start=WEEK).order_by('project_id')
        assert selections.count() == 2
        assert list(selections.values_list('record_id', flat=True)) == ['1', '1']
        assert len(set(selections.values_list('project_id', flat=True))) == 2


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_snapshot_is_idempotent_integrity_checked_and_freezes_later_changes(weekly_env):
    item = weekly_env['projects'][0]
    with weekly_env['blocker'].unblock():
        start = datetime(2026, 8, 10, tzinfo=SHANGHAI)
        original = _record(
            item, 1, start + timedelta(hours=1), released_at=start + timedelta(hours=1),
            area_total=100,
        )
        first, created = create_weekly_snapshot(
            weekly_env['project_owner'], item['project'].id, WEEK,
        )
        second, created_again = create_weekly_snapshot(
            weekly_env['project_owner'], item['project'].id, WEEK,
        )
        assert created is True
        assert created_again is False
        assert second.id == first.id
        assert first.verify_integrity()
        assert json.loads(first.frozen_data)['groups'][0]['modules'][0]['risk']['rating'] == (
            'unrated'
        )
        assert ReviewSnapshot.objects.using(item['alias']).filter(
            project_id=item['project'].id,
            snapshot_type='weekly_review',
            week_start=WEEK,
        ).count() == 1

        _record(
            item, 2, start + timedelta(days=1), released_at=start + timedelta(days=1),
            area_total=999,
        )
        frozen = get_weekly_review_input(
            weekly_env['owner'], item['project'].id, WEEK,
        )
        assert frozen['is_frozen'] is True
        assert frozen['snapshot']['id'] == first.id
        assert frozen['groups'][0]['modules'][0]['star']['id'] == original.id
        with pytest.raises(ValueError, match='frozen'):
            select_weekly_star(
                weekly_env['owner'], item['project'].id,
                item['global_module'].id, 2, WEEK,
            )
        live = get_weekly_review_input(
            weekly_env['project_owner'], item['project'].id, WEEK, live_preview=True,
        )
        assert live['is_frozen'] is False
        assert live['groups'][0]['modules'][0]['star']['id'] == 2
        with pytest.raises(PermissionError):
            get_weekly_review_input(
                weekly_env['owner'], item['project'].id, WEEK, live_preview=True,
            )

        first.frozen_data = json.dumps({'mutated': True})
        with pytest.raises(ValueError, match='immutable'):
            first.save(using=item['alias'])
        first.refresh_from_db(using=item['alias'])
        ReviewSnapshot.objects.using(item['alias']).filter(pk=first.pk).update(
            frozen_data=json.dumps({'tampered': True}),
        )
        first.refresh_from_db(using=item['alias'])
        assert not first.verify_integrity()
        with pytest.raises(SnapshotIntegrityError):
            get_weekly_review_input(weekly_env['project_owner'], item['project'].id, WEEK)


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_weekly_api_defaults_frozen_and_live_preview_is_owner_only(weekly_env, client):
    item = weekly_env['projects'][0]
    with weekly_env['blocker'].unblock():
        start = datetime(2026, 8, 10, tzinfo=SHANGHAI)
        _record(item, 1, start, released_at=start)
        create_weekly_snapshot(weekly_env['project_owner'], item['project'].id, WEEK)

        client.force_login(weekly_env['owner'])
        frozen = client.get('/api/reviews/weekly', {
            'project_id': item['project'].id,
            'week_start': WEEK.isoformat(),
        })
        assert frozen.status_code == 200
        assert frozen.json()['input_mode'] == 'frozen'
        denied = client.get('/api/reviews/weekly', {
            'project_id': item['project'].id,
            'week_start': WEEK.isoformat(),
            'live_preview': 'true',
        })
        assert denied.status_code == 403

        client.force_login(weekly_env['project_owner'])
        preview = client.get('/api/reviews/weekly', {
            'project_id': item['project'].id,
            'week_start': WEEK.isoformat(),
            'live_preview': 'true',
        })
        assert preview.status_code == 200
        assert preview.json()['input_mode'] == 'live_preview'


@pytest.mark.django_db(transaction=True, databases='__all__')
@pytest.mark.parametrize(
    ('review_type', 'scope'),
    [('group', 'group_name'), ('project', None)],
)
def test_review_creation_requires_and_binds_authoritative_snapshot(
    weekly_env, client, review_type, scope,
):
    item = weekly_env['projects'][0]
    project_id = item['project'].id
    client.force_login(weekly_env['project_owner'])
    payload = {'project_id': project_id, 'week_start': WEEK.isoformat()}
    if scope:
        payload[scope] = item['group'].name

    missing = client.post(
        f'/api/reviews/{review_type}',
        json.dumps(payload),
        content_type='application/json',
    )
    assert missing.status_code == 409
    assert missing.json()['code'] == 'review_snapshot_required'

    with weekly_env['blocker'].unblock():
        start = datetime(2026, 8, 10, tzinfo=SHANGHAI)
        original = _record(item, 1, start, released_at=start, area_total=100)
        snapshot, _ = create_weekly_snapshot(
            weekly_env['project_owner'], project_id, WEEK,
        )

    created = client.post(
        f'/api/reviews/{review_type}',
        json.dumps(payload),
        content_type='application/json',
    )
    assert created.status_code == 201, created.content
    provenance = created.json()['snapshot_provenance']
    assert provenance['id'] == snapshot.id
    assert provenance['checksum'] == snapshot.checksum
    assert provenance['week_start'] == WEEK.isoformat()
    assert provenance['config_version'] == 'weekly-v1'
    assert provenance['verified'] is True

    with weekly_env['blocker'].unblock():
        _record(
            item, 2, start + timedelta(days=1),
            released_at=start + timedelta(days=1), area_total=999,
        )
    detail = client.get(
        f"/api/reviews/{review_type}/{created.json()['id']}",
        {'project_id': project_id},
    )
    assert detail.status_code == 200
    assert detail.json()['snapshot_provenance']['verified'] is True
    model = GroupReview if review_type == 'group' else SubsystemReview
    row = model.objects.using(item['alias']).get(pk=created.json()['id'])
    frozen_copy = json.loads(row.snapshot_data)
    assert frozen_copy['groups'][0]['modules'][0]['star']['id'] == original.id


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_legacy_review_is_labeled_and_rejected_review_can_be_resubmitted(
    weekly_env, client,
):
    item = weekly_env['projects'][0]
    owner = weekly_env['project_owner']
    row = GroupReview.objects.using(item['alias']).create(
        project_id=item['project'].id,
        group_name=item['group'].name,
        title='Legacy review',
        leader_id=owner.id,
        status='rejected',
        review_comment='Fix timing evidence',
    )
    client.force_login(owner)

    detail = client.get(
        f'/api/reviews/group/{row.id}',
        {'project_id': item['project'].id},
    )
    assert detail.json()['snapshot_provenance']['binding'] == 'legacy_live_unbound'
    assert detail.json()['can_edit'] is True
    assert detail.json()['can_delete'] is True
    assert detail.json()['can_submit'] is True

    submitted = client.post(
        f'/api/reviews/group/{row.id}/submit',
        json.dumps({'project_id': item['project'].id}),
        content_type='application/json',
    )
    assert submitted.status_code == 200
    assert submitted.json()['status'] == 'submitted'
    assert submitted.json()['submission_count'] == 1
    assert submitted.json()['resubmitted_at']
    assert submitted.json()['review_comment'] == 'Fix timing evidence'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_project_owner_can_finalize_own_project_review(weekly_env, client):
    item = weekly_env['projects'][0]
    owner = weekly_env['project_owner']
    row = SubsystemReview.objects.using(item['alias']).create(
        project_id=item['project'].id,
        subsystem=item['project'].name,
        title='Owner final review',
        manager_id=owner.id,
        status='submitted',
    )
    client.force_login(owner)
    detail = client.get(
        f'/api/reviews/project/{row.id}',
        {'project_id': item['project'].id},
    )
    assert detail.json()['can_review'] is True
    approved = client.post(
        f'/api/reviews/project/{row.id}/review',
        json.dumps({
            'project_id': item['project'].id,
            'action': 'approve',
            'comment': 'Owner final signoff',
        }),
        content_type='application/json',
    )
    assert approved.status_code == 200
    assert approved.json()['status'] == 'approved'
