"""API 视图模块

QoR Recorder 所有 API 端点视图函数。
匹配 urls.py 中定义的路由名称。
"""
import csv as _csv
import io as _io
import json
import logging
import os
import platform
import re
import subprocess
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import (
    HttpResponse, Http404, HttpResponseForbidden, JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from django.contrib.auth import update_session_auth_hash, login, logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_app.core.decorators import login_required, api_auth_required
from django_app.core.security import generate_csrf_token
from django_app.core.db_routing import (
    set_current_project_id,
    _get_project_db_alias,
    get_project_engine,
    list_all_project_dbs,
    _resolve_project_ids as db_resolve_project_ids,
    query_records_by_projects as db_query_records_by_projects,
    _find_qor_record_project as db_find_qor_record_project,
    _find_module_project_id as db_find_module_project_id,
)
from django_app.core.models import (
    User, Project, ProjectMember, Module, QorRecord,
    ViolationPath, RunNote, DataSnapshot, BackupRecord,
    DataLock, ApiKey, AlertRule, AlertEvent,
    UserDashboard, DashboardGroup,
    TileReview, GroupReview, SubsystemReview,
    ReviewSnapshot, ReviewFile,
    ProjectModule, ReviewGroup, ReviewGroupModule, LegacyModuleMapping,
    WeeklyRunSelection,
    REVIEW_STATUS_DRAFT, REVIEW_STATUS_SUBMITTED,
    REVIEW_STATUS_APPROVED, REVIEW_STATUS_REJECTED,
)
from django_app.services import qor_import, json_upload, backup_service
from django_app.services.weekly_review import (
    create_weekly_snapshot,
    get_authoritative_weekly_snapshot,
    get_weekly_review_input,
    clear_weekly_star,
    select_weekly_star,
    SnapshotIntegrityError,
)
from django_app.services.review_hierarchy import (
    HierarchyConfigError,
    HierarchyWriteError,
    hierarchy_status,
    update_module_release_owner,
)
from django_app.services.timing_normalization import normalize_timing_sections
from django_app.services.risk_rating import shanghai_week_window
from django_app.services.record_risk import assess_module_history, can_edit_risk


logger = logging.getLogger(__name__)


# =========================================================================
# 辅助函数
# =========================================================================

def _get_project_db(project_id):
    """获取项目数据库 Django 连接别名"""
    return _get_project_db_alias(project_id)


def _resolve_project_ids(project_ids_str=''):
    """Resolve project IDs while consistently excluding offline projects."""
    requested = db_resolve_project_ids(project_ids_str)
    visible = set(
        Project.objects.exclude(status='hidden').values_list('id', flat=True)
    )
    return [project_id for project_id in requested if project_id in visible]


def _find_qor_record_project(record_id):
    """Locate a record only within the canonical non-hidden Dashboard scope."""
    project_id = db_find_qor_record_project(record_id)
    if project_id is None:
        return None
    if not Project.objects.exclude(status='hidden').filter(pk=project_id).exists():
        return None
    return project_id


def _find_qor_record_projects(record_id):
    """Return every project containing a local record ID."""
    project_ids = []
    for item in list_all_project_dbs():
        project_id = item['project_id']
        try:
            get_project_engine(project_id)
            if QorRecord.objects.using(_get_project_db(project_id)).filter(pk=record_id).exists():
                project_ids.append(project_id)
        except Exception:
            continue
    return project_ids


def _find_module_project_id(module_id):
    """跨项目库查找 Module 所在 project_id"""
    return db_find_module_project_id(module_id)


def _project_module_record_counts(project_id):
    """在项目库上下文内统计 module/record 数量"""
    db_name = _get_project_db(project_id)
    try:
        get_project_engine(project_id)
        module_count = Module.objects.using(db_name).filter(project_id=project_id).count()
        record_count = QorRecord.objects.using(db_name).filter(
            module__project_id=project_id,
        ).count()
        return module_count, record_count, True
    except Exception:
        return 0, 0, False


def _project_not_writable_response(project):
    """Reject writes while still allowing historical reads of locked projects."""
    return JsonResponse({
        'error': f'项目当前不可写 (status={project.status})',
        'status': project.status,
        'is_writable': False,
    }, status=403)


def _require_writable_project(project):
    if not getattr(project, 'is_writable', False):
        return _project_not_writable_response(project)
    return None


def query_records_by_projects(
    proj_id_list=None, module_ids_str='', versions_str='',
    owner_id=None, release_only=False, dir_prefix=None,
    order_desc=True, limit=5000,
):
    """按项目迭代查询 QorRecord, 跨库安全"""
    return db_query_records_by_projects(
        proj_id_list=proj_id_list,
        module_ids_str=module_ids_str,
        versions_str=versions_str,
        owner_id=owner_id,
        release_only=release_only,
        dir_prefix=dir_prefix,
        order_desc=order_desc,
        limit=limit,
    )


def parse_full_dir(full_dir):
    """从 full_dir 路径中解析 base_dir / sub_path / run_name"""
    if not full_dir:
        return {'base_dir': '', 'sub_path': '', 'run_name': '', 'level': 0}
    parts = [p.strip() for p in str(full_dir).replace('\\', '/').split('/') if p.strip()]
    if not parts:
        return {'base_dir': '', 'sub_path': '', 'run_name': '', 'level': 0}
    if len(parts) == 1:
        return {'base_dir': '', 'sub_path': '', 'run_name': parts[0], 'level': 1}
    if len(parts) == 2:
        return {'base_dir': parts[0], 'sub_path': '', 'run_name': parts[1], 'level': 2}
    return {
        'base_dir': parts[0],
        'sub_path': '/'.join(parts[1:-1]),
        'run_name': parts[-1],
        'level': len(parts),
    }


def _display_minute(value):
    if not value:
        return None
    try:
        return timezone.localtime(value).isoformat(timespec='minutes')
    except (ValueError, TypeError):
        return value.isoformat(timespec='minutes')


def _serialize_qor_records(records, user=None):
    """Serialize cross-database rows without losing project/uploader context."""
    records = list(records)
    rows = []
    owner_ids = {r.owner_id for r in records if r.owner_id}
    users = {
        user.id: user
        for user in User.objects.filter(id__in=owner_ids)
    }
    project_ids = {
        getattr(r, '_qor_project_id', None)
        or getattr(getattr(r, 'module', None), 'project_id', None)
        for r in records
    }
    projects = {
        project.id: project
        for project in Project.objects.filter(id__in=[pid for pid in project_ids if pid])
    }
    record_context = {}
    mapping_query = Q(pk__in=[])
    for record in records:
        project_id = (
            getattr(record, '_qor_project_id', None)
            or getattr(getattr(record, 'module', None), 'project_id', None)
        )
        week_start = (
            shanghai_week_window(record.recorded_at)[0].date()
            if record.recorded_at else None
        )
        record_context[id(record)] = (project_id, week_start)
        if project_id and record.module_id:
            mapping_query |= Q(
                project_id=project_id,
                legacy_module_id=record.module_id,
            )
    identity_map = {
        (mapping.project_id, mapping.legacy_module_id): mapping.module_id
        for mapping in LegacyModuleMapping.objects.filter(mapping_query)
    }
    selection_keys = {
        (project_id, identity_map.get((project_id, record.module_id)), week_start)
        for record in records
        for project_id, week_start in [record_context[id(record)]]
        if project_id and week_start and identity_map.get((project_id, record.module_id))
    }
    selections = {
        (selection.project_id, selection.module_id, selection.week_start): selection
        for selection in WeeklyRunSelection.objects.filter(
            project_id__in={key[0] for key in selection_keys},
            module_id__in={key[1] for key in selection_keys},
            week_start__in={key[2] for key in selection_keys},
        )
    } if selection_keys else {}
    owner_map = {
        (row.project_id, row.module_id): row.owner_id
        for row in ProjectModule.objects.filter(
            project_id__in={key[0] for key in selection_keys},
            module_id__in={key[1] for key in selection_keys},
        )
    } if selection_keys else {}
    for record in records:
        value = record.to_dict()
        project_id, week_start = record_context[id(record)]
        value['project_id'] = project_id
        value['project_name'] = projects[project_id].name if project_id in projects else None
        if not value.get('module_name'):
            value['module_name'] = LegacyModuleMapping.objects.filter(
                project_id=project_id,
                legacy_module_id=record.module_id,
            ).values_list('legacy_name', flat=True).first() or f'#{record.module_id}'
        owner = users.get(record.owner_id)
        value['uploader_id'] = record.owner_id
        value['uploader_username'] = owner.username if owner else None
        value['uploader_display_name'] = owner.display_name if owner else None
        # Compatibility for existing clients while the label changes to uploader.
        value['owner_username'] = owner.username if owner else None
        value['release_sort_at'] = (
            record.released_at or record.recorded_at
        ).isoformat() if (record.released_at or record.recorded_at) else None
        value['recorded_at_display'] = _display_minute(record.recorded_at)
        value['released_at_display'] = _display_minute(record.released_at)
        value['release_sort_at_display'] = _display_minute(
            record.released_at or record.recorded_at
        )
        value['can_manage'] = bool(
            user and not user.is_viewer
            and (user.is_admin or record.module.can_be_managed_by(user))
        )
        value['can_edit_description'] = bool(user and user.is_admin)
        global_module_id = identity_map.get((project_id, record.module_id))
        selection = selections.get((project_id, global_module_id, week_start))
        value['global_module_id'] = global_module_id
        value['review_week_start'] = week_start.isoformat() if week_start else None
        value['review_star'] = bool(
            selection and selection.record_id == str(record.id)
        )
        value['review_star_selected_by'] = (
            selection.selected_by_id if value['review_star'] else None
        )
        value['can_select_review_star'] = bool(
            user
            and not user.is_viewer
            and global_module_id
            and week_start
            and (
                user.is_admin
                or owner_map.get((project_id, global_module_id)) == user.id
            )
        )
        rows.append(value)
    return rows


# 数字电路 QoR 评选指标的方向
QOR_METRIC_DIRECTION = {
    'area_total': 'min', 'area_combinational': 'min', 'area_sequential': 'min',
    'area_black_box': 'min', 'area_macro': 'min', 'cell_count': 'min',
    'instance_count': 'min', 'net_count': 'min', 'sequential_cell_count': 'min',
    'wns_setup': 'min', 'tns_setup': 'min', 'nvp_setup': 'min',
    'wns_hold': 'min', 'tns_hold': 'min', 'nvp_hold': 'min',
    'power_internal': 'min', 'power_switching': 'min', 'power_leakage': 'min',
    'power_total': 'min',
    'mbb_ratio': 'max', 'clock_gating_ratio': 'max',
    'utilization': 'mid',
    'congestion': 'min', 'congestion_h': 'min', 'congestion_v': 'min', 'congestion_b': 'min',
}


# =========================================================================
# 页面视图
# =========================================================================

@login_required
def tools_source_files_check_page(request):
    """渲染 source_files_check 页面"""
    return render(request, 'source_files_check.html', {
        'csrf_token': generate_csrf_token(request),
    })


# =========================================================================
# QoR API - 项目与模块
# =========================================================================

@login_required
def api_get_projects(request):
    """Return the role-independent Dashboard project scope."""
    try:
        query = Project.objects.exclude(status='hidden')
        projects = query.order_by('name')

        result = []
        for p in projects:
            db_name = _get_project_db(p.id)
            try:
                get_project_engine(p.id)
                modules = Module.objects.using(db_name).filter(project_id=p.id).order_by('name')
                module_list = []
                for m in modules:
                    record_count = QorRecord.objects.using(db_name).filter(module_id=m.id).count()
                    module_list.append({
                        'id': m.id, 'name': m.name, 'record_count': record_count,
                    })
            except Exception:
                module_list = []

            result.append({
                'id': p.id,
                'name': p.name,
                'description': p.description,
                'status': p.status,
                'is_writable': p.is_writable,
                'locked_at': p.locked_at.isoformat() if p.locked_at else None,
                'locked_by_name': p.locked_by.username if p.locked_by else None,
                'lock_reason': p.lock_reason,
                'module_count': len(module_list),
                'modules': module_list,
            })
        return JsonResponse(result, safe=False)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse([], safe=False)


@login_required
def api_get_modules(request, project_id):
    """获取指定项目的模块列表"""
    get_object_or_404(Project.objects.exclude(status='hidden'), pk=project_id)
    db_name = _get_project_db(project_id)
    try:
        get_project_engine(project_id)
        modules = Module.objects.using(db_name).filter(
            project_id=project_id,
        ).order_by('name')
        result = []
        for m in modules:
            record_count = QorRecord.objects.using(db_name).filter(module_id=m.id).count()
            result.append({
                'id': m.id, 'name': m.name, 'record_count': record_count,
            })
        return JsonResponse(result, safe=False)
    except Exception:
        return JsonResponse([], safe=False)


@login_required
def api_get_module_records(request, project_id, module_id):
    """获取指定模块下的记录摘要"""
    get_object_or_404(Project.objects.exclude(status='hidden'), pk=project_id)
    db_name = _get_project_db(project_id)
    try:
        get_project_engine(project_id)
        get_object_or_404(
            Module.objects.using(db_name),
            pk=module_id, project_id=project_id,
        )
        q = QorRecord.objects.using(db_name).filter(module_id=module_id)
        records = q.order_by('version', '-recorded_at')[:500]
        result = []
        for r in records:
            result.append({
                'id': r.id,
                'version': r.version or 'v1',
                'tag': r._compute_tag(),
                'full_dir': r.full_dir or '',
                'recorded_at': r.recorded_at.isoformat() if r.recorded_at else None,
                'is_released': bool(r.is_released),
                'owner_id': r.owner_id,
            })
        return JsonResponse(result, safe=False)
    except Http404:
        raise
    except Exception:
        return JsonResponse([], safe=False)


# =========================================================================
# QoR API - 数据查询
# =========================================================================

@login_required
def api_get_qor_data(request):
    """查询 QoR 数据"""
    try:
        project_ids = request.GET.get('project_ids', '')
        module_ids = request.GET.get('module_ids', '')
        versions = request.GET.get('versions', '')
        owner_id = request.GET.get('owner_id', '').strip()
        owner_username = request.GET.get('owner_username', '').strip()
        dir_prefix = request.GET.get('dir_prefix', '').strip() or None
        paginated = 'page' in request.GET or 'page_size' in request.GET
        try:
            page = max(1, int(request.GET.get('page', 1)))
            page_size = min(200, max(1, int(request.GET.get('page_size', 50))))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'page 和 page_size 必须为整数'}, status=400)

        owner_user_id = None
        if owner_id and owner_id.isdigit():
            owner_user_id = int(owner_id)
        elif owner_username:
            try:
                owner_user = User.objects.get(username=owner_username)
                owner_user_id = owner_user.id
            except User.DoesNotExist:
                return JsonResponse([], safe=False)

        proj_id_list = _resolve_project_ids(project_ids)
        records = query_records_by_projects(
            proj_id_list=proj_id_list,
            module_ids_str=module_ids,
            versions_str=versions,
            owner_id=owner_user_id,
            release_only=False,
            dir_prefix=dir_prefix,
            order_desc=True,
            limit=5000,
        )
        rows = _serialize_qor_records(records, request.user)
        if not paginated:
            return JsonResponse(rows, safe=False)
        total = len(rows)
        start = (page - 1) * page_size
        return JsonResponse({
            'records': rows[start:start + page_size],
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'pages': (total + page_size - 1) // page_size,
            },
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse([], safe=False)


@login_required
def api_qor_record_detail(request, record_id):
    """单条 QoR 记录详情 + 同 module+version 横向对比"""
    explicit_pid = request.GET.get('project_id', '').strip()
    pid = int(explicit_pid) if explicit_pid.isdigit() else _find_qor_record_project(record_id)
    if pid is None:
        return JsonResponse({'error': '记录不存在'}, status=404)
    if not Project.objects.exclude(status='hidden').filter(pk=pid).exists():
        return JsonResponse({'error': '记录不存在'}, status=404)
    db_name = _get_project_db(pid)
    try:
        get_project_engine(pid)
        rec = QorRecord.objects.using(db_name).select_related('module').get(pk=record_id)
    except QorRecord.DoesNotExist:
        return JsonResponse({'error': '记录不存在'}, status=404)

    if not request.user.is_admin and not request.user.is_owner and not request.user.is_viewer:
        member = ProjectMember.objects.filter(
            project_id=rec.module.project_id, user=request.user,
        ).first()
        if not member:
            return JsonResponse({'error': 'forbidden'}, status=403)

    siblings = QorRecord.objects.using(db_name).filter(
        module_id=rec.module_id, version=rec.version,
    ).order_by('recorded_at')
    sibling_summaries = []
    for s in siblings:
        sibling_summaries.append({
            'id': s.id,
            'full_dir': s.full_dir or '',
            'version': s.version,
            'area_total': s.area_total,
            'wns_setup': s.wns_setup,
            'tns_setup': s.tns_setup,
            'nvp_setup': s.nvp_setup,
            'power_total': s.power_total,
            'cell_count': s.cell_count,
            'mbb_ratio': s.mbb_ratio,
            'clock_gating_ratio': s.clock_gating_ratio,
            'recorded_at': s.recorded_at.isoformat() if s.recorded_at else None,
        })

    rec._qor_project_id = pid
    serialized_record = _serialize_qor_records([rec], request.user)[0]
    serialized_record['timing_sections'] = normalize_timing_sections(serialized_record)
    return JsonResponse({
        'record': serialized_record,
        'siblings': sibling_summaries,
        'sibling_count': len(sibling_summaries),
    })


@login_required
def api_qor_aggregate(request):
    """按维度聚合 QoR 记录"""
    project_ids = request.GET.get('project_ids', '')
    module_ids = request.GET.get('module_ids', '')
    versions = request.GET.get('versions', '')
    group_by = request.GET.get('group_by', 'run').lower()
    single_metric = request.GET.get('metric', '').strip()
    dir_prefix = request.GET.get('dir_prefix', '').strip() or None

    if group_by not in ('base_dir', 'module', 'run'):
        return JsonResponse({'error': 'group_by must be base_dir|module|run'}, status=400)

    proj_id_list = _resolve_project_ids(project_ids)

    mod_id_filter = None
    if module_ids:
        mod_id_filter = set(int(x) for x in module_ids.split(',') if x.strip().isdigit())
    ver_filter = None
    if versions:
        ver_filter = set(v.strip() for v in versions.split(',') if v.strip())

    records = []
    for pid in proj_id_list:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            q = QorRecord.objects.using(db_name).select_related('module')
            if mod_id_filter:
                q = q.filter(module_id__in=mod_id_filter)
            if ver_filter:
                q = q.filter(version__in=ver_filter)
            if dir_prefix:
                q = q.filter(full_dir__startswith=dir_prefix)
            for r in q.order_by('recorded_at')[:10000]:
                mod_name = r.module.name if r.module else ''
                records.append({
                    'record': r,
                    'module_id': r.module_id,
                    'module_name': mod_name,
                })
        except Exception:
            continue

    groups = {}
    for item in records:
        r = item['record']
        d = parse_full_dir(r.full_dir or '')
        if group_by == 'base_dir':
            key = d['base_dir'] or '(root)'
        elif group_by == 'module':
            key = item['module_name'] or f'#{r.module_id}'
        else:
            key = (r.full_dir or '').strip() or f'#{r.id}'
        groups.setdefault(key, []).append((r, d, item))

    metric_fields = [
        'area_total', 'area_combinational', 'area_sequential',
        'wns_setup', 'tns_setup', 'nvp_setup',
        'wns_hold', 'tns_hold', 'nvp_hold',
        'power_total', 'cell_count', 'utilization',
        'congestion', 'congestion_h', 'congestion_v', 'congestion_b',
    ]

    def _median(vals):
        s = sorted(vals)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2

    result = []
    for key, items in groups.items():
        recs = [x[0] for x in items]
        first_d = items[0][1]
        first_item = items[0][2]
        agg = {
            'label': key,
            'count': len(recs),
            'base_dir': first_d.get('base_dir', '') if group_by == 'run' else key if group_by == 'base_dir' else '',
            'run_name': first_d.get('run_name', '') if group_by == 'run' else '',
            'module_name': first_item['module_name'] if group_by in ('run', 'base_dir') else key,
        }
        for f in metric_fields:
            vals = [getattr(r, f) for r in recs if getattr(r, f) is not None]
            if vals:
                agg[f] = {
                    'avg': sum(vals) / len(vals),
                    'min': min(vals),
                    'max': max(vals),
                    'median': _median(vals),
                    'count': len(vals),
                }
        result.append(agg)

    if single_metric:
        result = [{
            'label': r['label'], 'count': r['count'],
            'base_dir': r.get('base_dir', ''), 'run_name': r.get('run_name', ''),
            'module_name': r.get('module_name', ''),
            single_metric: r.get(single_metric),
        } for r in result]

    return JsonResponse({
        'group_by': group_by,
        'total_records': len(records),
        'group_count': len(result),
        'items': result,
        'metric_directions': QOR_METRIC_DIRECTION,
    })


@login_required
def api_qor_parse_path(request):
    """解析 full_dir 路径结构"""
    full_dir = request.GET.get('full_dir', '')
    return JsonResponse(parse_full_dir(full_dir))


@login_required
def api_dir_modules(request):
    """根据 base_dir 前缀查询该目录下所有 module 的记录"""
    base_dir = request.GET.get('base_dir', '').strip()
    if not base_dir:
        return JsonResponse({'ok': False, 'error': '缺少 base_dir 参数'}, status=400)

    project_ids = request.GET.get('project_ids', '')
    proj_id_list = _resolve_project_ids(project_ids)

    records = query_records_by_projects(
        proj_id_list=proj_id_list,
        dir_prefix=base_dir,
        release_only=False,
        order_desc=True,
        limit=10000,
    )

    if not records:
        return JsonResponse({
            'ok': True,
            'base_dir': base_dir,
            'modules': [],
            'total_modules': 0,
            'total_records': 0,
            'warning': f'目录 {base_dir} 下没有找到任何记录',
        })

    module_groups = {}
    for r in records:
        mid = r.module_id
        if mid not in module_groups:
            module_groups[mid] = {
                'module_id': mid,
                'module_name': '',
                'full_dirs': set(),
                'records': [],
            }
        module_groups[mid]['records'].append(r)
        if r.full_dir:
            module_groups[mid]['full_dirs'].add(r.full_dir)

    modules = []
    total_records = 0
    for mid, group in module_groups.items():
        recs = group['records']
        total_records += len(recs)
        versions = sorted(set(r.version for r in recs if r.version))
        latest = recs[0].to_dict() if recs else None

        mn = getattr(recs[0], 'module_name', None) if recs else None
        if not mn:
            try:
                m = Module.objects.get(pk=mid)
                mn = m.name if m else f'Module#{mid}'
            except Exception:
                mn = f'Module#{mid}'

        modules.append({
            'module_id': mid,
            'module_name': mn,
            'full_dirs': sorted(group['full_dirs']),
            'record_count': len(recs),
            'versions': versions,
            'latest_record': latest,
        })

    modules.sort(key=lambda m: m['module_name'].lower())
    return JsonResponse({
        'ok': True,
        'base_dir': base_dir,
        'modules': modules,
        'total_modules': len(modules),
        'total_records': total_records,
    })


@login_required
def api_get_metrics(request):
    """获取所有支持的指标列表"""
    return JsonResponse([
        {'name': k, 'direction': v} for k, v in QOR_METRIC_DIRECTION.items()
    ], safe=False)


@login_required
def api_get_versions(request):
    """获取所有版本号"""
    project_ids = request.GET.get('project_ids', '')
    module_ids = request.GET.get('module_ids', '')

    records = query_records_by_projects(
        proj_id_list=_resolve_project_ids(project_ids),
        module_ids_str=module_ids,
        release_only=False,
        order_desc=True,
        limit=10000,
    )
    versions = sorted(set(r.version for r in records if r.version))
    return JsonResponse(versions, safe=False)


@login_required
def api_get_run_notes(request):
    """获取 Run 备注"""
    record_id = request.GET.get('record_id')
    if not record_id:
        return JsonResponse([], safe=False)
    try:
        record_id = int(record_id)
    except (ValueError, TypeError):
        return JsonResponse([], safe=False)

    pid = _find_qor_record_project(record_id)
    if pid is None:
        return JsonResponse([], safe=False)
    db_name = _get_project_db(pid)
    try:
        get_project_engine(pid)
        notes = RunNote.objects.using(db_name).filter(
            qor_record_id=record_id,
        ).order_by('created_at')
        return JsonResponse([n.to_dict() for n in notes], safe=False)
    except Exception:
        return JsonResponse([], safe=False)


@login_required
def api_compare(request):
    """对比多个版本的 QoR 数据"""
    record_ids = request.GET.get('record_ids', '')
    if not record_ids:
        return JsonResponse({'error': 'record_ids 必填'}, status=400)
    rid_list = [int(x) for x in record_ids.split(',') if x.strip().isdigit()]
    if not rid_list:
        return JsonResponse({'error': '无效的 record_ids'}, status=400)

    all_records = []
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            recs = QorRecord.objects.using(db_name).filter(pk__in=rid_list)
            all_records.extend(recs)
        except Exception:
            continue
    return JsonResponse([r.to_dict() for r in all_records], safe=False)


@login_required
def export_data(request):
    """导出对比结果为 CSV"""
    record_ids = request.GET.get('record_ids', '')
    fmt = request.GET.get('format', 'csv').lower()
    if not record_ids:
        return JsonResponse({'error': 'record_ids 必填'}, status=400)
    rid_list = [int(x) for x in record_ids.split(',') if x.strip().isdigit()]

    all_records = []
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            recs = QorRecord.objects.using(db_name).filter(pk__in=rid_list)
            all_records.extend(recs)
        except Exception:
            continue

    if not all_records:
        return JsonResponse({'error': '无数据'}, status=404)

    rows = [r.to_dict() for r in all_records]

    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        if fmt == 'xlsx':
            output = _io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='QoR')
            output.seek(0)
            response = HttpResponse(
                output.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = (
                f'attachment; filename="qor_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
            )
            return response
        else:
            output = _io.StringIO()
            df.to_csv(output, index=False)
            csv_data = output.getvalue().encode('utf-8-sig')
            response = HttpResponse(csv_data, content_type='text/csv')
            response['Content-Disposition'] = (
                f'attachment; filename="qor_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
            )
            return response
    except ImportError:
        pass

    # Fallback: 纯 CSV
    output = _io.StringIO()
    if rows:
        keys = rows[0].keys()
        writer = _csv.DictWriter(output, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v) if v is not None else '' for k, v in row.items()})
    csv_data = output.getvalue().encode('utf-8-sig')
    response = HttpResponse(csv_data, content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="qor_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    )
    return response


# =========================================================================
# Review API
# =========================================================================

@login_required
def reviews_options(request):
    """返回前端表单所需的全部选项"""
    if request.user.is_viewer:
        return JsonResponse({
            'projects': [], 'approved_tile_reviews': [], 'approved_group_reviews': [],
        })

    projects = []
    for p in Project.objects.all():
        db_name = _get_project_db(p.id)
        try:
            get_project_engine(p.id)
            modules = []
            for m in Module.objects.using(db_name).filter(project_id=p.id):
                records = [{
                    'id': r.id, 'version': r.version or 'v1',
                } for r in QorRecord.objects.using(db_name).filter(module_id=m.id)[:500]]
                modules.append({'id': m.id, 'name': m.name, 'records': records})
            projects.append({'id': p.id, 'name': p.name, 'modules': modules})
        except Exception:
            projects.append({'id': p.id, 'name': p.name, 'modules': []})

    approved_tiles = []
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            for r in TileReview.objects.using(db_name).filter(status=REVIEW_STATUS_APPROVED)[:200]:
                approved_tiles.append({
                    'id': r.id, 'title': r.title, 'project_id': r.project_id,
                    'module_name': r.module.name if hasattr(r, 'module') and r.module else None,
                    'verdict': r.verdict,
                    'created_at': r.created_at.isoformat() if r.created_at else None,
                })
        except Exception:
            continue

    approved_groups = []
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            for r in GroupReview.objects.using(db_name).filter(status=REVIEW_STATUS_APPROVED)[:200]:
                approved_groups.append({
                    'id': r.id, 'title': r.title, 'project_id': r.project_id,
                    'group_name': r.group_name, 'verdict': r.verdict,
                    'created_at': r.created_at.isoformat() if r.created_at else None,
                })
        except Exception:
            continue

    return JsonResponse({
        'projects': projects,
        'approved_tile_reviews': approved_tiles,
        'approved_group_reviews': approved_groups,
    })


# ---- Tile Reviews ----

@login_required
def list_tile_reviews(request):
    """List or create a module-level weekly review."""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            pid = int(data.get('project_id'))
            module_id = int(data.get('module_id'))
            db_name = _get_project_db(pid)
            get_project_engine(pid)
            module = Module.objects.using(db_name).get(pk=module_id, project_id=pid)
            if not module.can_be_managed_by(request.user):
                return JsonResponse({'error': 'forbidden'}, status=403)
            record_id = data.get('record_id')
            record = None
            if record_id:
                record = QorRecord.objects.using(db_name).get(
                    pk=record_id, module_id=module_id,
                )
            row = TileReview(
                project_id=pid,
                module_id=module_id,
                record=record,
                title=data.get('title') or f'{module.name} weekly review',
                period=data.get('period', 'weekly'),
                summary=data.get('summary', ''),
                verdict=data.get('verdict'),
                created_by=request.user.id,
            )
            for key in ('key_metrics', 'findings', 'decisions', 'next_steps', 'risks'):
                if data.get(key) is not None:
                    setattr(row, key, json.dumps(data[key], ensure_ascii=False))
            row.save(using=db_name)
            return JsonResponse(row.to_dict(include_detail=True), status=201)
        except (ValueError, TypeError, Module.DoesNotExist, QorRecord.DoesNotExist) as exc:
            return JsonResponse({'error': f'invalid review: {exc}'}, status=400)
    pid = request.GET.get('project_id')
    if pid:
        try:
            pid = int(pid)
        except (ValueError, TypeError):
            pid = None

    if pid is not None:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            rows = TileReview.objects.using(db_name).filter(project_id=pid).order_by('-created_at')[:500]
            return JsonResponse({'items': [r.to_dict(include_detail=True) for r in rows]})
        except Exception:
            return JsonResponse({'items': []})
    else:
        items = []
        for p in _resolve_project_ids():
            db_name = _get_project_db(p)
            try:
                get_project_engine(p)
                rows = TileReview.objects.using(db_name).order_by('-created_at')[:500]
                items.extend([r.to_dict(include_detail=True) for r in rows])
            except Exception:
                continue
        return JsonResponse({'items': items})


@login_required
def tile_review_detail(request, rid):
    """Tile Review 详情 (GET) / 更新 (PUT)"""
    if request.method == 'GET':
        for pid in _resolve_project_ids():
            db_name = _get_project_db(pid)
            try:
                get_project_engine(pid)
                r = TileReview.objects.using(db_name).get(pk=rid)
                return JsonResponse(r.to_dict(include_detail=True))
            except TileReview.DoesNotExist:
                continue
        return JsonResponse({'error': '不存在'}, status=404)

    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    data = json.loads(request.body) if request.body else {}
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = TileReview.objects.using(db_name).get(pk=rid)
            if request.method == 'DELETE':
                if not request.user.is_admin and r.created_by != request.user.id:
                    return JsonResponse({'error': 'forbidden'}, status=403)
                if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
                    return JsonResponse({'error': 'only draft/rejected reviews can be deleted'}, status=400)
                r.delete(using=db_name)
                return JsonResponse({'ok': True})
            if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
                return JsonResponse({'error': f'当前状态 {r.status} 不可修改'}, status=400)
            for k in ('title', 'period', 'summary', 'verdict'):
                if k in data:
                    setattr(r, k, data[k])
            for k in ('key_metrics', 'findings', 'decisions', 'next_steps', 'risks'):
                if k in data:
                    val = json.dumps(data[k], ensure_ascii=False) if data[k] else None
                    setattr(r, k, val)
            r.save(using=db_name)
            return JsonResponse(r.to_dict())
        except TileReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def submit_tile_review(request, rid):
    """提交 Tile Review"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = TileReview.objects.using(db_name).get(pk=rid)
            if not request.user.is_admin and r.created_by != request.user.id:
                return JsonResponse({'error': 'forbidden'}, status=403)
            if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
                return JsonResponse({'error': f'当前状态 {r.status} 不可提交'}, status=400)
            r.status = REVIEW_STATUS_SUBMITTED
            r.submitted_by = request.user.id
            r.submitted_at = timezone.now()
            r.save(using=db_name)
            return JsonResponse(r.to_dict())
        except TileReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def review_tile_review(request, rid):
    """审批 Tile Review"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = TileReview.objects.using(db_name).get(pk=rid)
            if r.status != REVIEW_STATUS_SUBMITTED:
                return JsonResponse({'error': f'当前状态 {r.status} 不可审批'}, status=400)
            if not request.user.is_admin:
                global_module_id = LegacyModuleMapping.objects.filter(
                    project_id=r.project_id,
                    legacy_module_id=r.module_id,
                ).values_list('module_id', flat=True).first()
                is_group_owner = ReviewGroupModule.objects.filter(
                    project_module__project_id=r.project_id,
                    project_module__module_id=global_module_id,
                    group__owner_id=request.user.id,
                ).exists()
                if not is_group_owner:
                    return JsonResponse({'error': 'forbidden'}, status=403)
            data = json.loads(request.body) if request.body else {}
            action = data.get('action')
            if action not in ('approve', 'reject'):
                return JsonResponse({'error': 'action 必须是 approve 或 reject'}, status=400)
            r.status = REVIEW_STATUS_APPROVED if action == 'approve' else REVIEW_STATUS_REJECTED
            r.reviewed_by = request.user.id
            r.reviewed_at = timezone.now()
            r.review_comment = data.get('comment', '')
            r.save(using=db_name)
            return JsonResponse(r.to_dict(include_detail=True))
        except TileReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


# ---- Group Reviews ----

def _is_project_owner(user, project_id):
    return ProjectMember.objects.filter(
        project_id=project_id, user=user, role='owner',
    ).exists()


def _review_capabilities(
    row, user, creator_field, is_project_owner=None, allow_owner_self_review=False,
):
    if is_project_owner is None:
        is_project_owner = _is_project_owner(user, row.project_id)
    creator_id = getattr(row, creator_field)
    can_manage = bool(user.is_admin or creator_id == user.id)
    can_review = bool(
        row.status == REVIEW_STATUS_SUBMITTED
        and (
            user.is_admin
            or (
                is_project_owner
                and (allow_owner_self_review or creator_id != user.id)
            )
        )
    )
    editable = row.status in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED)
    return {
        'can_view': True,
        'can_edit': can_manage and editable,
        'can_delete': can_manage and editable,
        'can_submit': can_manage and editable,
        'can_review': can_review,
    }


