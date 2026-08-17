"""Authoritative weekly review inputs and immutable project-local snapshots."""
from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import (
    LegacyModuleMapping,
    Project,
    ProjectModule,
    QorRecord,
    ReviewGroup,
    ReviewSnapshot,
    WeeklyRunSelection,
)
from django_app.services.review_hierarchy import (
    get_effective_risk_thresholds,
    load_hierarchy,
)
from django_app.services.risk_rating import rate_record, shanghai_week_window


SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotIntegrityError(ValueError):
    """Raised when stored frozen review input no longer matches its checksum."""


def _canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str,
    )


def _window(week_start=None):
    tz = ZoneInfo('Asia/Shanghai')
    if week_start:
        if isinstance(week_start, datetime):
            week_start = week_start.astimezone(tz).date() if week_start.tzinfo else week_start.date()
        if not isinstance(week_start, date):
            raise ValueError('week_start must be an ISO date')
        if week_start.weekday() != 0:
            raise ValueError('week_start must be a Monday in Asia/Shanghai')
        value = datetime.combine(week_start, time.min, tzinfo=tz)
        return value, value + timedelta(days=7)
    return shanghai_week_window()


def _legacy_ids(project_id, global_module_id):
    return list(LegacyModuleMapping.objects.filter(
        project_id=project_id,
        module_id=global_module_id,
    ).values_list('legacy_module_id', flat=True))


def _record_payload(record):
    payload = record.to_dict()
    extra = payload.get('extra_fields') or {}
    timing_sections = extra.get('timing_sections') if isinstance(extra, dict) else None
    if not timing_sections and record.raw_dc_report:
        raw = record.raw_dc_report
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = {}
        timing_sections = {}
        for timing_name, timing_section in (raw.get('timing') or {}).items():
            if not isinstance(timing_section, dict):
                continue
            scenarios = {}
            for scenario_name, scenario in (timing_section.get('scenarios') or {}).items():
                groups = {}
                for group_name, metrics in (
                    (scenario or {}).get('path_groups') or {}
                ).items():
                    if not isinstance(metrics, dict):
                        continue
                    groups[group_name] = {
                        'wns': metrics.get('WNS', metrics.get('wns')),
                        'tns': metrics.get('TNS', metrics.get('tns')),
                        'nvp': metrics.get('NVP', metrics.get('nvp')),
                        'period': metrics.get(
                            'Clk_Period',
                            metrics.get('clk_period', metrics.get('period')),
                        ),
                        'lol': metrics.get('LoL', metrics.get('lol')),
                    }
                if groups:
                    scenarios[scenario_name] = groups
            if scenarios:
                timing_sections[timing_name] = scenarios
    if timing_sections:
        payload['timing_sections'] = timing_sections
    payload.pop('raw_dc_report', None)
    return payload


def _selected_record(
    project, project_module, start, eligible_candidates, default_record,
):
    selection = WeeklyRunSelection.objects.filter(
        project=project,
        module=project_module.module,
        week_start=start.date(),
    ).first()
    if selection:
        selected = next(
            (row for row in eligible_candidates if str(row.id) == selection.record_id),
            None,
        )
        if selected:
            return selected, True, selection
    return default_record, False, None


def _baseline_record(project, project_module, start, alias):
    previous = WeeklyRunSelection.objects.filter(
        project=project,
        module=project_module.module,
        week_start__lt=start.date(),
    ).order_by('-week_start').first()
    legacy_ids = _legacy_ids(project.id, project_module.module_id)
    if previous:
        row = QorRecord.objects.using(alias).filter(
            pk=previous.record_id,
            module_id__in=legacy_ids,
            is_released=True,
        ).first()
        if row:
            return row
    return QorRecord.objects.using(alias).filter(
        module_id__in=legacy_ids,
        recorded_at__lt=start,
    ).order_by('-recorded_at', '-id').first()


def _snapshot_for_week(project_id, week_start):
    alias = _get_project_db_alias(project_id)
    get_project_engine(project_id)
    return ReviewSnapshot.objects.using(alias).filter(
        project_id=project_id,
        snapshot_type='weekly_review',
        week_start=week_start,
    ).first()


def get_authoritative_weekly_snapshot(project_id, week_start, verify=True):
    """Stable service contract for future Group/Project review creation."""
    start, _ = _window(week_start)
    snapshot = _snapshot_for_week(project_id, start.date())
    if snapshot and verify:
        _read_snapshot(snapshot)
    return snapshot


def _snapshot_metadata(snapshot):
    return {
        'id': snapshot.id,
        'checksum': snapshot.checksum,
        'created_at': snapshot.created_at.isoformat() if snapshot.created_at else None,
        'created_by': snapshot.created_by,
        'schema_version': snapshot.schema_version,
        'verified': snapshot.verify_integrity(),
    }


