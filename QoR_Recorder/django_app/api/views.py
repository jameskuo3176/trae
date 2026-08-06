"""API 视图模块

QoR Recorder 所有 API 端点视图函数。
匹配 urls.py 中定义的路由名称。
"""
import csv as _csv
import io as _io
import json
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
from django.views.decorators.csrf import csrf_exempt

from django.contrib.auth import update_session_auth_hash
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
    REVIEW_STATUS_DRAFT, REVIEW_STATUS_SUBMITTED,
    REVIEW_STATUS_APPROVED, REVIEW_STATUS_REJECTED,
)
from django_app.services import qor_import, json_upload, backup_service


# =========================================================================
# 辅助函数
# =========================================================================

def _get_project_db(project_id):
    """获取项目数据库 Django 连接别名"""
    return _get_project_db_alias(project_id)


def _resolve_project_ids(project_ids_str=''):
    """解析查询参数中的 project_ids, 兜底到所有非隐藏项目"""
    return db_resolve_project_ids(project_ids_str)


def _find_qor_record_project(record_id):
    """跨项目库查找 QorRecord 所在 project_id"""
    return db_find_qor_record_project(record_id)


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
    """获取项目列表 (默认排除已隐藏项目)"""
    include_hidden = request.GET.get('include_hidden', '').lower() in ('1', 'true', 'yes')
    query = Project.objects.all()
    if not (include_hidden and request.user.is_admin):
        query = query.exclude(status='hidden')
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


@login_required
def api_get_modules(request, project_id):
    """获取指定项目的模块列表"""
    get_object_or_404(Project, pk=project_id)
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
    get_object_or_404(Project, pk=project_id)
    db_name = _get_project_db(project_id)
    try:
        get_project_engine(project_id)
        get_object_or_404(
            Module.objects.using(db_name),
            pk=module_id, project_id=project_id,
        )
        q = QorRecord.objects.using(db_name).filter(module_id=module_id)
        if request.user.is_viewer:
            q = q.filter(is_released=True)
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
    project_ids = request.GET.get('project_ids', '')
    module_ids = request.GET.get('module_ids', '')
    versions = request.GET.get('versions', '')
    owner_id = request.GET.get('owner_id', '').strip()
    owner_username = request.GET.get('owner_username', '').strip()
    dir_prefix = request.GET.get('dir_prefix', '').strip() or None

    owner_user_id = None
    if owner_id and owner_id.isdigit():
        owner_user_id = int(owner_id)
    elif owner_username:
        try:
            owner_user = User.objects.get(username=owner_username)
            owner_user_id = owner_user.id
        except User.DoesNotExist:
            return JsonResponse([], safe=False)

    proj_id_list = _resolve_project_ids(project_ids) or None
    release_only = request.user.is_viewer
    records = query_records_by_projects(
        proj_id_list=proj_id_list,
        module_ids_str=module_ids,
        versions_str=versions,
        owner_id=owner_user_id,
        release_only=release_only,
        dir_prefix=dir_prefix,
        order_desc=True,
        limit=5000,
    )
    return JsonResponse([r.to_dict() for r in records], safe=False)