def _review_identity_payload(value, creator_id, creator_label):
    user_ids = [creator_id]
    if value.get('reviewed_by'):
        user_ids.append(value['reviewed_by'])
    usernames = dict(
        User.objects.filter(id__in=user_ids).values_list('id', 'username')
    )
    value[creator_label] = usernames.get(creator_id)
    value['reviewer_name'] = usernames.get(value.get('reviewed_by'))
    return value


def _group_review_payload(row, user, is_project_owner=None):
    value = row.to_dict(include_detail=True)
    value.update(
        _review_capabilities(row, user, 'leader_id', is_project_owner)
    )
    value['review_type'] = 'group'
    value['snapshot_provenance'] = _verified_snapshot_provenance(row)
    return _review_identity_payload(value, row.leader_id, 'leader_name')


def _project_review_payload(row, user, is_project_owner=None):
    value = row.to_dict(include_detail=True)
    value.pop('subsystem', None)
    value.update(
        _review_capabilities(
            row, user, 'manager_id', is_project_owner,
            allow_owner_self_review=True,
        )
    )
    value['review_type'] = 'project'
    value['snapshot_provenance'] = _verified_snapshot_provenance(row)
    return _review_identity_payload(value, row.manager_id, 'manager_name')


class ReviewSnapshotRequired(ValueError):
    pass


