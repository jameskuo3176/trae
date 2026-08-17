"""Load, validate and synchronize the YAML review hierarchy."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from django_app.core.models import (
    GlobalModule,
    LegacyModuleMapping,
    Module,
    Project,
    ProjectMember,
    ProjectModule,
    ReviewGroup,
    ReviewGroupModule,
    ReviewHierarchySyncState,
    User,
    normalize_module_name,
)
from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.services.risk_rating import DEFAULT_THRESHOLDS


DEFAULT_CONFIG_PATH = Path(settings.PARENT_DIR) / 'config' / 'review_hierarchy.yaml'
ALLOWED_METRICS = frozenset(DEFAULT_THRESHOLDS)
ALLOWED_THRESHOLD_LEVELS = frozenset(('medium_percent', 'high_percent'))


class HierarchyConfigError(ValueError):
    pass


class HierarchyWriteError(RuntimeError):
    pass


def _config_checksum(data):
    canonical = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str,
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def load_hierarchy(path=None):
    config_path = Path(path or DEFAULT_CONFIG_PATH)
    try:
        raw = config_path.read_text(encoding='utf-8')
        data = yaml.safe_load(raw) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise HierarchyConfigError(f'cannot load hierarchy config: {exc}') from exc
    if not isinstance(data, dict):
        raise HierarchyConfigError('hierarchy config root must be a mapping')
    return data, _config_checksum(data)


def _valid_name(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_thresholds(block, location, errors):
    if not isinstance(block, dict):
        errors.append(f'{location} must be a mapping')
        return
    for metric, levels in block.items():
        if metric not in ALLOWED_METRICS:
            errors.append(
                f'{location}: unsupported metric {metric!r}; '
                f'allowed: {", ".join(sorted(ALLOWED_METRICS))}'
            )
            continue
        if not isinstance(levels, dict):
            errors.append(f'{location}.{metric} must be a mapping')
            continue
        for level, value in levels.items():
            if level not in ALLOWED_THRESHOLD_LEVELS:
                errors.append(
                    f'{location}.{metric}: unsupported level {level!r}; '
                    'allowed: medium_percent, high_percent'
                )
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                errors.append(f'{location}.{metric}.{level} must be a finite number')
            elif value < 0:
                errors.append(f'{location}.{metric}.{level} must be nonnegative')


def get_effective_risk_thresholds(data, project_name=None):
    """Return defaults overlaid by global and then per-project YAML thresholds."""
    effective = copy.deepcopy(DEFAULT_THRESHOLDS)
    global_thresholds = data.get('risk_thresholds') or {}
    if isinstance(global_thresholds, dict):
        for metric, levels in global_thresholds.items():
            if metric in effective and isinstance(levels, dict):
                effective[metric].update(levels)
    projects = data.get('projects') or {}
    project_cfg = projects.get(project_name, {}) if isinstance(projects, dict) else {}
    project_thresholds = (
        project_cfg.get('risk_thresholds') or {}
        if isinstance(project_cfg, dict)
        else {}
    )
    if isinstance(project_thresholds, dict):
        for metric, levels in project_thresholds.items():
            if metric in effective and isinstance(levels, dict):
                effective[metric].update(levels)
    return effective


def _validate_threshold_ordering(effective, location, errors):
    for metric, levels in effective.items():
        medium = levels.get('medium_percent')
        high = levels.get('high_percent')
        if (
            isinstance(medium, (int, float))
            and not isinstance(medium, bool)
            and isinstance(high, (int, float))
            and not isinstance(high, bool)
            and medium > high
        ):
            errors.append(
                f'{location}: {metric} medium_percent must not exceed high_percent'
            )


def validate_hierarchy(data):
    errors = []
    resolved = []
    configured_modules = set()
    version = data.get('version')
    if not _valid_name(version) or len(version) > 64:
        errors.append('version must be a non-empty string of at most 64 characters')
    timezone_name = data.get('timezone')
    if timezone_name is not None and timezone_name != 'Asia/Shanghai':
        errors.append('timezone must be "Asia/Shanghai" when provided')
    projects = data.get('projects', {})
    if not isinstance(projects, dict):
        errors.append('projects must be a mapping')
        projects = {}
    global_thresholds = data.get('risk_thresholds', {})
    _validate_thresholds(global_thresholds, 'risk_thresholds', errors)
    _validate_threshold_ordering(
        get_effective_risk_thresholds(data),
        'risk_thresholds',
        errors,
    )
    for project_name, project_cfg in sorted(projects.items(), key=lambda item: str(item[0])):
        if not _valid_name(project_name):
            errors.append(f'project key {project_name!r} must be a non-empty string')
            continue
        if not isinstance(project_cfg, dict):
            errors.append(f'project {project_name}: value must be a mapping')
            continue
        project = Project.objects.filter(name=project_name).first()
        if not project:
            errors.append(f'project {project_name}: project does not exist')
            continue
        owner_name = project_cfg.get('owner')
        if not _valid_name(owner_name):
            errors.append(f'project {project_name}: owner must be a non-empty username')
            project_owner = None
        else:
            project_owner = User.objects.filter(username=owner_name).first()
        if not project_owner:
            if _valid_name(owner_name):
                errors.append(f'project {project_name}: owner {owner_name!r} does not exist')
        project_thresholds = project_cfg.get('risk_thresholds', {})
        _validate_thresholds(
            project_thresholds,
            f'projects.{project_name}.risk_thresholds',
            errors,
        )
        groups = project_cfg.get('groups', {})
        if not isinstance(groups, dict):
            errors.append(f'project {project_name}: groups must be a mapping')
            continue
        group_rows = []
        for group_name, group_cfg in sorted(groups.items(), key=lambda item: str(item[0])):
            if not _valid_name(group_name):
                errors.append(
                    f'project {project_name}: group key {group_name!r} '
                    'must be a non-empty string'
                )
                continue
            if not isinstance(group_cfg, dict):
                errors.append(f'{project_name}/{group_name}: group must be a mapping')
                continue
            group_owner_name = group_cfg.get('owner')
            if not _valid_name(group_owner_name):
                errors.append(
                    f'{project_name}/{group_name}: owner must be a non-empty username'
                )
                group_owner = None
            else:
                group_owner = User.objects.filter(username=group_owner_name).first()
            if not group_owner:
                if _valid_name(group_owner_name):
                    errors.append(
                        f'{project_name}/{group_name}: owner '
                        f'{group_owner_name!r} does not exist'
                    )
            description = group_cfg.get('description', '')
            if not isinstance(description, str):
                errors.append(f'{project_name}/{group_name}: description must be a string')
            modules = group_cfg.get('modules', {})
            if not isinstance(modules, dict):
                errors.append(f'{project_name}/{group_name}: modules must be a mapping')
                continue
            module_rows = []
            for module_name, module_cfg in sorted(
                modules.items(), key=lambda item: str(item[0]),
            ):
                if not _valid_name(module_name):
                    errors.append(
                        f'{project_name}/{group_name}: module key {module_name!r} '
                        'must be a non-empty string'
                    )
                    continue
                key = (project.id, normalize_module_name(module_name))
                if key in configured_modules:
                    errors.append(
                        f'{project_name}/{module_name}: module belongs to more than one group'
                    )
                    continue
                configured_modules.add(key)
                global_module = GlobalModule.objects.filter(normalized_name=key[1]).first()
                project_module = (
                    ProjectModule.objects.filter(project=project, module=global_module).first()
                    if global_module else None
                )
                if not project_module:
                    errors.append(
                        f'{project_name}/{module_name}: no ProjectModule mapping; '
                        'run migrate_global_modules --execute first'
                    )
                if module_cfg is None:
                    module_cfg = {}
                if not isinstance(module_cfg, dict):
                    errors.append(
                        f'{project_name}/{group_name}/{module_name}: '
                        'module must be a mapping'
                    )
                    continue
                release_owner_name = module_cfg.get('release_owner')
                if not _valid_name(release_owner_name):
                    errors.append(
                        f'{project_name}/{module_name}: release_owner '
                        'must be a non-empty username'
                    )
                    release_owner = None
                else:
                    release_owner = User.objects.filter(
                        username=release_owner_name,
                    ).first()
                if not release_owner:
                    if _valid_name(release_owner_name):
                        errors.append(
                            f'{project_name}/{module_name}: release owner '
                            f'{release_owner_name!r} does not exist'
                        )
                module_rows.append({
                    'project_module': project_module,
                    'release_owner': release_owner,
                })
            group_rows.append({
                'name': group_name,
                'description': description if isinstance(description, str) else '',
                'owner': group_owner,
                'modules': module_rows,
            })
        effective = get_effective_risk_thresholds(data, project_name)
        _validate_threshold_ordering(effective, f'project {project_name}', errors)
        resolved.append({
            'project': project,
            'owner': project_owner,
            'groups': group_rows,
            'thresholds': effective,
        })
    return errors, resolved


def build_sync_plan(data, config_version, resolved=None):
    """Build a deterministic, read-only reconciliation plan."""
    if resolved is None:
        errors, resolved = validate_hierarchy(data)
        if errors:
            raise HierarchyConfigError('\n'.join(errors))
    change_counts = {
        'project_owner_updates': 0,
        'group_creates': 0,
        'group_updates': 0,
        'group_deletes': 0,
        'module_owner_updates': 0,
        'legacy_owner_updates': 0,
        'module_link_creates': 0,
        'module_link_moves': 0,
        'module_link_deletes': 0,
    }
    desired_counts = {
        'projects': len(resolved),
        'groups': sum(len(row['groups']) for row in resolved),
        'modules': sum(
            len(group['modules'])
            for row in resolved
            for group in row['groups']
        ),
    }
    project_rows = []
    for row in resolved:
        project = row['project']
        owner = row['owner']
        current_owner_ids = set(ProjectMember.objects.filter(
            project=project, role='owner',
        ).values_list('user_id', flat=True))
        owner_membership = ProjectMember.objects.filter(
            project=project, user=owner,
        ).first()
        if current_owner_ids != {owner.id} or not owner_membership:
            change_counts['project_owner_updates'] += 1
        existing_groups = {
            group.name: group
            for group in ReviewGroup.objects.filter(project=project)
        }
        desired_group_names = {group['name'] for group in row['groups']}
        stale_groups = sorted(set(existing_groups) - desired_group_names)
        change_counts['group_deletes'] += len(stale_groups)
        existing_links = {
            link.project_module_id: link
            for link in ReviewGroupModule.objects.filter(
                group__project=project,
            ).select_related('group')
        }
        desired_module_ids = set()
        groups_payload = []
        for group_row in row['groups']:
            group = existing_groups.get(group_row['name'])
            if group is None:
                change_counts['group_creates'] += 1
            elif (
                group.owner_id != group_row['owner'].id
                or group.description != group_row['description']
                or group.config_version != config_version
            ):
                change_counts['group_updates'] += 1
            modules_payload = []
            for module_row in group_row['modules']:
                project_module = module_row['project_module']
                release_owner = module_row['release_owner']
                desired_module_ids.add(project_module.id)
                if project_module.owner_id != release_owner.id:
                    change_counts['module_owner_updates'] += 1
                change_counts['legacy_owner_updates'] += _legacy_owner_mismatch_count(
                    project, project_module, release_owner,
                )
                link = existing_links.get(project_module.id)
                if link is None:
                    change_counts['module_link_creates'] += 1
                elif link.group.name != group_row['name']:
                    change_counts['module_link_moves'] += 1
                modules_payload.append({
                    'name': project_module.module.name,
                    'release_owner': release_owner.username,
                })
            groups_payload.append({
                'name': group_row['name'],
                'owner': group_row['owner'].username,
                'description': group_row['description'],
                'modules': modules_payload,
            })
        stale_link_ids = set(existing_links) - desired_module_ids
        stale_link_ids -= {
            link.project_module_id
            for link in existing_links.values()
            if link.group.name in stale_groups
        }
        change_counts['module_link_deletes'] += len(stale_link_ids)
        project_rows.append({
            'id': project.id,
            'name': project.name,
            'status': project.status,
            'owner': owner.username,
            'groups': groups_payload,
            'effective_thresholds': row['thresholds'],
        })
    return {
        'config_version': config_version,
        'desired': desired_counts,
        'changes': change_counts,
        'total_changes': sum(change_counts.values()),
        'projects': project_rows,
    }


def _legacy_owner_context(project, project_module):
    legacy_ids = list(LegacyModuleMapping.objects.filter(
        project=project,
        module=project_module.module,
    ).values_list('legacy_module_id', flat=True))
    if not legacy_ids:
        return None, []
    get_project_engine(project.id)
    return _get_project_db_alias(project.id), legacy_ids


def _legacy_owner_mismatch_count(project, project_module, release_owner):
    alias, legacy_ids = _legacy_owner_context(project, project_module)
    if not legacy_ids:
        return 0
    return Module.objects.using(alias).filter(id__in=legacy_ids).exclude(
        owner_id=release_owner.id,
    ).count()


def _sync_legacy_owner(project, project_module, release_owner):
    alias, legacy_ids = _legacy_owner_context(project, project_module)
    if not legacy_ids:
        return
    with transaction.atomic(using=alias):
        Module.objects.using(alias).filter(id__in=legacy_ids).exclude(
            owner_id=release_owner.id,
        ).update(owner_id=release_owner.id)


@transaction.atomic
def sync_hierarchy(data, config_version, config_path=None):
    """Validate, diff and atomically reconcile projects included in YAML."""
    errors, resolved = validate_hierarchy(data)
    if errors:
        raise HierarchyConfigError('\n'.join(errors))
    plan = build_sync_plan(data, config_version, resolved)
    now = timezone.now()
    for row in resolved:
        project = row['project']
        project_owner = row['owner']
        ProjectMember.objects.filter(
            project=project, role='owner',
        ).exclude(user=project_owner).update(role='editor')
        membership = ProjectMember.objects.filter(
            project=project, user=project_owner,
        ).first()
        if membership is None:
            ProjectMember.objects.create(
                project=project, user=project_owner, role='owner',
            )
        elif membership.role != 'owner':
            membership.role = 'owner'
            membership.save(update_fields=['role'])
        keep_group_ids = []
        keep_project_module_ids = []
        for group_row in row['groups']:
            group = ReviewGroup.objects.filter(
                project=project, name=group_row['name'],
            ).first()
            if group is None:
                group = ReviewGroup.objects.create(
                    project=project,
                    name=group_row['name'],
                    owner=group_row['owner'],
                    description=group_row['description'],
                    config_version=config_version,
                    updated_at=now,
                )
            else:
                changed_fields = []
                desired_fields = {
                    'owner_id': group_row['owner'].id,
                    'description': group_row['description'],
                    'config_version': config_version,
                }
                for field, value in desired_fields.items():
                    if getattr(group, field) != value:
                        setattr(group, field, value)
                        changed_fields.append(field)
                if changed_fields:
                    group.updated_at = now
                    group.save(update_fields=changed_fields + ['updated_at'])
            keep_group_ids.append(group.id)
            for module_row in group_row['modules']:
                project_module = module_row['project_module']
                release_owner = module_row['release_owner']
                keep_project_module_ids.append(project_module.id)
                if project_module.owner_id != release_owner.id:
                    project_module.owner_id = release_owner.id
                    project_module.save(update_fields=['owner_id'])
                _sync_legacy_owner(project, project_module, release_owner)
                link = ReviewGroupModule.objects.filter(
                    project_module=project_module,
                ).first()
                if link is None:
                    ReviewGroupModule.objects.create(
                        project_module=project_module, group=group,
                    )
                elif link.group_id != group.id:
                    link.group = group
                    link.save(update_fields=['group'])
        ReviewGroupModule.objects.filter(
            group__project=project,
        ).exclude(project_module_id__in=keep_project_module_ids).delete()
        ReviewGroup.objects.filter(project=project).exclude(
            id__in=keep_group_ids,
        ).delete()
    state = ReviewHierarchySyncState.objects.filter(singleton=1).first()
    normalized_path = str(Path(config_path or DEFAULT_CONFIG_PATH).resolve())
    state_changed = (
        state is None
        or state.config_path != normalized_path
        or state.config_version != data['version']
        or state.config_checksum != config_version
        or plan['total_changes'] > 0
    )
    if state_changed:
        ReviewHierarchySyncState.objects.update_or_create(
            singleton=1,
            defaults={
                'config_path': normalized_path,
                'config_version': data['version'],
                'config_checksum': config_version,
                'applied_at': now,
                'summary': {
                    'desired': plan['desired'],
                    'changes': plan['changes'],
                    'total_changes': plan['total_changes'],
                },
            },
        )
    return plan


def _stage_hierarchy_yaml(path, data):
    """Validate serialization and fsync a replacement in the same directory."""
    try:
        rendered = yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        round_tripped = yaml.safe_load(rendered)
    except yaml.YAMLError as exc:
        raise HierarchyWriteError(f'cannot serialize hierarchy config: {exc}') from exc
    if round_tripped != data:
        raise HierarchyWriteError('serialized hierarchy config failed round-trip validation')

    fd = None
    staged_path = None
    try:
        fd, staged_name = tempfile.mkstemp(
            prefix=f'.{path.name}.',
            suffix='.tmp',
            dir=str(path.parent),
        )
        staged_path = Path(staged_name)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            fd = None
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(staged_path, path.stat().st_mode)
        return staged_path
    except OSError as exc:
        if staged_path is not None and staged_path.exists():
            staged_path.unlink()
        raise HierarchyWriteError(f'cannot stage hierarchy config: {exc}') from exc
    finally:
        if fd is not None:
            os.close(fd)


def _atomic_restore(path, content):
    fd, staged_name = tempfile.mkstemp(
        prefix=f'.{path.name}.restore.',
        suffix='.tmp',
        dir=str(path.parent),
    )
    staged_path = Path(staged_name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(staged_path, path.stat().st_mode)
        os.replace(staged_path, path)
    finally:
        if staged_path.exists():
            staged_path.unlink()


def update_module_release_owner(
    project_name,
    group_name,
    module_name,
    owner_id,
    *,
    expected_checksum=None,
    config_path=None,
):
    """Update one canonical module owner and its YAML source as one guarded unit."""
    if not all(_valid_name(value) for value in (project_name, group_name, module_name)):
        raise HierarchyConfigError('project, group and module names are required')
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError) as exc:
        raise HierarchyConfigError('owner_id must be an integer') from exc

    path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
    try:
        original_bytes = path.read_bytes()
    except OSError as exc:
        raise HierarchyWriteError(f'cannot read hierarchy config for update: {exc}') from exc
    data, current_checksum = load_hierarchy(path)
    if not _valid_name(expected_checksum):
        raise HierarchyConfigError(
            'config_checksum is required; refresh hierarchy status and try again'
        )
    if expected_checksum != current_checksum:
        raise HierarchyConfigError(
            'hierarchy config changed since it was loaded; refresh and try again'
        )

    owner = User.objects.filter(
        pk=owner_id,
        role=User.ROLE_OWNER,
        is_active=True,
    ).first()
    if owner is None:
        raise HierarchyConfigError('selected release owner is not an active owner account')

    project_cfg = (data.get('projects') or {}).get(project_name)
    if not isinstance(project_cfg, dict):
        raise HierarchyConfigError(f'project {project_name!r} is not configured')
    group_cfg = (project_cfg.get('groups') or {}).get(group_name)
    if not isinstance(group_cfg, dict):
        raise HierarchyConfigError(
            f'group {group_name!r} is not configured under project {project_name!r}'
        )
    module_cfg = (group_cfg.get('modules') or {}).get(module_name)
    if not isinstance(module_cfg, dict):
        raise HierarchyConfigError(
            f'module {module_name!r} is not configured under '
            f'{project_name!r}/{group_name!r}'
        )

    project_module = ProjectModule.objects.filter(
        project__name=project_name,
        project__status__in=('active', 'locked'),
        module__normalized_name=normalize_module_name(module_name),
        review_group_link__group__name=group_name,
    ).first()
    if project_module is None:
        raise HierarchyConfigError(
            'module identity does not match the configured database hierarchy'
        )

    updated_data = copy.deepcopy(data)
    updated_data['projects'][project_name]['groups'][group_name]['modules'][module_name][
        'release_owner'
    ] = owner.username
    status_data, _excluded = _status_hierarchy(updated_data)
    errors, resolved = validate_hierarchy(status_data)
    if errors:
        raise HierarchyConfigError('\n'.join(errors))
    updated_checksum = _config_checksum(updated_data)
    staged_path = _stage_hierarchy_yaml(path, updated_data)
    yaml_replaced = False

    try:
        with transaction.atomic():
            locked_module = ProjectModule.objects.select_for_update().filter(
                pk=project_module.pk,
            ).first()
            if locked_module is None:
                raise HierarchyConfigError(
                    'module mapping changed during the update; refresh and try again'
                )
            locked_module.owner_id = owner.id
            locked_module.save(update_fields=['owner_id'])
            now = timezone.now()
            for project_row in resolved:
                for group_row in project_row['groups']:
                    ReviewGroup.objects.filter(
                        project=project_row['project'],
                        name=group_row['name'],
                    ).exclude(config_version=updated_checksum).update(
                        config_version=updated_checksum,
                        updated_at=now,
                    )

            try:
                latest_data, latest_checksum = load_hierarchy(path)
            except HierarchyConfigError as exc:
                raise HierarchyWriteError(
                    f'cannot verify hierarchy config before replacement: {exc}'
                ) from exc
            if latest_checksum != current_checksum or latest_data != data:
                raise HierarchyConfigError(
                    'hierarchy config changed during the update; refresh and try again'
                )
            os.replace(staged_path, path)
            yaml_replaced = True

            post_plan = build_sync_plan(status_data, updated_checksum, resolved)
            if post_plan['total_changes'] == 0:
                ReviewHierarchySyncState.objects.update_or_create(
                    singleton=1,
                    defaults={
                        'config_path': str(path),
                        'config_version': updated_data['version'],
                        'config_checksum': updated_checksum,
                        'applied_at': now,
                        'summary': {
                            'desired': post_plan['desired'],
                            'changes': {'module_owner_updates': 1},
                            'total_changes': 1,
                        },
                    },
                )
    except Exception as exc:
        if yaml_replaced:
            try:
                _atomic_restore(path, original_bytes)
            except OSError as restore_exc:
                raise HierarchyWriteError(
                    'database update was rolled back, but restoring the hierarchy YAML '
                    f'also failed: {restore_exc}'
                ) from exc
        if isinstance(exc, (HierarchyConfigError, HierarchyWriteError)):
            raise
        if isinstance(exc, OSError):
            raise HierarchyWriteError(f'cannot replace hierarchy config: {exc}') from exc
        raise
    finally:
        if staged_path.exists():
            staged_path.unlink()

    return {
        'project': project_name,
        'group': group_name,
        'module': module_name,
        'release_owner': owner.username,
        'release_owner_id': owner.id,
        'config_checksum': updated_checksum,
    }


def _status_hierarchy(data):
    """Exclude lifecycle-inactive YAML projects without mutating the source data."""
    visible = copy.deepcopy(data)
    configured_projects = data.get('projects')
    if not isinstance(configured_projects, dict):
        return visible, []

    project_names = [
        name for name in configured_projects
        if _valid_name(name)
    ]
    projects_by_name = {}
    for project in Project.objects.filter(name__in=project_names).order_by('id'):
        projects_by_name.setdefault(project.name, project)

    visible_projects = {}
    excluded = []
    for name, config in configured_projects.items():
        project = projects_by_name.get(name)
        if project is None:
            excluded.append({
                'name': name,
                'status': 'deleted',
                'reason': 'project no longer exists',
            })
        elif project.status not in ('active', 'locked'):
            excluded.append({
                'name': name,
                'status': project.status,
                'reason': 'project is offline',
            })
        else:
            visible_projects[name] = config
    visible['projects'] = visible_projects
    excluded.sort(key=lambda row: (str(row['name']).casefold(), str(row['name'])))
    return visible, excluded


def hierarchy_status(config_path=None):
    """Return read-only config validation, DB diff and last-apply status."""
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    state = ReviewHierarchySyncState.objects.filter(singleton=1).first()
    result = {
        'config_path': str(path.resolve()),
        'config_version': None,
        'config_checksum': None,
        'validation': {'valid': False, 'errors': []},
        'last_applied': (
            {
                'config_path': state.config_path,
                'config_version': state.config_version,
                'config_checksum': state.config_checksum,
                'applied_at': state.applied_at.isoformat() if state.applied_at else None,
                'summary': state.summary,
            }
            if state else None
        ),
        'current_db_diff': None,
        'projects': [],
        'excluded_projects': [],
    }
    try:
        data, config_version = load_hierarchy(path)
        result['config_version'] = data.get('version')
        result['config_checksum'] = config_version
        status_data, excluded = _status_hierarchy(data)
        result['excluded_projects'] = excluded
        errors, resolved = validate_hierarchy(status_data)
        result['validation'] = {'valid': not errors, 'errors': errors}
        if not errors:
            plan = build_sync_plan(status_data, config_version, resolved)
            result['current_db_diff'] = {
                'desired': plan['desired'],
                'changes': plan['changes'],
                'total_changes': plan['total_changes'],
                'in_sync': plan['total_changes'] == 0,
            }
            result['projects'] = sorted(
                plan['projects'],
                key=lambda row: (
                    1 if row['status'] == 'locked' else 0,
                    row['name'].casefold(),
                    row['name'],
                    row['id'],
                ),
            )
    except HierarchyConfigError as exc:
        result['validation']['errors'] = [str(exc)]
    return result