def _read_snapshot(snapshot):
    if not snapshot.verify_integrity():
        raise SnapshotIntegrityError(
            f'review snapshot {snapshot.id} failed checksum verification'
        )
    try:
        payload = json.loads(snapshot.frozen_data)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SnapshotIntegrityError(
            f'review snapshot {snapshot.id} contains invalid JSON'
        ) from exc
    payload['is_frozen'] = True
    payload['input_mode'] = 'frozen'
    payload['snapshot'] = _snapshot_metadata(snapshot)
    return payload


def build_weekly_overview(project_id, week_start=None):
    """Build a live preview; callers must prefer ``get_weekly_review_input``."""
    project = Project.objects.get(pk=project_id)
    start, end = _window(week_start)
    alias = _get_project_db_alias(project.id)
    get_project_engine(project.id)
    config, config_checksum = load_hierarchy()
    config_version = str(config.get('version', ''))
    thresholds = get_effective_risk_thresholds(config, project.name)
    groups = []
    for group in ReviewGroup.objects.filter(project=project).select_related('owner').order_by('name'):
        modules = []
        links = group.module_links.select_related(
            'project_module__module'
        ).order_by('project_module__module__name')
        for link in links:
            project_module = link.project_module
            legacy_ids = _legacy_ids(project.id, project_module.module_id)
            weekly_candidates = list(QorRecord.objects.using(alias).filter(
                module_id__in=legacy_ids,
                recorded_at__gte=start,
                recorded_at__lt=end,
            ).order_by('recorded_at', 'id'))
            latest_upload = QorRecord.objects.using(alias).filter(
                module_id__in=legacy_ids,
                recorded_at__lt=end,
            ).order_by('-recorded_at', '-id').first()
            eligible_candidates = (
                weekly_candidates if weekly_candidates else [latest_upload] if latest_upload else []
            )
            default_record = (
                weekly_candidates[-1]
                if weekly_candidates
                else latest_upload
            )
            selected, explicit, selection = _selected_record(
                project,
                project_module,
                start,
                eligible_candidates,
                default_record,
            )
            carried_forward = bool(selected and not weekly_candidates)
            baseline = _baseline_record(project, project_module, start, alias)
            risk = (
                rate_record(_record_payload(selected), _record_payload(baseline), thresholds)
                if selected and baseline and selected.id != baseline.id
                else {
                    'rating': 'unrated',
                    'details': [],
                    'reason': (
                        'no selected run'
                        if not selected
                        else 'carried forward from latest upload'
                        if carried_forward
                        else 'no historical baseline'
                    ),
                }
            )
            modules.append({
                'module_id': project_module.module_id,
                'module_name': project_module.module.name,
                'release_owner_id': project_module.owner_id,
                'candidates': [
                    {
                        **_record_payload(row),
                        'review_candidate_source': (
                            'weekly_upload' if weekly_candidates else 'carried_forward_latest_upload'
                        ),
                    }
                    for row in eligible_candidates
                ],
                'candidate_limit_reached': False,
                'star': _record_payload(selected) if selected else None,
                'star_explicit': explicit,
                'star_source': (
                    'explicit_carried_forward'
                    if explicit and carried_forward
                    else 'explicit_weekly_upload'
                    if explicit
                    else 'carried_forward_latest_upload'
                    if carried_forward
                    else 'implicit_weekly_upload'
                ),
                'has_weekly_update': bool(weekly_candidates),
                'upload_time': (
                    selected.recorded_at.isoformat()
                    if selected and selected.recorded_at
                    else None
                ),
                'star_selected_by': selection.selected_by_id if selection else None,
                'baseline': _record_payload(baseline) if baseline else None,
                'risk': risk,
            })
        groups.append({
            'id': group.id,
            'name': group.name,
            'owner_id': group.owner_id,
            'owner_username': group.owner.username,
            'modules': modules,
        })
    return {
        'project_id': project.id,
        'project_name': project.name,
        'week_start': start.date().isoformat(),
        'week_end': (end.date() - timedelta(days=1)).isoformat(),
        'timezone': 'Asia/Shanghai',
        'config_version': config_version,
        'config_checksum': config_checksum,
        'effective_thresholds': thresholds,
        'is_frozen': False,
        'input_mode': 'live_preview',
        'snapshot': None,
        'groups': groups,
    }


def get_weekly_review_input(user, project_id, week_start=None, live_preview=False):
    """Return frozen input by default, with owner/admin-only live preview."""
    start, _ = _window(week_start)
    snapshot = _snapshot_for_week(project_id, start.date())
    can_preview = bool(
        user.is_admin
        or user.project_memberships.filter(project_id=project_id, role='owner').exists()
    )
    if snapshot and not live_preview:
        payload = _read_snapshot(snapshot)
        payload['can_live_preview'] = can_preview
        return payload
    if live_preview and not can_preview:
        raise PermissionError('only a project owner or admin may view live preview')
    payload = build_weekly_overview(project_id, start.date())
    payload['can_live_preview'] = can_preview
    if snapshot:
        payload['frozen_snapshot'] = _snapshot_metadata(snapshot)
    return payload