def _snapshot_binding(data, project_id, db_name):
    week_value = data.get('week_start')
    if not week_value:
        raise ValueError('week_start is required')
    week_start = datetime.fromisoformat(str(week_value)).date()
    snapshot = get_authoritative_weekly_snapshot(project_id, week_start)
    if not snapshot:
        raise ReviewSnapshotRequired(
            'freeze the requested project week before creating a review'
        )
    frozen = json.loads(snapshot.frozen_data)
    return {
        'snapshot_id': snapshot.id,
        'snapshot_checksum': snapshot.checksum,
        'snapshot_week_start': snapshot.week_start,
        'snapshot_schema_version': snapshot.schema_version,
        'snapshot_config_version': str(frozen.get('config_version', '')),
        'snapshot_data': snapshot.frozen_data,
    }


def _verified_snapshot_provenance(row):
    value = row.snapshot_provenance()
    if not row.snapshot_id:
        return value
    alias = row._state.db or _get_project_db(row.project_id)
    snapshot = ReviewSnapshot.objects.using(alias).filter(
        pk=row.snapshot_id,
        project_id=row.project_id,
        snapshot_type='weekly_review',
        week_start=row.snapshot_week_start,
    ).first()
    authoritative_verified = bool(
        snapshot
        and snapshot.checksum == row.snapshot_checksum
        and snapshot.verify_integrity()
    )
    value['authoritative_snapshot_found'] = bool(snapshot)
    value['authoritative_verified'] = authoritative_verified
    value['verified'] = bool(value.get('copy_verified') and authoritative_verified)
    return value


def _review_project_id(request, data=None):
    raw_value = request.GET.get('project_id')
    if raw_value in (None, '') and data is not None:
        raw_value = data.get('project_id')
    if raw_value in (None, ''):
        raise ValueError('project_id is required')
    return int(raw_value)


def _project_scoped_review(model, project_id, rid):
    get_project_engine(project_id)
    db_name = _get_project_db(project_id)
    row = model.objects.using(db_name).get(pk=rid, project_id=project_id)
    return row, db_name


@login_required
def list_group_reviews(request):
    """List or create a YAML-defined group review."""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            pid = int(data.get('project_id'))
            group = ReviewGroup.objects.get(project_id=pid, name=data.get('group_name'))
            if not request.user.is_admin and group.owner_id != request.user.id:
                return JsonResponse({'error': 'forbidden'}, status=403)
            db_name = _get_project_db(pid)
            get_project_engine(pid)
            binding = _snapshot_binding(data, pid, db_name)
            with transaction.atomic(using=db_name):
                row = GroupReview(
                    project_id=pid,
                    group_name=group.name,
                    period='weekly',
                    title=data.get('title') or f'{group.name} weekly review',
                    summary=data.get('summary', ''),
                    verdict=data.get('verdict'),
                    leader_id=request.user.id,
                    **binding,
                )
                for key in ('tile_review_ids', 'key_metrics', 'findings', 'decisions', 'next_steps', 'risks'):
                    if data.get(key) is not None:
                        setattr(row, key, json.dumps(data[key], ensure_ascii=False))
                row.save(using=db_name)
            return JsonResponse(_group_review_payload(row, request.user), status=201)
        except ReviewSnapshotRequired as exc:
            return JsonResponse(
                {'error': str(exc), 'code': 'review_snapshot_required'},
                status=409,
            )
        except SnapshotIntegrityError as exc:
            return JsonResponse(
                {'error': str(exc), 'code': 'snapshot_integrity_failed'},
                status=409,
            )
        except (ValueError, TypeError, ReviewGroup.DoesNotExist) as exc:
            return JsonResponse({'error': f'invalid review: {exc}'}, status=400)
    pid = request.GET.get('project_id')
    if pid:
        try:
            pid = int(pid)
        except (ValueError, TypeError):
            pid = None

    if pid is not None:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            rows = GroupReview.objects.using(db_name).filter(project_id=pid)
            group_name = request.GET.get('group_name', '').strip()
            if group_name:
                rows = rows.filter(group_name=group_name)
            rows = rows.order_by('-created_at')[:500]
            is_project_owner = _is_project_owner(request.user, pid)
            return JsonResponse({
                'items': [
                    _group_review_payload(r, request.user, is_project_owner)
                    for r in rows
                ],
            })
        except Exception:
            return JsonResponse({'items': []})
    else:
        items = []
        for p in _resolve_project_ids():
            db_name = _get_project_db(p)
            try:
                get_project_engine(p)
                rows = GroupReview.objects.using(db_name).order_by('-created_at')[:500]
                is_project_owner = _is_project_owner(request.user, p)
                items.extend([
                    _group_review_payload(r, request.user, is_project_owner)
                    for r in rows
                ])
            except Exception:
                continue
        return JsonResponse({'items': items})


@login_required
def group_review_detail(request, rid):
    """Group Review 详情 (GET) / 更新 (PUT)"""
    try:
        data = json.loads(request.body) if request.body else {}
        pid = _review_project_id(request, data)
        r, db_name = _project_scoped_review(GroupReview, pid, rid)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except GroupReview.DoesNotExist:
        return JsonResponse({'error': '不存在'}, status=404)

    capabilities = _review_capabilities(r, request.user, 'leader_id')
    if request.method == 'GET':
        return JsonResponse(_group_review_payload(r, request.user))
    if request.user.is_viewer or not capabilities['can_edit']:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if request.method == 'DELETE':
        r.delete(using=db_name)
        return JsonResponse({'ok': True})
    for k in ('title', 'summary', 'verdict'):
        if k in data:
            setattr(r, k, data[k])
    for k in ('tile_review_ids', 'key_metrics', 'findings', 'decisions', 'next_steps', 'risks'):
        if k in data:
            val = json.dumps(data[k], ensure_ascii=False) if data[k] else None
            setattr(r, k, val)
    r.updated_at = timezone.now()
    r.save(using=db_name)
    return JsonResponse(_group_review_payload(r, request.user))


@login_required
def submit_group_review(request, rid):
    """提交 Group Review"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    try:
        data = json.loads(request.body) if request.body else {}
        pid = _review_project_id(request, data)
        r, db_name = _project_scoped_review(GroupReview, pid, rid)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except GroupReview.DoesNotExist:
        return JsonResponse({'error': '不存在'}, status=404)
    if not _review_capabilities(r, request.user, 'leader_id')['can_submit']:
        if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
            return JsonResponse({'error': f'当前状态 {r.status} 不可提交'}, status=400)
        return JsonResponse({'error': 'forbidden'}, status=403)
    was_rejected = r.status == REVIEW_STATUS_REJECTED
    r.status = REVIEW_STATUS_SUBMITTED
    r.submitted_at = timezone.now()
    r.submission_count = (r.submission_count or 0) + 1
    if was_rejected:
        r.resubmitted_at = r.submitted_at
    r.updated_at = timezone.now()
    r.save(using=db_name)
    return JsonResponse(_group_review_payload(r, request.user))


@login_required
def review_group_review(request, rid):
    """审批 Group Review"""
    try:
        data = json.loads(request.body) if request.body else {}
        pid = _review_project_id(request, data)
        r, db_name = _project_scoped_review(GroupReview, pid, rid)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except GroupReview.DoesNotExist:
        return JsonResponse({'error': '不存在'}, status=404)
    if r.status != REVIEW_STATUS_SUBMITTED:
        return JsonResponse({'error': f'当前状态 {r.status} 不可审批'}, status=400)
    if not request.user.is_admin and r.leader_id == request.user.id:
        return JsonResponse({'error': '不能审核自己创建的 review'}, status=400)
    if not _review_capabilities(r, request.user, 'leader_id')['can_review']:
        return JsonResponse({'error': 'forbidden'}, status=403)
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return JsonResponse({'error': 'action 必须是 approve 或 reject'}, status=400)
    r.status = REVIEW_STATUS_APPROVED if action == 'approve' else REVIEW_STATUS_REJECTED
    r.reviewed_by = request.user.id
    r.reviewed_at = timezone.now()
    r.review_comment = data.get('comment', '')
    r.updated_at = timezone.now()
    r.save(using=db_name)
    return JsonResponse(_group_review_payload(r, request.user))


# ---- Subsystem Reviews ----

@login_required
def list_subsystem_reviews(request):
    """List or create project reviews (legacy model name: SubsystemReview)."""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            pid = int(data.get('project_id'))
            project = Project.objects.get(pk=pid)
            membership = ProjectMember.objects.filter(
                project=project, user=request.user, role='owner',
            ).exists()
            if not request.user.is_admin and not membership:
                return JsonResponse({'error': 'forbidden'}, status=403)
            db_name = _get_project_db(pid)
            get_project_engine(pid)
            binding = _snapshot_binding(data, pid, db_name)
            with transaction.atomic(using=db_name):
                row = SubsystemReview(
                    project_id=pid,
                    subsystem=project.name,
                    period='weekly',
                    title=data.get('title') or f'{project.name} weekly review',
                    summary=data.get('summary', ''),
                    verdict=data.get('verdict'),
                    manager_id=request.user.id,
                    **binding,
                )
                for key in ('group_review_ids', 'key_metrics', 'findings', 'decisions', 'next_steps', 'risks'):
                    if data.get(key) is not None:
                        setattr(row, key, json.dumps(data[key], ensure_ascii=False))
                row.save(using=db_name)
            value = _project_review_payload(row, request.user)
            value['project_name'] = project.name
            return JsonResponse(value, status=201)
        except ReviewSnapshotRequired as exc:
            return JsonResponse(
                {'error': str(exc), 'code': 'review_snapshot_required'},
                status=409,
            )
        except SnapshotIntegrityError as exc:
            return JsonResponse(
                {'error': str(exc), 'code': 'snapshot_integrity_failed'},
                status=409,
            )
        except (ValueError, TypeError, Project.DoesNotExist) as exc:
            return JsonResponse({'error': f'invalid review: {exc}'}, status=400)
    pid = request.GET.get('project_id')
    if pid:
        try:
            pid = int(pid)
        except (ValueError, TypeError):
            pid = None

    if pid is not None:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            rows = SubsystemReview.objects.using(db_name).filter(project_id=pid).order_by('-created_at')[:500]
            project = Project.objects.filter(pk=pid).first()
            items = []
            is_project_owner = _is_project_owner(request.user, pid)
            for row in rows:
                value = _project_review_payload(row, request.user, is_project_owner)
                value['project_name'] = project.name if project else row.subsystem
                value['review_type'] = 'project'
                items.append(value)
            return JsonResponse({'items': items})
        except Exception:
            return JsonResponse({'items': []})
    else:
        items = []
        for p in _resolve_project_ids():
            db_name = _get_project_db(p)
            try:
                get_project_engine(p)
                rows = SubsystemReview.objects.using(db_name).order_by('-created_at')[:500]
                project = Project.objects.filter(pk=p).first()
                is_project_owner = _is_project_owner(request.user, p)
                for row in rows:
                    value = _project_review_payload(
                        row, request.user, is_project_owner,
                    )
                    value['project_name'] = (
                        project.name if project else row.subsystem
                    )
                    value['review_type'] = 'project'
                    items.append(value)
            except Exception:
                continue
        return JsonResponse({'items': items})


@login_required
def subsystem_review_detail(request, rid):
    """Subsystem Review 详情 (GET) / 更新 (PUT)"""
    try:
        data = json.loads(request.body) if request.body else {}
        pid = _review_project_id(request, data)
        r, db_name = _project_scoped_review(SubsystemReview, pid, rid)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except SubsystemReview.DoesNotExist:
        return JsonResponse({'error': '不存在'}, status=404)

    capabilities = _review_capabilities(r, request.user, 'manager_id')
    project = Project.objects.filter(pk=pid).first()
    if request.method == 'GET':
        value = _project_review_payload(r, request.user)
        value['project_name'] = project.name if project else r.subsystem
        return JsonResponse(value)
    if request.user.is_viewer or not capabilities['can_edit']:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if request.method == 'DELETE':
        r.delete(using=db_name)
        return JsonResponse({'ok': True})
    for k in ('title', 'summary', 'verdict'):
        if k in data:
            setattr(r, k, data[k])
    for k in ('group_review_ids', 'key_metrics', 'findings', 'decisions', 'next_steps', 'risks'):
        if k in data:
            val = json.dumps(data[k], ensure_ascii=False) if data[k] else None
            setattr(r, k, val)
    r.updated_at = timezone.now()
    r.save(using=db_name)
    value = _project_review_payload(r, request.user)
    value['project_name'] = project.name if project else r.subsystem
    return JsonResponse(value)


@login_required
def submit_subsystem_review(request, rid):
    """提交 Subsystem Review"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    try:
        data = json.loads(request.body) if request.body else {}
        pid = _review_project_id(request, data)
        r, db_name = _project_scoped_review(SubsystemReview, pid, rid)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except SubsystemReview.DoesNotExist:
        return JsonResponse({'error': '不存在'}, status=404)
    if not _review_capabilities(
        r, request.user, 'manager_id', allow_owner_self_review=True,
    )['can_submit']:
        if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
            return JsonResponse({'error': f'当前状态 {r.status} 不可提交'}, status=400)
        return JsonResponse({'error': 'forbidden'}, status=403)
    was_rejected = r.status == REVIEW_STATUS_REJECTED
    r.status = REVIEW_STATUS_SUBMITTED
    r.submitted_at = timezone.now()
    r.submission_count = (r.submission_count or 0) + 1
    if was_rejected:
        r.resubmitted_at = r.submitted_at
    r.updated_at = timezone.now()
    r.save(using=db_name)
    return JsonResponse(_project_review_payload(r, request.user))