@login_required
def api_qor_record_detail(request, record_id):
    """单条 QoR 记录详情 + 同 module+version 横向对比"""
    pid = _find_qor_record_project(record_id)
    if pid is None:
        return JsonResponse({'error': '记录不存在'}, status=404)
    db_name = _get_project_db(pid)
    try:
        get_project_engine(pid)
        rec = QorRecord.objects.using(db_name).select_related('module').get(pk=record_id)
    except QorRecord.DoesNotExist:
        return JsonResponse({'error': '记录不存在'}, status=404)

    if request.user.is_viewer:
        if not rec.is_released:
            return JsonResponse({'error': '记录不存在'}, status=404)
    elif not request.user.is_admin and not request.user.is_owner:
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

    return JsonResponse({
        'record': rec.to_dict(),
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
    proj_id_list = _resolve_project_ids(project_ids) or None
    release_only = request.user.is_viewer

    records = query_records_by_projects(
        proj_id_list=proj_id_list,
        dir_prefix=base_dir,
        release_only=release_only,
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
        proj_id_list=_resolve_project_ids(project_ids) or None,
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
    """列出 Tile Review"""
    if request.user.is_viewer:
        return JsonResponse([], safe=False)
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
                member = ProjectMember.objects.filter(
                    project_id=r.project_id, user=request.user,
                ).first()
                if not member or member.role not in ('owner', 'editor'):
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

@login_required
def list_group_reviews(request):
    """列出 Group Review"""
    if request.user.is_viewer:
        return JsonResponse([], safe=False)
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
            rows = GroupReview.objects.using(db_name).filter(project_id=pid).order_by('-created_at')[:500]
            return JsonResponse({'items': [r.to_dict(include_detail=True) for r in rows]})
        except Exception:
            return JsonResponse({'items': []})
    else:
        items = []
        for p in _resolve_project_ids():
            db_name = _get_project_db(p)
            try:
                get_project_engine(p)
                rows = GroupReview.objects.using(db_name).order_by('-created_at')[:500]
                items.extend([r.to_dict(include_detail=True) for r in rows])
            except Exception:
                continue
        return JsonResponse({'items': items})


@login_required
def group_review_detail(request, rid):
    """Group Review 详情 (GET) / 更新 (PUT)"""
    if request.method == 'GET':
        for pid in _resolve_project_ids():
            db_name = _get_project_db(pid)
            try:
                get_project_engine(pid)
                r = GroupReview.objects.using(db_name).get(pk=rid)
                return JsonResponse(r.to_dict(include_detail=True))
            except GroupReview.DoesNotExist:
                continue
        return JsonResponse({'error': '不存在'}, status=404)

    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    data = json.loads(request.body) if request.body else {}
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = GroupReview.objects.using(db_name).get(pk=rid)
            if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
                return JsonResponse({'error': f'当前状态 {r.status} 不可修改'}, status=400)
            for k in ('title', 'period', 'summary', 'verdict', 'group_name', 'subsystem'):
                if k in data:
                    setattr(r, k, data[k])
            for k in ('tile_review_ids', 'key_metrics', 'findings', 'decisions', 'next_steps', 'risks'):
                if k in data:
                    val = json.dumps(data[k], ensure_ascii=False) if data[k] else None
                    setattr(r, k, val)
            r.save(using=db_name)
            return JsonResponse(r.to_dict())
        except GroupReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def submit_group_review(request, rid):
    """提交 Group Review"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = GroupReview.objects.using(db_name).get(pk=rid)
            if r.status != REVIEW_STATUS_DRAFT:
                return JsonResponse({'error': f'当前状态 {r.status} 不可提交'}, status=400)
            r.status = REVIEW_STATUS_SUBMITTED
            r.submitted_at = timezone.now()
            r.save(using=db_name)
            return JsonResponse(r.to_dict())
        except GroupReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def review_group_review(request, rid):
    """审批 Group Review"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = GroupReview.objects.using(db_name).get(pk=rid)
            if r.status != REVIEW_STATUS_SUBMITTED:
                return JsonResponse({'error': f'当前状态 {r.status} 不可审批'}, status=400)
            if r.leader_id == request.user.id:
                return JsonResponse({'error': '不能审核自己创建的 review'}, status=400)
            if not request.user.is_admin:
                member = ProjectMember.objects.filter(
                    project_id=r.project_id, user=request.user,
                ).first()
                if not member or member.role not in ('owner', 'editor'):
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
        except GroupReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


# ---- Subsystem Reviews ----

@login_required
def list_subsystem_reviews(request):
    """列出 Subsystem Review"""
    if request.user.is_viewer:
        return JsonResponse([], safe=False)
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
            return JsonResponse({'items': [r.to_dict(include_detail=True) for r in rows]})
        except Exception:
            return JsonResponse({'items': []})
    else:
        items = []
        for p in _resolve_project_ids():
            db_name = _get_project_db(p)
            try:
                get_project_engine(p)
                rows = SubsystemReview.objects.using(db_name).order_by('-created_at')[:500]
                items.extend([r.to_dict(include_detail=True) for r in rows])
            except Exception:
                continue
        return JsonResponse({'items': items})


@login_required
def subsystem_review_detail(request, rid):
    """Subsystem Review 详情 (GET) / 更新 (PUT)"""
    if request.method == 'GET':
        for pid in _resolve_project_ids():
            db_name = _get_project_db(pid)
            try:
                get_project_engine(pid)
                r = SubsystemReview.objects.using(db_name).get(pk=rid)
                return JsonResponse(r.to_dict(include_detail=True))
            except SubsystemReview.DoesNotExist:
                continue
        return JsonResponse({'error': '不存在'}, status=404)

    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    data = json.loads(request.body) if request.body else {}
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = SubsystemReview.objects.using(db_name).get(pk=rid)
            if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
                return JsonResponse({'error': f'当前状态 {r.status} 不可修改'}, status=400)
            for k in ('title', 'period', 'summary', 'verdict', 'subsystem'):
                if k in data:
                    setattr(r, k, data[k])
            for k in ('group_review_ids', 'key_metrics', 'findings', 'decisions', 'next_steps'):
                if k in data:
                    val = json.dumps(data[k], ensure_ascii=False) if data[k] else None
                    setattr(r, k, val)
            r.save(using=db_name)
            return JsonResponse(r.to_dict())
        except SubsystemReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def submit_subsystem_review(request, rid):
    """提交 Subsystem Review"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'forbidden'}, status=403)
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = SubsystemReview.objects.using(db_name).get(pk=rid)
            if r.status != REVIEW_STATUS_DRAFT:
                return JsonResponse({'error': f'当前状态 {r.status} 不可提交'}, status=400)
            r.status = REVIEW_STATUS_SUBMITTED
            r.submitted_at = timezone.now()
            r.save(using=db_name)
            return JsonResponse(r.to_dict())
        except SubsystemReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


@login_required
def review_subsystem_review(request, rid):
    """审批 Subsystem Review"""
    for pid in _resolve_project_ids():
        db_name = _get_project_db(pid)
        try:
            get_project_engine(pid)
            r = SubsystemReview.objects.using(db_name).get(pk=rid)
            if r.status != REVIEW_STATUS_SUBMITTED:
                return JsonResponse({'error': f'当前状态 {r.status} 不可审批'}, status=400)
            if r.manager_id == request.user.id:
                return JsonResponse({'error': '不能审核自己创建的 review'}, status=400)
            if not request.user.is_admin:
                member = ProjectMember.objects.filter(
                    project_id=r.project_id, user=request.user,
                ).first()
                if not member or member.role not in ('owner', 'editor'):
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
        except SubsystemReview.DoesNotExist:
            continue
    return JsonResponse({'error': '不存在'}, status=404)


# ---- Review Snapshots ----

@login_required
def list_snapshots(request):
    """列出 Review Snapshots"""
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

@csrf_exempt
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


@csrf_exempt
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


@csrf_exempt
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
    p.save()
    return JsonResponse({
        'ok': True,
        'message': f'项目 "{p.name}" 已恢复为 active',
        'project': p.to_dict(),
    })


@csrf_exempt
@login_required
def admin_hard_delete_project(request, project_id):
    """彻底删除项目"""
    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)
    p = get_object_or_404(Project, pk=project_id)
    if p.status != 'hidden':
        return JsonResponse({'error': '只能彻底删除已隐藏项目, 请先软删除'}, status=400)

    data = json.loads(request.body) if request.body else {}
    if str(data.get('confirm', '')).lower() not in ('1', 'true', 'yes'):
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


@csrf_exempt
@login_required
def admin_lock_project(request, project_id):
    """锁定项目"""
    p = get_object_or_404(Project, pk=project_id)
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    p.status = 'locked'
    p.locked_at = timezone.now()
    p.locked_by = request.user
    data = json.loads(request.body) if request.body else {}
    p.lock_reason = data.get('reason', '')
    p.save()
    return JsonResponse(p.to_dict())


@csrf_exempt
@login_required
def admin_unlock_project(request, project_id):
    """解锁项目"""
    p = get_object_or_404(Project, pk=project_id)
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    p.status = 'active'
    p.locked_at = None
    p.locked_by = None
    p.lock_reason = None
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
            if p.status != 'active':
                return JsonResponse({'error': '项目非活跃状态, 不可回滚'}, status=403)

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
                    module_id=module_map[module_name],
                    version=item.get('version', 'v1'),
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
                    target_frequency=item.get('target_frequency'),
                    achieved_frequency=item.get('achieved_frequency'),
                    mbb_ratio=item.get('mbb_ratio'),
                    clock_gating_ratio=item.get('clock_gating_ratio'),
                    utilization=item.get('utilization'),
                    congestion=item.get('congestion'),
                    congestion_h=item.get('congestion_h'),
                    congestion_v=item.get('congestion_v'),
                    congestion_b=item.get('congestion_b'),
                    source_file=item.get('source_file'),
                    full_dir=item.get('full_dir'),
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
def admin_list_backups(request):
    """列出备份记录"""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
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

@csrf_exempt
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


@csrf_exempt
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


@csrf_exempt
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

@csrf_exempt
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


@csrf_exempt
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


@csrf_exempt
@login_required
def admin_delete_record(request, record_id):
    """删除记录"""
    if request.user.is_viewer:
        return JsonResponse({'error': '无权限 (viewer 角色不可删除)'}, status=403)

    pid = _find_qor_record_project(record_id)
    if pid is None:
        return JsonResponse({'error': '记录不存在'}, status=404)
    db_name = _get_project_db(pid)
    get_project_engine(pid)
    r = get_object_or_404(QorRecord.objects.using(db_name), pk=record_id)

    if not request.user.is_admin:
        if r.owner_id != request.user.id:
            return JsonResponse({'error': '无权限删除此记录'}, status=403)

    r.delete()
    return JsonResponse({'ok': True})


@login_required
def admin_list_record_owners(request):
    """列出所有记录 owner"""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    owner_ids = set()
    for pid in _resolve_project_ids():
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

@csrf_exempt
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
    if project.status != 'active':
        return JsonResponse({'error': '项目当前不可写'}, status=403)

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


@csrf_exempt
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


@csrf_exempt
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

@csrf_exempt
@login_required
def admin_toggle_release(request, record_id):
    """切换记录发布状态"""
    project_id = _find_qor_record_project(record_id)
    if project_id is None:
        return JsonResponse({'error': '记录不存在'}, status=404)

    data = json.loads(request.body) if request.body else {}
    new_release_dir = data.get('release_dir', None)

    db_name = _get_project_db(project_id)
    get_project_engine(project_id)
    r = get_object_or_404(QorRecord.objects.using(db_name), pk=record_id)

    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无发布权限'}, status=403)
    if not request.user.is_admin and not request.user.is_owner:
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


@csrf_exempt
@login_required
def admin_update_release_dir(request, record_id):
    """更新记录 release_dir"""
    project_id = _find_qor_record_project(record_id)
    if project_id is None:
        return JsonResponse({'error': '记录不存在'}, status=404)

    data = json.loads(request.body) if request.body else {}
    new_release_dir = data.get('release_dir', None)
    if new_release_dir is None or not isinstance(new_release_dir, str):
        return JsonResponse({'error': 'release_dir 必填且为字符串'}, status=400)
    if len(new_release_dir) > 500:
        return JsonResponse({'error': 'release_dir 长度不能超过 500'}, status=400)

    db_name = _get_project_db(project_id)
    get_project_engine(project_id)
    r = get_object_or_404(QorRecord.objects.using(db_name), pk=record_id)

    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无发布权限'}, status=403)
    if not request.user.is_admin and not request.user.is_owner:
        return JsonResponse({'error': '无权限'}, status=403)

    cleaned = new_release_dir.strip()[:500] if new_release_dir.strip() else None
    r.release_dir = cleaned
    r.save(using=db_name)
    return JsonResponse({
        'ok': True,
        'id': r.id,
        'release_dir': r.release_dir or '',
        'release_dir_effective': r.release_dir or r.full_dir or '',
    })


@csrf_exempt
@login_required
def admin_update_version_description(request, record_id):
    """更新版本描述"""
    pid = _find_qor_record_project(record_id)
    if pid is None:
        return JsonResponse({'error': '记录不存在'}, status=404)
    data = json.loads(request.body) if request.body else {}
    desc = (data.get('description') or '').strip()

    db_name = _get_project_db(pid)
    get_project_engine(pid)
    r = get_object_or_404(QorRecord.objects.using(db_name), pk=record_id)

    if not request.user.is_admin:
        return JsonResponse({'error': '需要管理员权限'}, status=403)

    r.version_description = desc or None
    r.save(using=db_name)
    return JsonResponse({
        'ok': True,
        'id': r.id,
        'version_description': r.version_description or '',
    })


@csrf_exempt
@login_required
def admin_batch_release(request):
    """批量发布/取消发布"""
    if request.user.is_viewer:
        return JsonResponse({'error': 'viewer 角色无发布权限'}, status=403)

    data = json.loads(request.body) if request.body else {}
    record_ids = data.get('record_ids', [])
    if not record_ids:
        return JsonResponse({'error': 'record_ids 必填'}, status=400)
    if not isinstance(record_ids, list):
        return JsonResponse({'error': 'record_ids 必须为数组'}, status=400)
    if len(record_ids) > 1000:
        return JsonResponse({'error': f'单次最多 1000 条, 当前 {len(record_ids)} 条'}, status=400)

    released = bool(data.get('released', True))
    batch_release_dir = data.get('release_dir', '__NOT_PROVIDED__')

    updated = 0
    skipped = 0
    failed = []

    rid_to_project = {}
    for rid in record_ids:
        pid = _find_qor_record_project(int(rid))
        if pid is not None:
            rid_to_project[rid] = pid

    by_project = {}
    for rid, pid in rid_to_project.items():
        by_project.setdefault(pid, []).append(rid)

    for pid, rids in by_project.items():
        db_name = _get_project_db(pid)
        get_project_engine(pid)
        records = QorRecord.objects.using(db_name).filter(pk__in=rids)
        records_map = {r.id: r for r in records}

        for rid in rids:
            r = records_map.get(rid)
            if not r:
                skipped += 1
                failed.append({'id': rid, 'reason': '记录不存在'})
                continue

            if not request.user.is_admin and not request.user.is_owner:
                skipped += 1
                failed.append({'id': rid, 'reason': '无权限'})
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

@csrf_exempt
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


@csrf_exempt
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


@csrf_exempt
@login_required
def admin_reset_user_password(request, user_id):
    """重置用户密码"""
    if not request.user.is_admin:
        return JsonResponse({'error': '无权限'}, status=403)
    user = get_object_or_404(User, pk=user_id)

    data = json.loads(request.body) if request.body else {}
    new_password = (data.get('password') or '').strip() or 'Reset@123'

    user.set_password(new_password)
    user.must_change_password = True
    user.password_changed_at = None
    user.save()
    return JsonResponse({
        'ok': True,
        'username': user.username,
        'reset_to': new_password,
        'must_change_password': True,
    })


@login_required
@csrf_exempt
def user_change_own_password(request):
    """修改自己的密码"""
    data = json.loads(request.body) if request.body else {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return JsonResponse({'error': '旧密码和新密码不能为空'}, status=400)
    if not request.user.check_password(old_password):
        return JsonResponse({'error': '旧密码错误'}, status=400)
    if old_password == new_password:
        return JsonResponse({'error': '新密码不能与旧密码相同'}, status=400)

    from django_app.core.security import validate_password
    ok, err = validate_password(new_password)
    if not ok:
        return JsonResponse({'error': err or '密码强度不足'}, status=400)

    request.user.set_password(new_password)
    request.user.must_change_password = False
    request.user.password_changed_at = timezone.now()
    request.user.save()
    update_session_auth_hash(request, request.user)
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

    if not user.check_password(password):
        return JsonResponse({'error': '用户名或密码错误'}, status=401)

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
        'user': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name,
        },
    })


@api_auth_required()
def api_v1_me(request):
    """API v1 当前用户信息"""
    user = request.user
    return JsonResponse({
        'id': user.id,
        'username': user.username,
        'role': user.role,
        'display_name': user.display_name,
        'auth_method': getattr(request, 'auth_method', 'session'),
    })


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
    """在 gvim 中打开源文件"""
    try:
        body = json.loads(request.body) if request.body else None
        if not body:
            return JsonResponse({'ok': False, 'error': '请求体为空'}, status=400)

        file_path = body.get('path', '').strip()
        if not file_path:
            return JsonResponse({'ok': False, 'error': '缺少 path 参数'}, status=400)

        line = body.get('line')

        expanded = os.path.expanduser(file_path)
        if not os.path.exists(expanded):
            return JsonResponse({'ok': False, 'error': f'文件不存在: {file_path}'}, status=404)

        system = platform.system()
        if system == 'Windows':
            gvim_candidates = [
                'gvim',
                r'C:\Program Files\Vim\vim91\gvim.exe',
                r'C:\Program Files (x86)\Vim\vim91\gvim.exe',
                r'C:\Program Files\Vim\vim90\gvim.exe',
                r'C:\Program Files (x86)\Vim\vim90\gvim.exe',
            ]
            gvim_path = None
            for candidate in gvim_candidates:
                try:
                    subprocess.run(
                        [candidate, '--version'],
                        capture_output=True, timeout=3,
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                    )
                    gvim_path = candidate
                    break
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue

            if not gvim_path:
                return JsonResponse({
                    'ok': False,
                    'error': '未找到 gvim 安装路径',
                }, status=400)
        else:
            gvim_path = 'gvim'

        args = [gvim_path]
        if line:
            args.append(f'+{line}')
        args.append(expanded)

        if system == 'Windows':
            subprocess.Popen(
                args,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )

        return JsonResponse({
            'ok': True,
            'message': f'已在 gvim 中打开: {os.path.basename(expanded)}',
            'path': os.path.abspath(expanded),
        })

    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'打开 gvim 失败: {str(e)}'}, status=500)