def select_weekly_star(user, project_id, module_id, record_id, week_start=None):
    project_module = ProjectModule.objects.select_related('module').get(
        project_id=project_id,
        module_id=module_id,
    )
    if not user.is_admin and project_module.owner_id != user.id:
        raise PermissionError('only the release owner may select the weekly star')
    start, end = _window(week_start)
    if _snapshot_for_week(project_id, start.date()):
        raise ValueError(
            'weekly review input is frozen; official star changes are not allowed'
        )
    alias = _get_project_db_alias(project_id)
    get_project_engine(project_id)
    legacy_ids = _legacy_ids(project_id, module_id)
    record = QorRecord.objects.using(alias).filter(
        pk=record_id,
        module_id__in=legacy_ids,
    ).first()
    if not record:
        raise ValueError('record does not belong to the requested project and module')
    weekly_uploads = QorRecord.objects.using(alias).filter(
        module_id__in=legacy_ids,
        recorded_at__gte=start,
        recorded_at__lt=end,
    )
    if weekly_uploads.exists():
        if not record.recorded_at or not start <= record.recorded_at < end:
            raise ValueError(
                'record must be uploaded inside the requested Shanghai week'
            )
        source = 'weekly_upload'
    else:
        latest_upload = QorRecord.objects.using(alias).filter(
            module_id__in=legacy_ids,
            recorded_at__lt=end,
        ).order_by('-recorded_at', '-id').first()
        if not latest_upload or str(latest_upload.id) != str(record.id):
            raise ValueError(
                'only the exact latest upload may be selected as carried-forward candidate'
            )
        source = 'carried_forward_latest_upload'
    with transaction.atomic():
        existing = WeeklyRunSelection.objects.select_for_update().filter(
            project_id=project_id,
            module_id=module_id,
            week_start=start.date(),
        ).first()
        if (
            existing
            and existing.record_id == str(record.id)
            and existing.source == source
            and existing.selected_by_id == user.id
        ):
            return existing
        selection, _ = WeeklyRunSelection.objects.update_or_create(
            project_id=project_id,
            module_id=module_id,
            week_start=start.date(),
            defaults={
                'record_id': str(record.id),
                'selected_by': user,
                'explicit': True,
                'source': source,
                'updated_at': timezone.now(),
            },
        )
    return selection


def clear_weekly_star(user, project_id, module_id, record_id, week_start=None):
    """Remove an explicit weekly selection without deleting any QoR record."""
    project_module = ProjectModule.objects.select_related('module').get(
        project_id=project_id,
        module_id=module_id,
    )
    if not user.is_admin and project_module.owner_id != user.id:
        raise PermissionError('only the release owner may clear the weekly star')
    start, _ = _window(week_start)
    if _snapshot_for_week(project_id, start.date()):
        raise ValueError(
            'weekly review input is frozen; official star changes are not allowed'
        )
    with transaction.atomic():
        selection = WeeklyRunSelection.objects.select_for_update().filter(
            project_id=project_id,
            module_id=module_id,
            week_start=start.date(),
        ).first()
        if not selection:
            return False
        if record_id and selection.record_id != str(record_id):
            raise ValueError('weekly star changed; refresh before clearing it')
        selection.delete()
    return True


def create_weekly_snapshot(user, project_id, week_start=None, description=''):
    """Create the sole authoritative project/week snapshot, or return it."""
    start, _ = _window(week_start)
    alias = _get_project_db_alias(project_id)
    get_project_engine(project_id)
    with transaction.atomic(using=alias):
        existing = ReviewSnapshot.objects.using(alias).filter(
            project_id=project_id,
            snapshot_type='weekly_review',
            week_start=start.date(),
        ).first()
        if existing:
            _read_snapshot(existing)
            return existing, False
        overview = build_weekly_overview(project_id, start.date())
        overview['is_frozen'] = True
        overview['input_mode'] = 'frozen'
        overview['snapshot_schema_version'] = SNAPSHOT_SCHEMA_VERSION
        overview.pop('snapshot', None)
        frozen_data = _canonical_json(overview)
        snapshot, created = ReviewSnapshot.objects.using(alias).get_or_create(
            project_id=project_id,
            snapshot_type='weekly_review',
            week_start=start.date(),
            defaults={
                'schema_version': SNAPSHOT_SCHEMA_VERSION,
                'name': f"Weekly review {overview['week_start']}",
                'description': description,
                'frozen_data': frozen_data,
                'record_count': sum(
                    len(module['candidates'])
                    for group in overview['groups']
                    for module in group['modules']
                ),
                'file_count': 0,
                'checksum': hashlib.sha256(frozen_data.encode('utf-8')).hexdigest(),
                'created_by': user.id,
            },
        )
        if not created:
            _read_snapshot(snapshot)
        return snapshot, created