@login_required
def review_subsystem_review(request, rid):
    """审批 Subsystem Review"""
    try:
        data = json.loads(request.body) if request.body else {}
        pid = _review_project_id(request, data)
        r, db_name = _project_scoped_review(SubsystemReview, pid, rid)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except SubsystemReview.DoesNotExist:
        return JsonResponse({'error': '不存在'}, status=404)
    if r.status != REVIEW_STATUS_SUBMITTED:
        return JsonResponse({'error': f'当前状态 {r.status} 不可审批'}, status=400)
    if not _review_capabilities(
        r, request.user, 'manager_id', allow_owner_self_review=True,
    )['can_review']:
        return JsonResponse({'error': 'forbidden'}, status=403)
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return JsonResponse({'error': 'action 必须是 approve 或 reject'}, status=400)
    r.status = REVIEW_STATUS_APPROVED if action == 'approve' else REVIEW_STATUS_REJECTED
    r.reviewed_by = request.user.id
    r.reviewed_at = timezone.now()
    r.review_comment = data.get('comment', '')
    r.updated_at = timezone.now()
    r.save(using=db_name)
    return JsonResponse(_project_review_payload(r, request.user))


# ---- Review Snapshots ----

@login_required
def weekly_review_overview(request):
    """Return frozen review input, or an explicitly requested live preview."""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    try:
        pid = int(request.GET.get('project_id'))
        week_value = request.GET.get('week_start')
        week_start = datetime.fromisoformat(week_value).date() if week_value else None
        live_value = request.GET.get('live_preview', '').strip().lower()
        if live_value not in ('', '0', '1', 'false', 'true'):
            raise ValueError('live_preview must be true or false')
        live_preview = live_value in ('1', 'true')
        payload = get_weekly_review_input(
            request.user, pid, week_start, live_preview=live_preview,
        )
        is_project_owner = _is_project_owner(request.user, pid)
        is_authoritative = payload.get('input_mode') == 'frozen'
        payload['capabilities'] = {
            'can_freeze': bool(
                (request.user.is_admin or is_project_owner)
                and not payload.get('is_frozen')
                and not payload.get('frozen_snapshot')
            ),
            'can_create_project_review': bool(
                is_authoritative and (request.user.is_admin or is_project_owner)
            ),
            'can_view_live_preview': bool(payload.get('can_live_preview')),
        }
        for group in payload.get('groups', []):
            group['can_create_review'] = bool(
                is_authoritative
                and (
                    request.user.is_admin
                    or group.get('owner_id') == request.user.id
                )
            )
            for module in group.get('modules', []):
                star = module.get('star')
                if star:
                    current_risk = assess_module_history(
                        pid, int(module['module_id']),
                    ).get(str(star.get('id')))
                    if current_risk:
                        module['risk'] = current_risk
                module.setdefault('risk', {
                    'rating': 'unrated',
                    'auto_rating': 'unrated',
                    'manual_rating': None,
                    'source': 'automatic',
                    'details': [],
                })
                module['risk']['can_edit'] = can_edit_risk(
                    request.user, Project.objects.get(pk=pid), int(module['module_id']),
                )
                module['can_select_star'] = bool(
                    not payload.get('is_frozen')
                    and not payload.get('frozen_snapshot')
                    and (
                        request.user.is_admin
                        or module.get('release_owner_id') == request.user.id
                    )
                )
        return JsonResponse(payload)
    except PermissionError as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    except SnapshotIntegrityError as exc:
        return JsonResponse({'error': str(exc), 'code': 'snapshot_integrity_failed'}, status=409)
    except (TypeError, ValueError, Project.DoesNotExist) as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@login_required
def weekly_review_star(request):
    """Select or clear the explicit official run for a module/week."""
    if request.method not in ('POST', 'DELETE'):
        return JsonResponse({'error': 'method not allowed'}, status=405)
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    try:
        data = json.loads(request.body) if request.body else {}
        week_value = data.get('week_start')
        week_start = datetime.fromisoformat(week_value).date() if week_value else None
        project_id = int(data.get('project_id'))
        module_id = int(data.get('module_id'))
        record_id = str(data.get('record_id'))
        if request.method == 'DELETE':
            cleared = clear_weekly_star(
                request.user, project_id, module_id, record_id, week_start,
            )
            return JsonResponse({
                'ok': True,
                'cleared': cleared,
                'project_id': project_id,
                'module_id': module_id,
                'record_id': record_id,
                'week_start': week_start.isoformat() if week_start else None,
                'explicit': False,
            })
        selection = select_weekly_star(
            request.user, project_id, module_id, record_id, week_start,
        )
        return JsonResponse({
            'ok': True,
            'project_id': selection.project_id,
            'module_id': selection.module_id,
            'record_id': selection.record_id,
            'week_start': selection.week_start.isoformat(),
            'explicit': True,
            'source': selection.source,
        })
    except PermissionError as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    except (TypeError, ValueError, ProjectModule.DoesNotExist, QorRecord.DoesNotExist) as exc:
        return JsonResponse({'error': f'invalid star selection: {exc}'}, status=400)


@login_required
def list_snapshots(request):
    """List snapshots or freeze an immutable weekly review snapshot."""
    if request.method == 'POST':
        if request.user.is_viewer:
            return JsonResponse({'error': 'forbidden'}, status=403)
        try:
            data = json.loads(request.body) if request.body else {}
            pid = int(data.get('project_id'))
            week_value = data.get('week_start')
            week_start = datetime.fromisoformat(week_value).date() if week_value else None
            allowed = request.user.is_admin or ProjectMember.objects.filter(
                project_id=pid, user=request.user, role='owner',
            ).exists()
            if not allowed:
                return JsonResponse({'error': 'forbidden'}, status=403)
            snapshot, created = create_weekly_snapshot(
                request.user, pid, week_start, data.get('description', ''),
            )
            payload = snapshot.to_dict(include_data=True)
            payload['created'] = created
            return JsonResponse(payload, status=201 if created else 200)
        except SnapshotIntegrityError as exc:
            return JsonResponse(
                {'error': str(exc), 'code': 'snapshot_integrity_failed'}, status=409,
            )
        except (TypeError, ValueError, Project.DoesNotExist) as exc:
            return JsonResponse({'error': str(exc)}, status=400)
    pid = request.GET.get('project_id')
    if pid:
        try:
            pid = int(pid)
        except (ValueError, TypeError):
            pid = None

    if pid is not None:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            rows = ReviewSnapshot.objects.using(db_name).filter(project_id=pid).order_by('-created_at')[:500]
            return JsonResponse([r.to_dict() for r in rows], safe=False)
        except Exception:
            return JsonResponse([], safe=False)
    else:
        items = []
        for p in _resolve_project_ids():
            db_name = _get_project_db(p)
            try:
                get_project_engine(p)
                rows = ReviewSnapshot.objects.using(db_name).order_by('-created_at')[:500]
                items.extend([r.to_dict() for r in rows])
            except Exception:
                continue
        return JsonResponse(items, safe=False)


@login_required
def snapshot_detail(request, rid):
    """Review Snapshot 详情"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            snap = ReviewSnapshot.objects.using(db_name).get(pk=rid)
            return JsonResponse(snap.to_dict(include_data=True))
        except ReviewSnapshot.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def upload_snapshot_file(request, rid):
    """上传 Review Snapshot 附件"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)

    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            snap = ReviewSnapshot.objects.using(db_name).get(pk=rid)
            if 'file' not in request.FILES:
                return JsonResponse({'error': '缺少文件'}, status=400)
            f = request.FILES['file']
            if not f.name:
                return JsonResponse({'error': '文件名为空'}, status=400)

            upload_dir = os.path.join(settings.MEDIA_ROOT, 'review_snapshots', str(rid))
            os.makedirs(upload_dir, exist_ok=True)

            safe_name = os.path.basename(f.name)
            storage_path = os.path.join(upload_dir, safe_name)

            with open(storage_path, 'wb+') as dest:
                for chunk in f.chunks():
                    dest.write(chunk)

            file_size = os.path.getsize(storage_path)
            with open(storage_path, 'rb') as fp:
                file_checksum = hashlib.sha256(fp.read()).hexdigest()

            rf = ReviewFile(
                snapshot_id=rid,
                filename=safe_name,
                storage_path=storage_path,
                file_size=file_size,
                content_type=f.content_type or 'application/octet-stream',
                checksum=file_checksum,
                category=request.POST.get('category', 'rpt'),
                description=request.POST.get('description', ''),
                uploaded_by=request.user.id,
            )
            rf.save(using=db_name)
            snap.file_count = (snap.file_count or 0) + 1
            snap.save(using=db_name, update_fields=['file_count'])
            return JsonResponse(rf.to_dict(), status=201)
        except ReviewSnapshot.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def verify_snapshot(request, rid):
    """校验 Review Snapshot"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            snap = ReviewSnapshot.objects.using(db_name).get(pk=rid)
            ok = snap.verify_integrity()
            return JsonResponse({'id': rid, 'verified': ok})
        except ReviewSnapshot.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def download_review_file(request, fid):
    """下载 Review 附件"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            rf = ReviewFile.objects.using(db_name).get(pk=fid)
            if not os.path.exists(rf.storage_path):
                return JsonResponse({'error': 'file not found'}, status=404)
            with open(rf.storage_path, 'rb') as f:
                response = HttpResponse(f.read(), content_type=rf.content_type)
                response['Content-Disposition'] = f'attachment; filename="{rf.filename}"'
                return response
        except ReviewFile.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


# =========================================================================
# Dashboard API
# =========================================================================

@login_required
@require_POST
def save_dashboard_config(request):
    """保存 Dashboard 配置"""
    data = json.loads(request.body) if request.body else {}
    dash_id = data.get('id')
    name = (data.get('name') or 'My Dashboard').strip()
    config = data.get('config', {})
    is_default = data.get('is_default', False)

    if dash_id:
        dash = get_object_or_404(UserDashboard, pk=dash_id, user=request.user)
        dash.name = name
        dash.config = json.dumps(config, ensure_ascii=False)
        dash.is_default = is_default
    else:
        if is_default:
            UserDashboard.objects.filter(user=request.user, is_default=True).update(is_default=False)
        dash = UserDashboard(
            user=request.user,
            name=name,
            config=json.dumps(config, ensure_ascii=False),
            is_default=is_default,
        )
    dash.save()
    return JsonResponse({'id': dash.id, 'name': dash.name, 'is_default': dash.is_default})


@login_required
def list_dashboard_configs(request):
    """列出 Dashboard 配置"""
    configs = UserDashboard.objects.filter(user=request.user).order_by('-updated_at')
    return JsonResponse([{
        'id': c.id,
        'name': c.name,
        'is_default': c.is_default,
        'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M') if c.updated_at else '',
    } for c in configs], safe=False)


@login_required
def dashboard_config_detail(request, dash_id):
    """Dashboard 配置详情"""
    dash = get_object_or_404(UserDashboard, pk=dash_id, user=request.user)
    return JsonResponse({
        'id': dash.id,
        'name': dash.name,
        'is_default': dash.is_default,
        'config': json.loads(dash.config) if dash.config else {},
    })


# ---- Dashboard Groups ----

@login_required
def list_dashboard_groups(request):
    """列出 Dashboard Groups"""
    items = []
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            all_groups = DashboardGroup.objects.using(db_name).all()
            for g in all_groups:
                if g.is_visible_to(request.user):
                    items.append(g.to_dict(include_config=False))
        except Exception:
            continue
    return JsonResponse(items, safe=False)


@login_required
def dashboard_group_detail(request, gid):
    """Dashboard Group 详情"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            g = DashboardGroup.objects.using(db_name).get(pk=gid)
            if not g.is_visible_to(request.user):
                return JsonResponse({'error': 'forbidden'}, status=403)
            return JsonResponse(g.to_dict(include_config=True))
        except DashboardGroup.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def my_default_group(request):
    """获取我的默认 Dashboard Group"""
    if request.user.is_viewer:
        return JsonResponse({'group': None, 'config': None})
    candidates = []
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            for g in DashboardGroup.objects.using(db_name).all():
                if g.shared_default and g.is_member(request.user.id):
                    candidates.append(g)
        except Exception:
            continue
    if not candidates:
        return JsonResponse({'group': None, 'config': None})
    candidates.sort(key=lambda g: (
        (g.project_id is None),
        -(g.updated_at.timestamp() if g.updated_at else 0),
    ))
    chosen = candidates[0]
    return JsonResponse({
        'group': chosen.to_dict(include_config=False),
        'config': json.loads(chosen.config) if chosen.config else None,
    })


# ---- Theme ----

@login_required
def get_user_theme(request):
    """获取用户主题 (GET) / 保存 (POST)"""
    if request.method == 'POST':
        data = json.loads(request.body) if request.body else {}
        theme = data.get('theme', 'classic').strip()
        if not theme:
            return JsonResponse({'error': 'theme 必填'}, status=400)
        request.user.set_theme(data)
        request.user.save(update_fields=['theme'])
        return JsonResponse({'ok': True})
    return JsonResponse({
        'theme': request.user.get_theme(),
    })


# =========================================================================
# Admin API - 项目管理
# =========================================================================

@login_required
def admin_create_project(request):
    """创建项目"""
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)
    data = json.loads(request.body) if request.body else {}
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': '项目名不能为空'}, status=400)
    if Project.objects.filter(name=name).exists():
        return JsonResponse({'error': '项目名已存在'}, status=400)
    p = Project(name=name, description=data.get('description', ''))
    p.save()
    return JsonResponse(p.to_dict())


@login_required
def admin_delete_project(request, project_id):
    """软删除项目 (隐藏)"""
    p = get_object_or_404(Project, pk=project_id)
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    if p.status == 'hidden':
        return JsonResponse({'error': '项目已是隐藏状态'}, status=400)
    p.status = 'hidden'
    p.hidden_at = timezone.now()
    p.hidden_by = request.user
    p.save()
    return JsonResponse({
        'ok': True,
        'message': f'项目 "{p.name}" 已隐藏',
        'project_id': p.id,
    })


@login_required
def admin_list_hidden_projects(request):
    """列出已隐藏项目"""
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)
    projects = Project.objects.filter(status='hidden').order_by('-hidden_at')
    result = []
    for p in projects:
        module_count, record_count, db_ok = _project_module_record_counts(p.id)
        hider = p.hidden_by
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'status': p.status,
            'module_count': module_count,
            'record_count': record_count,
            'project_db_exists': db_ok,
            'hidden_at': p.hidden_at.isoformat() if p.hidden_at else None,
            'hidden_by': p.hidden_by_id,
            'hidden_by_name': hider.username if hider else None,
            'created_at': p.created_at.isoformat() if p.created_at else None,
        })
    return JsonResponse(result, safe=False)


@login_required
def admin_restore_project(request, project_id):
    """恢复已隐藏项目"""
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)
    p = get_object_or_404(Project, pk=project_id)
    if p.status != 'hidden':
        return JsonResponse({'error': f'项目状态为 {p.status}, 不需要恢复'}, status=400)
    p.status = 'active'
    p.hidden_at = None
    p.hidden_by = None
    # Clear any stale lock metadata left from before soft-delete.
    p.locked_at = None
    p.locked_by = None
    p.lock_reason = ''
    p.save()
    return JsonResponse({
        'ok': True,
        'message': f'项目 "{p.name}" 已恢复为 active',
        'project': p.to_dict(),
    })


@login_required
def admin_hard_delete_project(request, project_id):
    """彻底删除项目"""
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)
    p = get_object_or_404(Project, pk=project_id)
    if p.status != 'hidden':
        return JsonResponse({'error': '只能彻底删除已隐藏项目, 请先软删除'}, status=400)

    data = json.loads(request.body) if request.body else {}
    confirm = data.get('confirm', request.GET.get('confirm', ''))
    if str(confirm).lower() not in ('1', 'true', 'yes'):
        module_count, record_count, _ = _project_module_record_counts(p.id)
        return JsonResponse({
            'error': '此操作不可逆! 请传 confirm=true 二次确认',
            'warning': f'将永久删除项目 "{p.name}" 及其 {module_count} 个模块, {record_count} 条记录',
        }, status=400)

    project_name = p.name
    p.delete()
    return JsonResponse({
        'ok': True,
        'message': f'项目 "{project_name}" 已彻底删除 (不可恢复)',
    })


@login_required
def admin_lock_project(request, project_id):
    """锁定项目：禁止上传/写入，仍可查看历史数据。"""
    p = get_object_or_404(Project, pk=project_id)
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    if p.status == 'hidden':
        return JsonResponse({'error': '隐藏项目请先恢复再锁定'}, status=400)
    if p.status == 'locked':
        return JsonResponse(p.to_dict())
    data = json.loads(request.body) if request.body else {}
    p.status = 'locked'
    p.locked_at = timezone.now()
    p.locked_by = request.user
    p.lock_reason = data.get('reason', '') or ''
    p.save()
    return JsonResponse(p.to_dict())


@login_required
def admin_unlock_project(request, project_id):
    """解锁项目，恢复可上传状态。"""
    p = get_object_or_404(Project, pk=project_id)
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    if p.status == 'hidden':
        return JsonResponse({'error': '隐藏项目请使用恢复接口'}, status=400)
    if p.status != 'locked':
        return JsonResponse({
            'error': f'项目状态为 {p.status}, 无需解锁',
        }, status=400)
    p.status = 'active'
    p.locked_at = None
    p.locked_by = None
    p.lock_reason = ''
    p.save()
    return JsonResponse(p.to_dict())


# =========================================================================
# Admin API - 快照管理
# =========================================================================

@login_required
def admin_list_snapshots(request, project_id):
    """列出项目快照"""
    get_object_or_404(Project, pk=project_id)
    db_name = _get_project_db(project_id)
    try:
        get_project_engine(project_id)
        snaps = DataSnapshot.objects.using(db_name).filter(project_id=project_id).order_by('-created_at')
        return JsonResponse([s.to_dict() for s in snaps], safe=False)
    except Exception:
        return JsonResponse([], safe=False)


@login_required
def admin_snapshot_detail(request, snap_id):
    """快照详情"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            snap = DataSnapshot.objects.using(db_name).get(pk=snap_id)
            if not snap.verify_integrity():
                return JsonResponse({'error': '快照数据校验失败', 'verified': False}, status=500)
            return JsonResponse(snap.to_dict(include_data=True))
        except DataSnapshot.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def admin_verify_snapshot(request, snap_id):
    """校验快照"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            snap = DataSnapshot.objects.using(db_name).get(pk=snap_id)
            ok = snap.verify_integrity()
            return JsonResponse({'id': snap_id, 'verified': ok, 'checksum': snap.prefix_checksum})
        except DataSnapshot.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def admin_rollback_snapshot(request, snap_id):
    """回滚快照"""
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)

    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            snap = DataSnapshot.objects.using(db_name).get(pk=snap_id)
            if not snap.verify_integrity():
                return JsonResponse({'error': '快照数据校验失败, 拒绝回滚'}, status=500)

            p = get_object_or_404(Project, pk=snap.project_id)
            blocked = _require_writable_project(p)
            if blocked:
                return blocked

            try:
                snapshot_data = json.loads(snap.data)
            except (json.JSONDecodeError, TypeError):
                return JsonResponse({'error': '快照数据解析失败'}, status=500)

            # 回滚前自动创建当前快照
            current_records = QorRecord.objects.using(db_name).filter(
                module__project_id=snap.project_id,
            )
            current_data = [r.to_dict() for r in current_records]
            current_json = json.dumps(current_data, ensure_ascii=False, default=str)
            pre_snap = DataSnapshot(
                project_id=snap.project_id,
                name=f'[Auto] Before rollback to "{snap.name}"',
                description=f'自动创建于回滚操作, 由 {request.user.username} 触发',
                snapshot_type='custom',
                data=current_json,
                record_count=len(current_data),
                checksum=DataSnapshot.compute_checksum(current_json),
                created_by=request.user.id,
            )
            pre_snap.save(using=db_name)

            module_map = {
                m.name: m.id for m in Module.objects.using(db_name).filter(project_id=snap.project_id)
            }

            current_records.delete()

            restored = 0
            skipped = 0
            for item in snapshot_data:
                module_name = item.get('module_name')
                if not module_name or module_name not in module_map:
                    skipped += 1
                    continue
                rec = QorRecord(
                    id=item.get('id'),
                    module_id=module_map[module_name],
                    version=item.get('version', 'v1'),
                    full_dir=item.get('full_dir', ''),
                    area_total=item.get('area_total'),
                    area_combinational=item.get('area_combinational'),
                    area_sequential=item.get('area_sequential'),
                    area_black_box=item.get('area_black_box'),
                    area_macro=item.get('area_macro'),
                    wns_setup=item.get('wns_setup'),
                    tns_setup=item.get('tns_setup'),
                    nvp_setup=item.get('nvp_setup'),
                    wns_hold=item.get('wns_hold'),
                    tns_hold=item.get('tns_hold'),
                    nvp_hold=item.get('nvp_hold'),
                    power_internal=item.get('power_internal'),
                    power_switching=item.get('power_switching'),
                    power_leakage=item.get('power_leakage'),
                    power_total=item.get('power_total'),
                    cell_count=item.get('cell_count'),
                    instance_count=item.get('instance_count'),
                    net_count=item.get('net_count'),
                    sequential_cell_count=item.get('sequential_cell_count'),
                    ram_cell_count=item.get('ram_cell_count'),
                    macro_cell_count=item.get('macro_cell_count'),
                    register_count=item.get('register_count'),
                    target_frequency=item.get('target_frequency'),
                    achieved_frequency=item.get('achieved_frequency'),
                    mbb_ratio=item.get('mbb_ratio'),
                    clock_gating_ratio=item.get('clock_gating_ratio'),
                    utilization=item.get('utilization'),
                    congestion=item.get('congestion'),
                    congestion_h=item.get('congestion_h'),
                    congestion_v=item.get('congestion_v'),
                    congestion_b=item.get('congestion_b'),
                    raw_dc_report=item.get('raw_dc_report'),
                    source_file=item.get('source_file', ''),
                    owner_id=item.get('owner_id'),
                    is_released=bool(item.get('is_released')),
                    released_at=(
                        datetime.fromisoformat(item['released_at'])
                        if item.get('released_at') else None
                    ),
                    released_by=item.get('released_by'),
                    release_dir=item.get('release_dir', ''),
                    version_description=item.get('version_description', ''),
                    recorded_at=(
                        datetime.fromisoformat(item['recorded_at'])
                        if item.get('recorded_at') else timezone.now()
                    ),
                    extra_fields=json.dumps(item.get('extra_fields', {}), ensure_ascii=False) if item.get('extra_fields') else None,
                )
                rec.save(using=db_name)
                restored += 1

            return JsonResponse({
                'ok': True,
                'rolled_back_to': snap.to_dict(),
                'pre_rollback_snapshot': pre_snap.to_dict(),
                'restored_count': restored,
                'skipped_count': skipped,
            })
        except DataSnapshot.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


# =========================================================================
# Admin API - 备份管理
# =========================================================================

@login_required
def admin_review_hierarchy_status(request):
    """Read-only hierarchy config validation and database reconciliation status."""
    if not (request.user.is_admin or request.user.is_owner):
        return JsonResponse({'error': '无权限'}, status=403)
    if request.method != 'GET':
        return JsonResponse({'error': '只读接口仅支持 GET'}, status=405)
    payload = hierarchy_status()
    payload['permissions'] = {'can_edit_module_owner': request.user.is_admin}
    payload['owner_options'] = (
        [
            {
                'id': user.id,
                'username': user.username,
                'display_name': user.display_name or user.username,
            }
            for user in User.objects.filter(
                role=User.ROLE_OWNER,
                is_active=True,
            ).order_by('username')
        ]
        if request.user.is_admin
        else []
    )
    return JsonResponse(payload)


@login_required
def admin_review_hierarchy_module_owner(request):
    """Admin-only canonical DB + YAML release-owner update."""
    if not request.user.is_admin:
        return JsonResponse({'error': '仅管理员可修改评审层级 Owner'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': '仅支持 POST'}, status=405)
    try:
        data = json.loads(request.body or '{}')
    except (TypeError, json.JSONDecodeError):
        return JsonResponse({'error': '请求体必须是有效 JSON'}, status=400)
    try:
        result = update_module_release_owner(
            data.get('project'),
            data.get('group'),
            data.get('module'),
            data.get('owner_id'),
            expected_checksum=data.get('config_checksum'),
        )
    except HierarchyConfigError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    except HierarchyWriteError as exc:
        return JsonResponse(
            {'error': f'Owner 未保存：{exc}'},
            status=500,
        )
    except Exception:
        logger.exception('Unexpected review hierarchy owner update failure')
        return JsonResponse(
            {
                'error': (
                    'Owner 未保存：数据库或同步状态更新失败，'
                    '请检查服务日志并刷新状态后重试'
                )
            },
            status=500,
        )
    payload = hierarchy_status()
    payload['permissions'] = {'can_edit_module_owner': True}
    payload['owner_options'] = [
        {
            'id': user.id,
            'username': user.username,
            'display_name': user.display_name or user.username,
        }
        for user in User.objects.filter(
            role=User.ROLE_OWNER,
            is_active=True,
        ).order_by('username')
    ]
    return JsonResponse({'ok': True, 'updated': result, 'status': payload})


@login_required
def admin_list_backups(request):
    """List backups or create a verified manual backup."""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    if request.method == 'POST':
        result = backup_service.perform_backup('manual', request.user)
        return JsonResponse(result, status=201 if result.get('ok') else 500)
    backups = BackupRecord.objects.order_by('-created_at')[:100]
    return JsonResponse([b.to_dict() for b in backups], safe=False)


@login_required
def admin_verify_all_backups(request):
    """校验所有备份"""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    results = backup_service.verify_all_backups()
    return JsonResponse(results)


# =========================================================================
# Admin API - 模块管理
# =========================================================================

@login_required
def admin_create_module(request):
    """创建模块"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无创建模块权限'}, status=403)
    data = json.loads(request.body) if request.body else {}
    project_id = data.get('project_id')
    name = (data.get('name') or '').strip()
    if not project_id or not name:
        return JsonResponse({'error': '项目ID和模块名称不能为空'}, status=400)
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': '无效的 project_id'}, status=400)
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)
    get_object_or_404(Project, pk=pid)

    db_name = _get_project_db(pid)
    get_project_engine(pid)
    if Module.objects.using(db_name).filter(project_id=pid, name=name).exists():
        return JsonResponse({'error': '模块已存在'}, status=400)
    m = Module(
        project_id=pid,
        name=name,
        description=data.get('description', ''),
        owner_id=request.user.id,
        collaborators='[]',
    )
    m.save(using=db_name)
    return JsonResponse({'id': m.id, 'name': m.name, 'owner_id': m.owner_id})


@login_required
def admin_delete_module(request, module_id):
    """删除模块"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无删除模块权限'}, status=403)
    pid = _find_module_project_id(module_id)
    if pid is None:
        return JsonResponse({'error': '模块不存在'}, status=404)
    if not request.user.is_admin:
        return JsonResponse({'error': '仅 admin 可删除模块'}, status=403)

    db_name = _get_project_db(pid)
    get_project_engine(pid)
    m = get_object_or_404(Module.objects.using(db_name), pk=module_id)
    m.delete()
    return JsonResponse({'ok': True})


@login_required
def admin_batch_create_modules(request):
    """批量创建模块"""
    data = json.loads(request.body) if request.body else {}
    project_id = data.get('project_id')
    module_names = data.get('module_names', [])
    if isinstance(module_names, str):
        module_names = [n.strip() for n in module_names.replace(',', '\n').split('\n') if n.strip()]

    if not project_id:
        return JsonResponse({'error': '请选择项目'}, status=400)
    if not module_names:
        return JsonResponse({'error': '模块名称列表不能为空'}, status=400)
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': '无效的 project_id'}, status=400)
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)

    get_object_or_404(Project, pk=pid)
    db_name = _get_project_db(pid)
    get_project_engine(pid)

    created = []
    skipped = []
    for name in module_names:
        name = name.strip()
        if not name:
            continue
        if Module.objects.using(db_name).filter(project_id=pid, name=name).exists():
            skipped.append(name)
        else:
            m = Module(project_id=pid, name=name)
            m.save(using=db_name)
            created.append(name)

    return JsonResponse({
        'ok': True,
        'created_count': len(created),
        'skipped_count': len(skipped),
        'created': created,
        'skipped': skipped,
        'message': f'创建 {len(created)} 个模块' + (f'，跳过 {len(skipped)} 个已存在' if skipped else ''),
    })


# ---- 模块协作者管理 ----

@login_required
def admin_module_collaborators(request, module_id):
    """列出模块协作者 (GET) / 添加协作者 (POST)"""
    pid = _find_module_project_id(module_id)
    if pid is None:
        return JsonResponse({'error': '模块不存在'}, status=404)
    db_name = _get_project_db(pid)
    get_project_engine(pid)
    m = get_object_or_404(Module.objects.using(db_name), pk=module_id)

    if not (request.user.is_admin or m.can_be_managed_by(request.user)):
        return JsonResponse({'error': '无权限'}, status=403)

    # POST: 添加协作者
    if request.method == 'POST':
        data = json.loads(request.body) if request.body else {}
        user_id = data.get('user_id')
        if not user_id:
            return JsonResponse({'error': '缺少 user_id'}, status=400)
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            return JsonResponse({'error': '无效的 user_id'}, status=400)
        if not User.objects.filter(pk=user_id).exists():
            return JsonResponse({'error': '用户不存在'}, status=404)
        m.add_collaborator(user_id)
        m.save(using=db_name)
        return JsonResponse({
            'ok': True,
            'module_id': module_id,
            'collaborators': m.get_collaborator_ids(),
        })

    collab_ids = list(m.get_collaborator_ids())
    owner_id = m.owner_id
    user_ids = list(set(collab_ids + ([owner_id] if owner_id else [])))
    users = User.objects.filter(pk__in=user_ids) if user_ids else []
    user_map = {u.id: u for u in users}

    owner_info = None
    if owner_id and owner_id in user_map:
        o = user_map[owner_id]
        owner_info = {
            'id': o.id, 'username': o.username,
            'display_name': o.display_name or o.username, 'role': o.role,
        }
    collaborators = []
    for uid in collab_ids:
        if uid in user_map:
            u = user_map[uid]
            collaborators.append({
                'id': u.id, 'username': u.username,
                'display_name': u.display_name or u.username, 'role': u.role,
            })
    return JsonResponse({
        'module_id': module_id,
        'module_name': m.name,
        'owner': owner_info,
        'collaborators': collaborators,
    })


@login_required
def admin_remove_module_collaborator(request, module_id, user_id):
    """移除模块协作者"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无协作者管理权限'}, status=403)
    pid = _find_module_project_id(module_id)
    if pid is None:
        return JsonResponse({'error': '模块不存在'}, status=404)
    db_name = _get_project_db(pid)
    get_project_engine(pid)
    m = get_object_or_404(Module.objects.using(db_name), pk=module_id)
    if not (request.user.is_admin or m.owner_id == request.user.id):
        return JsonResponse({'error': '仅 admin 或模块创建者可管理协作者'}, status=403)
    if user_id not in m.get_collaborator_ids():
        return JsonResponse({'error': '该用户不在协作者列表中'}, status=400)
    m.remove_collaborator(user_id)
    m.save(using=db_name)
    return JsonResponse({
        'ok': True,
        'module_id': module_id,
        'collaborators': m.get_collaborator_ids(),
    })


# =========================================================================
# Admin API - 用户与记录管理
# =========================================================================

@login_required
def admin_list_owner_users(request):
    """列出 owner 角色用户"""
    if request.user.is_viewer:
        return JsonResponse({'error': '无权限'}, status=403)
    users = User.objects.filter(role='owner').order_by('username')
    return JsonResponse([{
        'id': u.id, 'username': u.username,
        'display_name': u.display_name or u.username,
    } for u in users], safe=False)


@login_required
def admin_delete_record(request, record_id):
    """删除记录"""
    if request.user.is_viewer:
        return JsonResponse({'error': '无权限 (viewer 角色不可删除)'}, status=403)

    explicit_project_id = request.GET.get('project_id', '').strip()
    if not explicit_project_id.isdigit():
        return JsonResponse({'error': 'project_id 必填且必须为整数'}, status=400)
    pid = int(explicit_project_id)
    if not Project.objects.filter(pk=pid).exists():
        return JsonResponse({'error': '项目不存在'}, status=404)
    get_project_engine(pid)
    db_name = _get_project_db(pid)
    r = QorRecord.objects.using(db_name).select_related('module').filter(
        pk=record_id,
        module__project_id=pid,
    ).first()
    if r is None:
        return JsonResponse({'error': '记录不存在'}, status=404)

    if not request.user.is_admin and not r.module.can_be_managed_by(request.user):
        return JsonResponse({'error': '无权限删除此记录'}, status=403)

    r.delete(using=db_name)
    return JsonResponse({'ok': True, 'project_id': pid, 'record_id': record_id})


@login_required
def admin_list_record_owners(request):
    """List uploaders (record owner_id) available for record-management filters."""
    if request.user.is_viewer:
        return JsonResponse({'error': '无权限'}, status=403)
    owner_ids = set()
    project_ids = _resolve_project_ids(request.GET.get('project_ids', ''))
    for pid in project_ids:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            ids = QorRecord.objects.using(db_name).filter(
                owner_id__isnull=False,
            ).values_list('owner_id', flat=True).distinct()
            owner_ids.update(ids)
        except Exception:
            continue
    if not owner_ids:
        return JsonResponse([], safe=False)
    users = User.objects.filter(pk__in=owner_ids).order_by('username')
    return JsonResponse([{
        'id': u.id,
        'username': u.username,
        'display_name': u.display_name or u.username,
    } for u in users], safe=False)


# =========================================================================
# Admin API - CSV 上传
# =========================================================================

@login_required
def admin_upload_csv(request):
    """上传 CSV 导入 QoR 数据 (支持多文件批量导入)"""
    if not request.user.is_admin and not request.user.is_owner:
        return JsonResponse({'error': '需要管理员或 owner 权限'}, status=403)

    project_id = request.POST.get('project_id')
    if not project_id:
        return JsonResponse({'error': '缺少 project_id'}, status=400)
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': '无效的 project_id'}, status=400)

    project = get_object_or_404(Project, pk=pid)
    blocked = _require_writable_project(project)
    if blocked:
        return blocked

    # 前端发送 'files' (复数), 兼容 'file' (单数)
    uploaded_files = request.FILES.getlist('files') or request.FILES.getlist('file')
    if not uploaded_files:
        # 尝试单个 file key
        if 'file' in request.FILES:
            uploaded_files = [request.FILES['file']]
        else:
            return JsonResponse({'error': '缺少上传文件'}, status=400)

    module_id = request.POST.get('module_id')
    version = request.POST.get('version', 'v1')
    mark_released = request.POST.get('mark_released', '').lower() in ('1', 'true', 'yes')
    release_dir = request.POST.get('release_dir', None)
    data_type = request.POST.get('data_type', 'qor')
    module_name_source = request.POST.get('module_name_source', 'csv')
    filename_suffixes = request.POST.get('filename_suffixes', '_qor,qor,_qor_report')
    full_dir = request.POST.get('full_dir', None)

    # 规范化 module_id: 空字符串视为 None
    if module_id is not None and str(module_id).strip() == '':
        module_id = None
    elif module_id is not None:
        try:
            module_id = int(module_id)
        except (ValueError, TypeError):
            module_id = None

    import logging as _logging
    _log = _logging.getLogger(__name__)
    _log.info("admin_upload_csv: project_id=%s, module_id=%s, version=%s, data_type=%s, file_count=%d",
              pid, module_id, version, data_type, len(uploaded_files))

    set_current_project_id(pid)
    db_name = _get_project_db(pid)
    get_project_engine(pid)

    file_results = []
    total_saved = 0
    total_updated = 0
    total_skipped = 0

    for f in uploaded_files:
        file_result = {
            'filename': f.name,
            'ok': True,
            'saved': 0,
            'updated': 0,
            'skipped': 0,
            'merged': 0,
            'stats': {'total_rows': 0, 'skipped_empty': 0, 'skipped_no_data': 0, 'errors': 0},
        }
        try:
            content = f.read().decode('utf-8-sig')
            reader = _csv.DictReader(_io.StringIO(content))
            rows = list(reader)
        except Exception as e:
            file_result['ok'] = False
            file_result['error'] = f'CSV 解析失败: {str(e)}'
            file_results.append(file_result)
            continue

        if not rows:
            file_result['stats']['total_rows'] = 0
            file_results.append(file_result)
            continue

        file_result['stats']['total_rows'] = len(rows)

        _log.info("admin_upload_csv: 文件=%s, 列名=%s, 行数=%d",
                  f.name, list(rows[0].keys()) if rows else [], len(rows))

        records = []
        for row in rows:
            rec = {}
            for k, v in row.items():
                key = k.strip().lower()
                rec[key] = v.strip() if v else ''
            records.append(rec)

        # 根据 data_type 调用不同的处理函数
        if data_type == 'power':
            merged, created = qor_import.merge_power_to_db(
                records, project, module_id, version, f.name,
                mark_released=mark_released, owner_id=request.user.id,
                current_user=request.user,
            )
            file_result['merged'] = merged
            file_result['saved'] = created
            total_saved += created
            total_updated += merged
        elif data_type == 'violation':
            saved, skipped = qor_import.save_violations_to_db(
                records, project, module_id, version, f.name,
            )
            file_result['saved'] = saved
            file_result['skipped'] = skipped
            total_saved += saved
            total_skipped += skipped
        elif data_type == 'notes':
            saved, skipped = qor_import.save_notes_to_db(
                records, project, module_id, version, f.name,
                full_dir=full_dir,
            )
            file_result['saved'] = saved
            file_result['skipped'] = skipped
            total_saved += saved
            total_skipped += skipped
        else:
            # data_type == 'qor'
            saved, skipped, updated = qor_import.save_records_to_db(
                records, project, module_id, version, f.name,
                mark_released=mark_released, owner_id=request.user.id,
                default_release_dir=release_dir, current_user=request.user,
            )
            file_result['saved'] = saved
            file_result['skipped'] = skipped
            file_result['updated'] = updated
            total_saved += saved
            total_skipped += skipped
            total_updated += updated

        file_results.append(file_result)

    return JsonResponse({
        'ok': True,
        'saved': total_saved,
        'updated': total_updated,
        'skipped': total_skipped,
        'total': sum(fr['stats']['total_rows'] for fr in file_results),
        'file_results': file_results,
        'data_type': data_type,
    })


@login_required
def admin_upload_block_qor(request):
    """上传 Block QoR CSV"""
    if not request.user.is_admin and not request.user.is_owner:
        return JsonResponse({'error': '需要管理员或 owner 权限'}, status=403)

    project_id = request.POST.get('project_id')
    if not project_id:
        return JsonResponse({'error': '缺少 project_id'}, status=400)
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': '无效的 project_id'}, status=400)

    project = get_object_or_404(Project, pk=pid)
    blocked = _require_writable_project(project)
    if blocked:
        return blocked

    # 前端发送 'files' (复数), 兼容 'file' (单数)
    uploaded_files = request.FILES.getlist('files') or request.FILES.getlist('file')
    if not uploaded_files:
        if 'file' in request.FILES:
            uploaded_files = [request.FILES['file']]
        else:
            return JsonResponse({'error': '缺少上传文件'}, status=400)

    f = uploaded_files[0]  # block_qor 只处理第一个文件
    db_name = _get_project_db(pid)
    get_project_engine(pid)

    try:
        content = f.read().decode('utf-8-sig')
        reader = _csv.DictReader(_io.StringIO(content))
        rows = list(reader)
    except Exception as e:
        return JsonResponse({'error': f'CSV 解析失败: {str(e)}'}, status=400)

    saved = 0
    skipped = 0
    errors = []
    for i, row in enumerate(rows):
        try:
            module_name = (row.get('module_name') or row.get('module') or '').strip()
            version = (row.get('version') or 'v1').strip()
            if not module_name:
                skipped += 1
                errors.append({'row': i + 1, 'error': '缺少 module_name'})
                continue

            module, _ = Module.objects.using(db_name).get_or_create(
                project_id=pid, name=module_name,
                defaults={'owner_id': request.user.id},
            )

            rec = QorRecord(
                module_id=module.id,
                version=version,
                full_dir=row.get('full_dir', '')[:500],
                area_total=_safe_float(row.get('area_total')),
                area_combinational=_safe_float(row.get('area_combinational')),
                area_sequential=_safe_float(row.get('area_sequential')),
                area_black_box=_safe_float(row.get('area_black_box')),
                area_macro=_safe_float(row.get('area_macro')),
                wns_setup=_safe_float(row.get('wns_setup')),
                tns_setup=_safe_float(row.get('tns_setup')),
                nvp_setup=_safe_int(row.get('nvp_setup')),
                wns_hold=_safe_float(row.get('wns_hold')),
                tns_hold=_safe_float(row.get('tns_hold')),
                nvp_hold=_safe_int(row.get('nvp_hold')),
                power_internal=_safe_float(row.get('power_internal')),
                power_switching=_safe_float(row.get('power_switching')),
                power_leakage=_safe_float(row.get('power_leakage')),
                power_total=_safe_float(row.get('power_total')),
                cell_count=_safe_int(row.get('cell_count')),
                owner_id=request.user.id,
                source_file=f.name,
            )
            rec.save(using=db_name)
            saved += 1
        except Exception as e:
            skipped += 1
            errors.append({'row': i + 1, 'error': str(e)})

    return JsonResponse({
        'ok': True,
        'saved': saved,
        'skipped': skipped,
        'errors': errors[:20],
        'total': len(rows),
    })


@login_required
def admin_upload_csv_preview(request):
    """预览 CSV 上传内容"""
    if not request.user.is_admin and not request.user.is_owner:
        return JsonResponse({'error': '需要管理员或 owner 权限'}, status=403)

    # 前端发送 'files' (复数), 兼容 'file' (单数)
    uploaded_files = request.FILES.getlist('files') or request.FILES.getlist('file')
    if not uploaded_files:
        if 'file' in request.FILES:
            uploaded_files = [request.FILES['file']]
        else:
            return JsonResponse({'error': '缺少上传文件'}, status=400)

    f = uploaded_files[0]  # 预览只处理第一个文件
    try:
        content = f.read().decode('utf-8-sig')
        reader = _csv.DictReader(_io.StringIO(content))
        rows = list(reader)
    except Exception as e:
        return JsonResponse({'error': f'CSV 解析失败: {str(e)}'}, status=400)

    if not rows:
        return JsonResponse({'error': 'CSV 文件为空'}, status=400)

    preview = rows[:20]
    columns = list(preview[0].keys()) if preview else []
    return JsonResponse({
        'ok': True,
        'total_rows': len(rows),
        'columns': columns,
        'preview': preview,
    })


def _safe_float(val):
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if val is None or val == '':
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


# =========================================================================
# Admin API - QoR 发布管理
# =========================================================================

@login_required
def admin_toggle_release(request, record_id):
    """切换记录发布状态"""
    data = json.loads(request.body) if request.body else {}
    explicit_project_id = data.get('project_id')
    if not str(explicit_project_id or '').isdigit():
        return JsonResponse({'error': 'project_id 必填且必须为整数'}, status=400)
    project_id = int(explicit_project_id)
    if not Project.objects.filter(pk=project_id).exists():
        return JsonResponse({'error': '项目不存在'}, status=404)

    new_release_dir = data.get('release_dir', None)

    db_name = _get_project_db(project_id)
    get_project_engine(project_id)
    r = get_object_or_404(
        QorRecord.objects.using(db_name).select_related('module'),
        pk=record_id,
        module__project_id=project_id,
    )

    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无发布权限'}, status=403)
    if not request.user.is_admin and not r.module.can_be_managed_by(request.user):
        return JsonResponse({'error': '无权限'}, status=403)

    r.is_released = not r.is_released
    if r.is_released:
        r.released_at = timezone.now()
        r.released_by = request.user.id
        if new_release_dir is not None:
            r.release_dir = new_release_dir.strip()[:500] if new_release_dir.strip() else None
    else:
        r.released_at = None
        r.released_by = None
        if new_release_dir is not None:
            r.release_dir = new_release_dir.strip()[:500] if new_release_dir.strip() else None

    r.save(using=db_name)
    return JsonResponse({
        'id': r.id,
        'is_released': r.is_released,
        'released_by': r.released_by,
        'released_at': r.released_at.isoformat() if r.released_at else None,
        'release_dir': r.release_dir or '',
        'release_dir_effective': r.release_dir or r.full_dir or '',
    })


@login_required
def admin_update_release_dir(request, record_id):
    """更新项目库记录的规范 release_dir；full_dir 保留原始 run 目录。"""
    data = json.loads(request.body) if request.body else {}
    explicit_project_id = data.get('project_id')
    if not str(explicit_project_id or '').isdigit():
        return JsonResponse({'error': 'project_id 必填且必须为整数'}, status=400)
    project_id = int(explicit_project_id)

    new_release_dir = data.get('release_dir', None)
    if new_release_dir is None or not isinstance(new_release_dir, str):
        return JsonResponse({'error': 'release_dir 必填且为字符串'}, status=400)
    if len(new_release_dir) > 500:
        return JsonResponse({'error': 'release_dir 长度不能超过 500'}, status=400)

    if not Project.objects.filter(pk=project_id).exists():
        return JsonResponse({'error': '项目不存在'}, status=404)
    db_name = _get_project_db(project_id)
    get_project_engine(project_id)
    r = get_object_or_404(
        QorRecord.objects.using(db_name).select_related('module'),
        pk=record_id,
        module__project_id=project_id,
    )

    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无发布权限'}, status=403)
    if not request.user.is_admin and not r.module.can_be_managed_by(request.user):
        return JsonResponse({'error': '无权限'}, status=403)

    # release_dir 是可编辑的规范发布目录；full_dir 是上传时的原始 run 目录，
    # 清空 release_dir 只恢复 full_dir fallback，不修改上传来源。
    cleaned = new_release_dir.strip()
    r.release_dir = cleaned
    r.save(using=db_name, update_fields=['release_dir'])
    return JsonResponse({
        'ok': True,
        'id': r.id,
        'project_id': project_id,
        'release_dir': r.release_dir or '',
        'release_dir_effective': r.release_dir or r.full_dir or '',
    })


@login_required
def admin_batch_update_release_dir(request):
    """Update release_dir per explicitly identified record across projects."""
    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无发布权限'}, status=403)

    data = json.loads(request.body) if request.body else {}
    items = data.get('items')
    shared_release_dir = data.get('release_dir')
    if not isinstance(items, list):
        return JsonResponse({'error': 'items 必须为数组'}, status=400)
    if not items:
        return JsonResponse({'error': '至少选择一条记录'}, status=400)
    if len(items) > 1000:
        return JsonResponse({'error': f'单次最多 1000 条, 当前 {len(items)} 条'}, status=400)
    if shared_release_dir is not None and not isinstance(shared_release_dir, str):
        return JsonResponse({'error': 'release_dir 必须为字符串'}, status=400)
    if isinstance(shared_release_dir, str) and len(shared_release_dir) > 500:
        return JsonResponse({'error': 'release_dir 长度不能超过 500'}, status=400)

    by_project = {}
    seen = set()
    for item in items:
        try:
            project_id = int(item['project_id'])
            record_id = int(item['record_id'])
        except (KeyError, TypeError, ValueError):
            return JsonResponse({
                'error': '每个 item 都必须包含整数 project_id 和 record_id',
            }, status=400)
        item_release_dir = item.get('release_dir', shared_release_dir)
        if not isinstance(item_release_dir, str):
            return JsonResponse({
                'error': '每个 item 必须包含字符串 release_dir，或提供顶层 release_dir',
            }, status=400)
        if len(item_release_dir) > 500:
            return JsonResponse({
                'error': (
                    f'项目 {project_id} 记录 {record_id} 的 release_dir '
                    '长度不能超过 500'
                ),
            }, status=400)
        identity = (project_id, record_id)
        if identity not in seen:
            by_project.setdefault(project_id, []).append(
                (record_id, item_release_dir.strip())
            )
            seen.add(identity)

    updated = 0
    skipped = 0
    failed = []
    for project_id, record_updates in by_project.items():
        record_ids = [record_id for record_id, _ in record_updates]
        if not Project.objects.filter(pk=project_id).exists():
            skipped += len(record_ids)
            failed.extend(
                {
                    'project_id': project_id,
                    'record_id': record_id,
                    'reason': '项目不存在',
                }
                for record_id in record_ids
            )
            continue

        db_name = _get_project_db(project_id)
        get_project_engine(project_id)
        records = QorRecord.objects.using(db_name).select_related('module').filter(
            pk__in=record_ids,
            module__project_id=project_id,
        )
        records_map = {record.id: record for record in records}
        writable_records = []
        for record_id, release_dir in record_updates:
            record = records_map.get(record_id)
            if not record:
                skipped += 1
                failed.append({
                    'project_id': project_id,
                    'record_id': record_id,
                    'reason': '记录不存在',
                })
                continue
            if (
                not request.user.is_admin
                and not record.module.can_be_managed_by(request.user)
            ):
                skipped += 1
                failed.append({
                    'project_id': project_id,
                    'record_id': record_id,
                    'reason': '无权限',
                })
                continue
            record.release_dir = release_dir
            writable_records.append(record)

        if writable_records:
            QorRecord.objects.using(db_name).bulk_update(
                writable_records, ['release_dir'],
            )
            updated += len(writable_records)

    return JsonResponse({
        'ok': True,
        'updated': updated,
        'skipped': skipped,
        'failed': failed,
        'release_dir': (
            shared_release_dir.strip()
            if isinstance(shared_release_dir, str)
            else None
        ),
    })


@login_required
def admin_update_version_description(request, record_id):
    """更新版本描述"""
    data = json.loads(request.body) if request.body else {}
    explicit_project_id = data.get('project_id')
    if not str(explicit_project_id or '').isdigit():
        return JsonResponse({'error': 'project_id 必填且必须为整数'}, status=400)
    pid = int(explicit_project_id)
    if not Project.objects.filter(pk=pid).exists():
        return JsonResponse({'error': '项目不存在'}, status=404)
    desc = (data.get('description') or '').strip()

    db_name = _get_project_db(pid)
    get_project_engine(pid)
    r = get_object_or_404(
        QorRecord.objects.using(db_name),
        pk=record_id,
        module__project_id=pid,
    )

    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)

    r.version_description = desc or None
    r.save(using=db_name)
    return JsonResponse({
        'ok': True,
        'id': r.id,
        'version_description': r.version_description or '',
    })


@login_required
def admin_batch_release(request):
    """批量发布/取消发布"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无发布权限'}, status=403)

    data = json.loads(request.body) if request.body else {}
    items = data.get('items')
    record_ids = data.get('record_ids')
    if items is None and record_ids is None:
        return JsonResponse({'error': 'items 必填'}, status=400)
    if items is not None and not isinstance(items, list):
        return JsonResponse({'error': 'items 必须为数组'}, status=400)
    if items is None and not isinstance(record_ids, list):
        return JsonResponse({'error': 'record_ids 必须为数组'}, status=400)
    requested_count = len(items if items is not None else record_ids)
    if not requested_count:
        return JsonResponse({'error': '至少选择一条记录'}, status=400)
    if requested_count > 1000:
        return JsonResponse({'error': f'单次最多 1000 条, 当前 {requested_count} 条'}, status=400)

    released = bool(data.get('released', True))
    batch_release_dir = data.get('release_dir', '__NOT_PROVIDED__')

    updated = 0
    skipped = 0
    failed = []

    by_project = {}
    seen = set()
    if items is not None:
        for item in items:
            try:
                pid = int(item['project_id'])
                rid = int(item['record_id'])
            except (KeyError, TypeError, ValueError):
                return JsonResponse({
                    'error': '每个 item 都必须包含整数 project_id 和 record_id'
                }, status=400)
            identity = (pid, rid)
            if identity not in seen:
                by_project.setdefault(pid, []).append(rid)
                seen.add(identity)
    else:
        # Legacy bare IDs are accepted only when each ID exists in exactly one
        # project. Ambiguous IDs fail the whole request before any mutation.
        for raw_id in record_ids:
            try:
                rid = int(raw_id)
            except (TypeError, ValueError):
                return JsonResponse({'error': 'record_ids 必须只包含整数'}, status=400)
            projects = _find_qor_record_projects(rid)
            if len(projects) != 1:
                return JsonResponse({
                    'error': f'记录 ID {rid} 跨项目不唯一或不存在，请使用 items'
                }, status=409)
            by_project.setdefault(projects[0], []).append(rid)

    for pid, rids in by_project.items():
        if not Project.objects.filter(pk=pid).exists():
            skipped += len(rids)
            failed.extend(
                {'project_id': pid, 'record_id': rid, 'reason': '项目不存在'} for rid in rids
            )
            continue
        db_name = _get_project_db(pid)
        get_project_engine(pid)
        records = QorRecord.objects.using(db_name).select_related('module').filter(
            pk__in=rids,
            module__project_id=pid,
        )
        records_map = {r.id: r for r in records}

        for rid in rids:
            r = records_map.get(rid)
            if not r:
                skipped += 1
                failed.append({'project_id': pid, 'record_id': rid, 'reason': '记录不存在'})
                continue

            if not request.user.is_admin and not r.module.can_be_managed_by(request.user):
                skipped += 1
                failed.append({'project_id': pid, 'record_id': rid, 'reason': '无权限'})
                continue

            r.is_released = released
            if released:
                r.released_at = timezone.now()
                r.released_by = request.user.id
                if batch_release_dir != '__NOT_PROVIDED__':
                    r.release_dir = batch_release_dir.strip()[:500] if batch_release_dir.strip() else None
            else:
                r.released_at = None
                r.released_by = None
                if batch_release_dir != '__NOT_PROVIDED__':
                    r.release_dir = batch_release_dir.strip()[:500] if batch_release_dir.strip() else None
            r.save(using=db_name)
            updated += 1

    return JsonResponse({
        'ok': True,
        'updated': updated,
        'skipped': skipped,
        'failed': failed,
    })


# =========================================================================
# Admin API - 用户管理
# =========================================================================

@login_required
def admin_list_users(request):
    """列出所有用户 (GET) / 创建单个用户 (POST)"""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)

    if request.method == 'POST':
        data = json.loads(request.body) if request.body else {}
        username = (data.get('username') or '').strip()
        password = data.get('password', '')
        role = data.get('role', 'owner')
        display_name = (data.get('display_name') or '').strip()

        if not username or not password:
            return JsonResponse({'error': '用户名和密码不能为空'}, status=400)
        if role not in ('admin', 'owner', 'viewer'):
            return JsonResponse({'error': '无效的角色'}, status=400)
        if User.objects.filter(username=username).exists():
            return JsonResponse({'error': '用户名已存在'}, status=400)

        user = User(username=username, role=role, display_name=display_name)
        user.set_password(password)
        user.save()
        return JsonResponse({
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name,
        })

    users = User.objects.order_by('created_at')
    return JsonResponse([{
        'id': u.id,
        'username': u.username,
        'role': u.role,
        'display_name': u.display_name,
        'created_at': u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else '',
    } for u in users], safe=False)


@login_required
def admin_batch_create_users(request):
    """批量创建用户"""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    data = json.loads(request.body) if request.body else {}

    raw = data.get('usernames', [])
    if isinstance(raw, str):
        usernames = [u.strip() for u in re.split(r'[\n,;\s]+', raw) if u.strip()]
    else:
        usernames = [str(u).strip() for u in raw if str(u).strip()]

    if not usernames:
        return JsonResponse({'error': '用户名列表不能为空'}, status=400)

    password = data.get('password') or '123456'
    role = data.get('role', 'owner')
    if role not in ('admin', 'owner', 'viewer'):
        return JsonResponse({'error': '无效的角色'}, status=400)

    created = []
    skipped = []
    existing = set(User.objects.filter(username__in=usernames).values_list('username', flat=True))

    for uname in usernames:
        if uname in existing:
            skipped.append({'username': uname, 'reason': '用户名已存在'})
            continue
        user = User(username=uname, role=role)
        user.set_password(password)
        try:
            user.save()
            created.append({'id': user.id, 'username': uname})
            existing.add(uname)
        except Exception as e:
            skipped.append({'username': uname, 'reason': str(e)})

    return JsonResponse({
        'created': created,
        'skipped': skipped,
        'total': len(usernames),
        'default_password': password,
    })


@login_required
def admin_reset_user_password(request, user_id):
    """重置用户密码"""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)

    data = json.loads(request.body) if request.body else {}
    new_password = (data.get('password') or '').strip() or 'Reset@123'

    # Serialize reset/change operations for one account and write only the
    # credential columns.  A request that loaded the same User earlier must
    # not be able to restore an old password while saving unrelated profile
    # state.
    with transaction.atomic():
        try:
            user = User.objects.select_for_update().get(pk=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': '用户不存在'}, status=404)
        user.set_password(new_password)
        user.must_change_password = True
        user.password_changed_at = None
        user.save(update_fields=[
            'password', 'must_change_password', 'password_changed_at',
        ])
    return JsonResponse({
        'ok': True,
        'username': user.username,
        'reset_to': new_password,
        'must_change_password': True,
    })


@api_auth_required()
@csrf_exempt
def user_change_own_password(request):
    """修改自己的密码"""
    data = json.loads(request.body) if request.body else {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return JsonResponse({'error': '旧密码和新密码不能为空'}, status=400)
    if old_password == new_password:
        return JsonResponse({'error': '新密码不能与旧密码相同'}, status=400)

    from django_app.core.security import validate_password
    ok, err = validate_password(new_password)
    if not ok:
        return JsonResponse({'error': err or '密码强度不足'}, status=400)

    # Re-read and lock the account instead of persisting the request's
    # potentially stale User instance.  This makes reset -> forced change
    # atomic with respect to another reset/change and limits the UPDATE to
    # password lifecycle fields.
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not user.check_password(old_password):
            return JsonResponse({'error': '旧密码错误'}, status=400)
        user.set_password(new_password)
        user.must_change_password = False
        user.password_changed_at = timezone.now()
        user.save(update_fields=[
            'password', 'must_change_password', 'password_changed_at',
        ])

    request.user = user
    update_session_auth_hash(request, user)
    return JsonResponse({'ok': True, 'must_change_password': False})


# =========================================================================
# API v1 - 认证
# =========================================================================

@csrf_exempt
def api_v1_login(request):
    """API v1 登录"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    data = json.loads(request.body) if request.body else {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return JsonResponse({'error': '用户名和密码不能为空'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': '用户名或密码错误'}, status=401)

    if not user.is_active or not user.check_password(password):
        return JsonResponse({'error': '用户名或密码错误'}, status=401)

    # 创建 Django session，确保 @login_required 端点能识别已认证用户
    login(request, user)
    # login() rotates Django's CSRF secret. Mark the new token as used so
    # CsrfViewMiddleware emits the csrftoken cookie with this response.
    get_token(request)

    plaintext = ApiKey.generate_key()
    api_key = ApiKey(
        user=user,
        key_hash=ApiKey.hash_key(plaintext),
        prefix=plaintext[:12],
        name=f'login-token-{timezone.now().strftime("%Y%m%d%H%M%S")}',
        scopes='read,upload',
        expires_at=timezone.now() + timedelta(days=7),
    )
    api_key.save()

    return JsonResponse({
        'api_key': plaintext,
        'api_key_id': api_key.id,
        'must_change_password': user.must_change_password,
        'user': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name,
            'is_admin': user.is_admin,
            'is_owner': user.is_owner,
            'is_release': user.is_release,
            'is_viewer': user.is_viewer,
        },
    })


@api_auth_required()
def api_v1_me(request):
    """API v1 当前用户信息"""
    user = request.user
    # Re-establish the AJAX CSRF cookie when restoring an existing session.
    get_token(request)
    return JsonResponse({
        'user': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name,
            'is_admin': user.is_admin,
            'is_owner': user.is_owner,
            'is_release': user.is_release,
            'is_viewer': user.is_viewer,
        },
        'must_change_password': user.must_change_password,
        'auth_method': getattr(request, 'auth_method', 'session'),
    })


@login_required
def api_v1_logout(request):
    """End the browser session without revoking independent API keys."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    logout(request)
    return JsonResponse({'ok': True})


# =========================================================================
# API v1 - 项目管理
# =========================================================================

@api_auth_required()
def api_v1_list_projects(request):
    """API v1 列出项目"""
    user = request.user
    projects = Project.objects.order_by('created_at')
    result = []
    for p in projects:
        if user.is_viewer and p.status == 'hidden':
            continue
        try:
            db_name = _get_project_db(p.id)
            get_project_engine(p.id)
            module_count = Module.objects.using(db_name).filter(project_id=p.id).count()
        except Exception:
            module_count = 0
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'module_count': module_count,
        })
    return JsonResponse(result, safe=False)


@api_auth_required()
def api_v1_get_project(request, project_id):
    """API v1 获取项目详情"""
    user = request.user
    p = get_object_or_404(Project, pk=project_id)
    db_name = _get_project_db(project_id)
    get_project_engine(project_id)
    modules = Module.objects.using(db_name).filter(project_id=project_id).order_by('name')
    return JsonResponse({
        'id': p.id, 'name': p.name, 'description': p.description,
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'modules': [{
            'id': m.id, 'name': m.name, 'description': m.description,
            'record_count': QorRecord.objects.using(db_name).filter(module_id=m.id).count(),
        } for m in modules],
    })


# =========================================================================
# API v1 - 项目成员管理
# =========================================================================

@api_auth_required()
def api_v1_list_members(request, project_id):
    """API v1 列出项目成员"""
    user = request.user
    members = ProjectMember.objects.filter(project_id=project_id)
    return JsonResponse([m.to_dict() for m in members], safe=False)


@api_auth_required()
def api_v1_remove_member(request, project_id, member_id):
    """API v1 移除项目成员"""
    user = request.user
    if not user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)
    m = get_object_or_404(ProjectMember, pk=member_id, project_id=project_id)
    if m.role == 'owner':
        owners = ProjectMember.objects.filter(project_id=project_id, role='owner').count()
        if owners <= 1:
            return JsonResponse({'error': '不能移除最后一个 owner'}, status=400)
    m.delete()
    return JsonResponse({'ok': True})


# =========================================================================
# API v1 - 数据锁
# =========================================================================

@api_auth_required()
def api_v1_list_locks(request):
    """API v1 列出数据锁"""
    resource_type = request.GET.get('resource_type')
    resource_id = request.GET.get('resource_id')
    if resource_id:
        try:
            resource_id = int(resource_id)
        except (ValueError, TypeError):
            resource_id = None
    q = DataLock.objects.all()
    if resource_type:
        q = q.filter(resource_type=resource_type)
    if resource_id:
        q = q.filter(resource_id=resource_id)
    locks = q.order_by('-locked_at')
    return JsonResponse([l.to_dict() for l in locks if not l.is_expired], safe=False)


@api_auth_required()
def api_v1_release_lock(request, lock_id):
    """API v1 释放数据锁"""
    user = request.user
    lock = get_object_or_404(DataLock, pk=lock_id)
    if lock.locked_by_id != user.id and not user.is_admin:
        return JsonResponse({'error': '只能释放自己持有的锁'}, status=403)
    lock.delete()
    return JsonResponse({'ok': True})


# =========================================================================
# API v1 - API Key 管理
# =========================================================================

@api_auth_required()
def api_v1_list_apikeys(request):
    """API v1 列出 API Key"""
    user = request.user
    keys = ApiKey.objects.filter(user=user).order_by('-created_at')
    return JsonResponse([k.to_dict() for k in keys], safe=False)


@api_auth_required()
def api_v1_revoke_apikey(request, key_id):
    """API v1 撤销 API Key"""
    user = request.user
    k = get_object_or_404(ApiKey, pk=key_id, user=user)
    k.revoked = True
    k.save(update_fields=['revoked'])
    return JsonResponse({'ok': True})


# =========================================================================
# API v1 - 上传
# =========================================================================

@csrf_exempt
@api_auth_required(required_scope='upload')
def api_v1_upload(request):
    """API v1 上传 CSV"""
    user = request.user
    project_id = request.POST.get('project_id')
    if not project_id:
        return JsonResponse({'error': '缺少 project_id'}, status=400)
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': '无效的 project_id'}, status=400)

    project = get_object_or_404(Project, pk=pid)
    blocked = _require_writable_project(project)
    if blocked:
        return blocked
    if 'file' not in request.FILES:
        return JsonResponse({'error': '缺少上传文件'}, status=400)

    f = request.FILES['file']
    module_id = request.POST.get('module_id')
    version = request.POST.get('version', 'v1')
    mark_released = request.POST.get('mark_released', '').lower() in ('1', 'true', 'yes')

    set_current_project_id(pid)
    db_name = _get_project_db(pid)
    get_project_engine(pid)

    try:
        content = f.read().decode('utf-8-sig')
        reader = _csv.DictReader(_io.StringIO(content))
        rows = list(reader)
    except Exception as e:
        return JsonResponse({'error': f'CSV 解析失败: {str(e)}'}, status=400)

    records = []
    for row in rows:
        rec = {}
        for k, v in row.items():
            rec[k.strip().lower()] = v.strip() if v else ''
        records.append(rec)

    saved, skipped, updated = qor_import.save_records_to_db(
        records, project, module_id, version, f.name,
        mark_released=mark_released, owner_id=user.id,
        current_user=user,
    )

    return JsonResponse({
        'ok': True,
        'saved': saved,
        'updated': updated,
        'skipped': skipped,
        'total': len(records),
    })


@csrf_exempt
@api_auth_required(required_scope='upload')
def api_v1_qor_upload_json(request):
    """API v1 上传 JSON QoR 数据"""
    user = request.user
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'error': '无效的 JSON 格式'}, status=400)

    try:
        json_upload.validate_upload_json(data)
    except json_upload.JSONUploadError as e:
        return JsonResponse({'error': str(e), 'path': e.path}, status=e.status_code)

    upload_info = data.get('upload', {})
    pid = upload_info.get('project_id')
    version = upload_info.get('version', 'v1')
    module_id = upload_info.get('module_id')
    mark_released = upload_info.get('mark_released', False)

    project = get_object_or_404(Project, pk=pid)
    blocked = _require_writable_project(project)
    if blocked:
        return blocked
    set_current_project_id(pid)
    db_name = _get_project_db(pid)
    get_project_engine(pid)

    qor_records = json_upload.json_to_qor_records(data, default_version=version)
    saved, skipped, updated = qor_import.save_records_to_db(
        qor_records, project, module_id, version, 'json_upload',
        mark_released=mark_released, owner_id=user.id,
        current_user=user,
    )

    violations = json_upload.json_to_violation_records(data, default_version=version)
    vp_saved, vp_skipped = qor_import.save_violations_to_db(
        violations, project, module_id, version, 'json_upload',
    )

    notes = json_upload.json_to_notes_records(data)
    n_saved, n_skipped = qor_import.save_notes_to_db(
        notes, project, module_id, version, 'json_upload',
    )

    return JsonResponse({
        'ok': True,
        'records': {'saved': saved, 'updated': updated, 'skipped': skipped},
        'violations': {'saved': vp_saved, 'skipped': vp_skipped},
        'notes': {'saved': n_saved, 'skipped': n_skipped},
    })


# =========================================================================
# API v1 - 告警
# =========================================================================

@api_auth_required()
def api_v1_list_alert_rules(request):
    """API v1 列出告警规则"""
    user = request.user
    project_id = request.GET.get('project_id')
    if project_id:
        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            project_id = None

    items = []
    for pid in _resolve_project_ids():
        if project_id and pid != project_id:
            continue
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            q = AlertRule.objects.using(db_name).all()
            if project_id:
                q = q.filter(project_id=project_id)
            items.extend([r.to_dict() for r in q.order_by('-created_at')[:500]])
        except Exception:
            continue
    return JsonResponse(items, safe=False)


@api_auth_required()
def api_v1_modify_alert_rule(request, rule_id):
    """API v1 修改/删除告警规则"""
    user = request.user
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            rule = AlertRule.objects.using(db_name).get(pk=rule_id)
            if request.method == 'DELETE':
                if not user.is_admin:
                    return JsonResponse({'error': '无权限'}, status=403)
                rule.delete()
                return JsonResponse({'ok': True})
            data = json.loads(request.body) if request.body else {}
            for field in ('metric', 'direction', 'threshold', 'window_size', 'sensitivity', 'enabled', 'module_id'):
                if field in data:
                    setattr(rule, field, data[field])
            rule.save(using=db_name)
            return JsonResponse(rule.to_dict())
        except AlertRule.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@api_auth_required()
def api_v1_list_alert_events(request):
    """API v1 列出告警事件"""
    user = request.user
    project_id = request.GET.get('project_id')
    if project_id:
        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            project_id = None
    acknowledged = request.GET.get('acknowledged')
    try:
        limit = int(request.GET.get('limit', 100))
    except (ValueError, TypeError):
        limit = 100
    limit = min(limit, 500)

    items = []
    for pid in _resolve_project_ids():
        if project_id and pid != project_id:
            continue
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            q = AlertEvent.objects.using(db_name).select_related('rule')
            if project_id:
                q = q.filter(rule__project_id=project_id)
            if acknowledged == 'true':
                q = q.filter(acknowledged_by__isnull=False)
            elif acknowledged == 'false':
                q = q.filter(acknowledged_by__isnull=True)
            items.extend([e.to_dict() for e in q.order_by('-triggered_at')[:limit]])
        except Exception:
            continue
    return JsonResponse(items, safe=False)


@api_auth_required()
def api_v1_acknowledge_event(request, event_id):
    """API v1 确认告警事件"""
    user = request.user
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            ev = AlertEvent.objects.using(db_name).get(pk=event_id)
            ev.acknowledged_by = user.id
            ev.acknowledged_at = timezone.now()
            ev.save()
            return JsonResponse(ev.to_dict())
        except AlertEvent.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


# =========================================================================
# Violations API
# =========================================================================

@login_required
def api_get_violations(request):
    """查询违例路径"""
    record_id = request.GET.get('record_id')
    if record_id:
        try:
            record_id = int(record_id)
        except (ValueError, TypeError):
            record_id = None
    timing_group = request.GET.get('timing_group', '')
    try:
        limit = int(request.GET.get('limit', 200))
    except (ValueError, TypeError):
        limit = 200
    limit = min(limit, 1000)

    pid = _find_qor_record_project(record_id) if record_id else None
    if pid is None and record_id:
        return JsonResponse([], safe=False)

    if pid:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            q = ViolationPath.objects.using(db_name).all()
            if record_id:
                q = q.filter(qor_record_id=record_id)
            if timing_group:
                q = q.filter(timing_group=timing_group)
            paths = q.order_by('slack')[:limit]
            return JsonResponse([p.to_dict() for p in paths], safe=False)
        except Exception:
            return JsonResponse([], safe=False)

    items = []
    for p in _resolve_project_ids():
        db_name = _get_project_db(p)
        try:
            get_project_engine(p)
            q = ViolationPath.objects.using(db_name).all()
            if record_id:
                q = q.filter(qor_record_id=record_id)
            if timing_group:
                q = q.filter(timing_group=timing_group)
            items.extend([vp.to_dict() for vp in q.order_by('slack')[:limit]])
        except Exception:
            continue
    return JsonResponse(items, safe=False)


@login_required
def api_get_violation_source_files(request):
    """获取违例的源文件列表"""
    record_id = request.GET.get('record_id')
    if record_id:
        try:
            record_id = int(record_id)
        except (ValueError, TypeError):
            record_id = None

    pid = _find_qor_record_project(record_id) if record_id else None
    if pid is None and record_id:
        return JsonResponse([], safe=False)

    if pid:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            q = ViolationPath.objects.using(db_name)
            if record_id:
                q = q.filter(qor_record_id=record_id)
            files = sorted(set(p.source_file for p in q if p.source_file))
            return JsonResponse(files, safe=False)
        except Exception:
            return JsonResponse([], safe=False)

    files = set()
    for p in _resolve_project_ids():
        db_name = _get_project_db(p)
        try:
            get_project_engine(p)
            q = ViolationPath.objects.using(db_name)
            if record_id:
                q = q.filter(qor_record_id=record_id)
            for vp in q:
                if vp.source_file:
                    files.add(vp.source_file)
        except Exception:
            continue
    return JsonResponse(sorted(files), safe=False)


@login_required
def api_violations_diff(request):
    """违例对比"""
    base_id = request.GET.get('base_record_id')
    target_id = request.GET.get('target_record_id')
    try:
        base_id = int(base_id) if base_id else None
        target_id = int(target_id) if target_id else None
    except (ValueError, TypeError):
        base_id = None
        target_id = None
    if not base_id or not target_id:
        return JsonResponse({'error': 'base_record_id, target_record_id 必填'}, status=400)

    pid_base = _find_qor_record_project(base_id)
    pid_target = _find_qor_record_project(target_id)

    base_paths = []
    target_paths = []
    if pid_base:
        db_name = _get_project_db(pid_base)
        try:
            get_project_engine(pid_base)
            base_paths = list(ViolationPath.objects.using(db_name).filter(qor_record_id=base_id))
        except Exception:
            pass
    if pid_target:
        db_name = _get_project_db(pid_target)
        try:
            get_project_engine(pid_target)
            target_paths = list(ViolationPath.objects.using(db_name).filter(qor_record_id=target_id))
        except Exception:
            pass

    def _key(p):
        return (p.startpoint, p.endpoint, p.timing_group)

    base_set = {_key(p): p for p in base_paths}
    target_set = {_key(p): p for p in target_paths}

    new_keys = set(target_set) - set(base_set)
    removed_keys = set(base_set) - set(target_set)
    common_keys = set(base_set) & set(target_set)

    return JsonResponse({
        'new_count': len(new_keys),
        'removed_count': len(removed_keys),
        'common_count': len(common_keys),
        'new': [target_set[k].to_dict() for k in list(new_keys)[:100]],
        'removed': [base_set[k].to_dict() for k in list(removed_keys)[:100]],
        'common': [target_set[k].to_dict() for k in list(common_keys)[:100]],
    })


@login_required
def api_get_timing_groups(request):
    """获取违例的 timing group 列表"""
    record_id = request.GET.get('record_id')
    if record_id:
        try:
            record_id = int(record_id)
        except (ValueError, TypeError):
            record_id = None

    pid = _find_qor_record_project(record_id) if record_id else None
    if pid is None and record_id:
        return JsonResponse([], safe=False)

    if pid:
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            q = ViolationPath.objects.using(db_name)
            if record_id:
                q = q.filter(qor_record_id=record_id)
            groups = sorted(set(p.timing_group for p in q if p.timing_group))
            return JsonResponse(groups, safe=False)
        except Exception:
            return JsonResponse([], safe=False)

    groups = set()
    for p in _resolve_project_ids():
        db_name = _get_project_db(p)
        try:
            get_project_engine(p)
            q = ViolationPath.objects.using(db_name)
            if record_id:
                q = q.filter(qor_record_id=record_id)
            for vp in q:
                if vp.timing_group:
                    groups.add(vp.timing_group)
        except Exception:
            continue
    return JsonResponse(sorted(groups), safe=False)


@login_required
def api_get_violation_summary(request):
    """违例摘要"""
    record_id = request.GET.get('record_id')
    if record_id:
        try:
            record_id = int(record_id)
        except (ValueError, TypeError):
            record_id = None
    if not record_id:
        return JsonResponse({'error': 'record_id 必填'}, status=400)

    pid = _find_qor_record_project(record_id)
    if pid is None:
        return JsonResponse({'error': '记录不存在'}, status=404)

    db_name = _get_project_db(pid)
    get_project_engine(pid)
    paths = ViolationPath.objects.using(db_name).filter(qor_record_id=record_id)
    if not paths:
        return JsonResponse({'total': 0, 'by_group': {}, 'worst_slack': None})

    by_group = {}
    for p in paths:
        by_group.setdefault(p.timing_group, []).append(p)

    summary = {
        'total': len(paths),
        'by_group': {
            g: {
                'count': len(items),
                'worst_slack': min((p.slack for p in items if p.slack is not None), default=None),
                'avg_slack': sum(p.slack for p in items if p.slack is not None) /
                             sum(1 for p in items if p.slack is not None) if any(
                    p.slack is not None for p in items) else None,
            } for g, items in by_group.items()
        },
        'worst_slack': min((p.slack for p in paths if p.slack is not None), default=None),
    }
    return JsonResponse(summary)


# =========================================================================
# Tools API
# =========================================================================

def _extract_source_files(data):
    """从 JSON 数据中提取所有 source_file 路径"""
    files = []

    def _walk(obj, parent_key='', depth=0):
        if depth > 10:
            return
        if isinstance(obj, dict):
            sf = obj.get('source_file')
            if sf and isinstance(sf, str) and sf.strip():
                mn = obj.get('module_name', '')
                files.append({
                    'index': len(files),
                    'module_name': str(mn) if mn else '',
                    'source_file': sf.strip(),
                })
            for k, v in obj.items():
                if k == 'source_file':
                    continue
                _walk(v, k, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, parent_key, depth + 1)

    _walk(data)

    seen = set()
    unique = []
    for f in files:
        if f['source_file'] not in seen:
            seen.add(f['source_file'])
            unique.append(f)
    for i, f in enumerate(unique):
        f['index'] = i

    return unique


@login_required
def api_tools_source_files_check(request):
    """检查 source file 是否存在"""
    try:
        body = json.loads(request.body) if request.body else None
        if not body:
            return JsonResponse({'ok': False, 'error': '请求体为空或非 JSON 格式'}, status=400)

        json_text = body.get('json_content', '')
        if not json_text or not json_text.strip():
            return JsonResponse({'ok': False, 'error': 'JSON 内容为空'}, status=400)

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            return JsonResponse({
                'ok': False,
                'error': f'JSON 解析失败: {e.msg} (位置: 行 {e.lineno}, 列 {e.colno})',
            }, status=400)

        files = _extract_source_files(data)

        if not files:
            return JsonResponse({
                'ok': True,
                'total': 0,
                'files': [],
                'warning': '未在 JSON 中找到任何 source_file 字段',
            })

        for f in files:
            path = f.get('source_file', '')
            if not path:
                f['exists'] = False
                f['size'] = None
                f['is_dir'] = False
                f['error'] = '路径为空'
                continue

            try:
                expanded = os.path.expanduser(path)
                if os.path.exists(expanded):
                    f['exists'] = True
                    f['is_dir'] = os.path.isdir(expanded)
                    if not f['is_dir']:
                        f['size'] = os.path.getsize(expanded)
                    else:
                        f['size'] = None
                    f['error'] = None
                    f['resolved_path'] = os.path.abspath(expanded)
                else:
                    f['exists'] = False
                    f['size'] = None
                    f['is_dir'] = False
                    f['error'] = '文件不存在'
                    f['resolved_path'] = os.path.abspath(expanded)
            except Exception as e:
                f['exists'] = False
                f['size'] = None
                f['is_dir'] = False
                f['error'] = f'路径检查异常: {str(e)}'
                f['resolved_path'] = path

        return JsonResponse({
            'ok': True,
            'total': len(files),
            'files': files,
        })

    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'服务器内部错误: {str(e)}'}, status=500)


@login_required
def api_tools_source_files_open(request):
    """打开源文件内容"""
    file_path = request.GET.get('path', '').strip()
    if not file_path:
        return JsonResponse({'ok': False, 'error': '缺少 path 参数'}, status=400)

    encoding = request.GET.get('encoding', 'utf-8').strip()

    try:
        expanded = os.path.expanduser(file_path)
        if not os.path.exists(expanded):
            return JsonResponse({'ok': False, 'error': f'文件不存在: {file_path}'}, status=404)

        if os.path.isdir(expanded):
            return JsonResponse({'ok': False, 'error': f'路径是目录而非文件: {file_path}'}, status=400)

        max_size = 50 * 1024 * 1024
        if os.path.getsize(expanded) > max_size:
            return JsonResponse({
                'ok': False,
                'error': f'文件过大 ({os.path.getsize(expanded)} bytes), 最大支持 50MB',
            }, status=400)

        with open(expanded, 'rb') as f:
            chunk = f.read(8192)
        if b'\x00' in chunk:
            return JsonResponse({
                'ok': False,
                'error': '文件可能是二进制格式, 无法在浏览器中显示',
            }, status=400)

        with open(expanded, 'r', encoding=encoding, errors='replace') as f:
            content = f.read()

        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'inline; filename="{os.path.basename(expanded)}"'
        response['X-Source-Path'] = os.path.abspath(expanded)
        response['X-File-Size'] = str(os.path.getsize(expanded))
        return response

    except UnicodeDecodeError:
        fallback_encodings = ['gbk', 'latin-1', 'cp1252']
        for enc in fallback_encodings:
            try:
                with open(expanded, 'r', encoding=enc, errors='replace') as f:
                    content = f.read()
                response = HttpResponse(content, content_type=f'text/plain; charset={enc}')
                response['Content-Disposition'] = f'inline; filename="{os.path.basename(expanded)}"'
                response['X-Source-Path'] = os.path.abspath(expanded)
                return response
            except Exception:
                continue
        return JsonResponse({'ok': False, 'error': '无法解码文件内容, 请尝试其他编码'}, status=400)

    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'读取文件失败: {str(e)}'}, status=500)


@login_required
def api_tools_source_files_gvim(request):
    """Deprecated: clients should use the gvim:// protocol instead of server launch.

    Kept for older tooling compatibility. Prefer registering
    ``scripts/register_gvim_protocol.ps1`` and opening ``gvim://open?path=...``.
    """
    return JsonResponse({
        'ok': False,
        'deprecated': True,
        'error': (
            'Server-launched gvim is deprecated. Register the Windows gvim:// '
            'protocol (scripts/register_gvim_protocol.ps1) and open source paths '
            'from the Vue client via SourceFileLink / gvim://open?path=...&line=...'
        ),
        'protocol_example': 'gvim://open?path=C%3A%5Cpath%5Cfile.v&line=1',
    }, status=410)