"""QoR 数据查询 API 蓝图

负责:
  - 项目/模块列表
  - QoR 数据查询
  - QoR 记录详情
  - QoR 聚合统计
  - Run Notes
  - 对比/导出
  - Metrics / Versions
"""
import io
import json
import re
from datetime import datetime

import pandas as pd
from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user, login_required

from models import (
    db, User, Project, Module, QorRecord, ProjectMember, RunNote,
)

from core.db_routing import (
    switch_to_project,
    query_records_by_projects,
    _resolve_project_ids,
)

bp = Blueprint('qor', __name__)


# =========================================================================
# 项目与模块 API
# =========================================================================

@bp.route('/api/projects')
@login_required
def api_get_projects():
    """获取项目列表 (默认排除已隐藏项目)

    查询参数:
      include_hidden=true  包含 hidden 状态 (仅 admin)
    """
    include_hidden = request.args.get('include_hidden', '').lower() in ('1', 'true', 'yes')
    query = Project.query
    if not (include_hidden and current_user.is_admin):
        query = query.filter(Project.status != 'hidden')
    projects = query.order_by(Project.name).all()
    result = []
    for p in projects:
        # 跨库关系 p.modules 是 viewonly InstrumentedList, 不支持 order_by
        # 改用直接查询 + ORM bind 路由 (先切换到该项目上下文)
        with switch_to_project(p.id):
            modules = Module.query.order_by(Module.name).all()
            for m in modules:
                # release 角色现在可查看所有数据 (v4.x 权限升级)
                m._record_count = m.records.count()
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'status': p.status,
            'is_writable': p.is_writable,
            'locked_at': p.locked_at.isoformat() if p.locked_at else None,
            'locked_by_name': p.locker.username if p.locker else None,
            'lock_reason': p.lock_reason,
            'module_count': len(modules),
            'modules': [{
                'id': m.id, 'name': m.name,
                'record_count': m._record_count,
            } for m in modules],
        })
    return jsonify(result)


@bp.route('/api/modules/<int:project_id>')
@login_required
def api_get_modules(project_id):
    """获取指定项目的模块列表"""
    project = Project.query.get_or_404(project_id)
    # 跨库 viewonly 关系: 切到项目库直接查 Module, 避免 ORM 兜底用第一个项目库
    with switch_to_project(project_id):
        modules = Module.query.filter_by(project_id=project_id).order_by(Module.name).all()
        result = []
        for m in modules:
            # release 角色现在可查看所有数据 (v4.x 权限升级)
            m._record_count = m.records.count()
            result.append({
                'id': m.id,
                'name': m.name,
                'record_count': m._record_count,
            })
        return jsonify(result)


# =========================================================================
# QoR 数据查询
# =========================================================================

@bp.route('/api/qor_data')
@login_required
def api_get_qor_data():
    """查询 QoR 数据

    查询参数:
      project_ids, module_ids, metric, versions, owner_id, owner_username

    按项目分库: 不能跨库 JOIN, 所以按 project_id 分别查询再合并.
    """
    project_ids = request.args.get('project_ids', '')
    module_ids = request.args.get('module_ids', '')
    versions = request.args.get('versions', '')
    owner_id = request.args.get('owner_id', '').strip()
    owner_username = request.args.get('owner_username', '').strip()

    # 解析 owner_user_id
    if owner_id and owner_id.isdigit():
        owner_user_id = int(owner_id)
    elif owner_username:
        owner_user = User.query.filter_by(username=owner_username).first()
        if owner_user is None:
            return jsonify([])
        owner_user_id = owner_user.id
    else:
        owner_user_id = None

    # 按项目分库: 用 helper 安全查询
    proj_id_list = _resolve_project_ids(project_ids) or None
    # v5.0: viewer 仅可查看已发布数据 (is_released=True)
    release_only = current_user.is_viewer
    records = query_records_by_projects(
        proj_id_list=proj_id_list,
        module_ids_str=module_ids,
        versions_str=versions,
        owner_id=owner_user_id,
        release_only=release_only,
        order_desc=True,
        limit=5000,
    )
    return jsonify([r.to_dict() for r in records])


# =========================================================================
# QoR 记录详情
# =========================================================================

def parse_full_dir(full_dir):
    """从 full_dir 路径中解析 base_dir / sub_path / run_name

    约定路径结构: <base_dir>[/<sub_path>...]/<run_name>
    """
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


@bp.route('/api/qor/record/<int:record_id>')
@login_required
def api_qor_record_detail(record_id):
    """单条 QoR 记录详情 + 同 module+version 横向对比"""
    rec = QorRecord.query.get_or_404(record_id)
    # v5.0 viewer: 仅可看已发布记录, 未发布记录视同不存在
    if current_user.is_viewer and not rec.is_released:
        return jsonify({'error': '记录不存在'}), 404
    if not current_user.is_admin and not current_user.is_release and not current_user.is_owner:
        member = ProjectMember.query.filter_by(
            project_id=rec.module.project_id, user_id=current_user.id,
        ).first()
        if not member:
            return jsonify({'error': 'forbidden'}), 403

    siblings = QorRecord.query.filter_by(
        module_id=rec.module_id, version=rec.version,
    ).order_by(QorRecord.recorded_at.asc()).all()
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

    return jsonify({
        'record': rec.to_dict(),
        'siblings': sibling_summaries,
        'sibling_count': len(sibling_summaries),
    })


@bp.route('/api/qor/aggregate')
@login_required
def api_qor_aggregate():
    """按维度聚合 QoR 记录

    group_by: base_dir | module | run
    """
    project_ids = request.args.get('project_ids', '')
    module_ids = request.args.get('module_ids', '')
    versions = request.args.get('versions', '')
    group_by = request.args.get('group_by', 'run').lower()
    single_metric = request.args.get('metric', '').strip()

    if group_by not in ('base_dir', 'module', 'run'):
        return jsonify({'error': 'group_by must be base_dir|module|run'}), 400

    # 按项目分库: 不能跨库 JOIN, 按 project_id 分别查询再合并
    proj_id_list = []
    if project_ids:
        proj_id_list = [int(x) for x in project_ids.split(',') if x.strip().isdigit()]
    if not proj_id_list:
        proj_id_list = [p.id for p in Project.query.filter(Project.status != 'hidden').all()]

    mod_id_filter = None
    if module_ids:
        mod_id_filter = set(int(x) for x in module_ids.split(',') if x.strip().isdigit())
    ver_filter = None
    if versions:
        ver_filter = set(v.strip() for v in versions.split(',') if v.strip())

    records = []
    for pid in proj_id_list:
        with switch_to_project(pid):
            q = QorRecord.query
            # release 角色现在可查看所有数据 (v4.x 权限升级)
            if mod_id_filter:
                q = q.filter(QorRecord.module_id.in_(mod_id_filter))
            if ver_filter:
                q = q.filter(QorRecord.version.in_(ver_filter))
            # 在项目库上下文内预先取出 (module_id, module_name), 防止 lazy-load 跨上下文掉到主库
            for r in q.order_by(QorRecord.recorded_at.asc()).limit(10000).all():
                mod_name = r.module.name if r.module is not None else ''
                records.append({
                    'record': r,
                    'module_id': r.module_id,
                    'module_name': mod_name,
                })

    # 按 group_by 分组聚合
    groups = {}
    for item in records:
        r = item['record']
        d = parse_full_dir(r.full_dir or '')
        if group_by == 'base_dir':
            key = d['base_dir'] or '(root)'
        elif group_by == 'module':
            key = item['module_name'] or f'#{r.module_id}'
        else:  # run: 用 full_dir 全路径作为唯一 key, 跨 base_dir 区分同名 run
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
        result = [{'label': r['label'], 'count': r['count'],
                   'base_dir': r.get('base_dir', ''), 'run_name': r.get('run_name', ''),
                   'module_name': r.get('module_name', ''),
                   single_metric: r.get(single_metric)} for r in result]

    return jsonify({
        'group_by': group_by,
        'total_records': len(records),
        'group_count': len(result),
        'items': result,
        'metric_directions': QOR_METRIC_DIRECTION,
    })


@bp.route('/api/qor/parse_path')
@login_required
def api_qor_parse_path():
    """解析 full_dir 路径结构"""
    full_dir = request.args.get('full_dir', '')
    return jsonify(parse_full_dir(full_dir))


@bp.route('/api/metrics')
@login_required
def api_get_metrics():
    """获取所有支持的指标列表"""
    return jsonify([
        {'name': k, 'direction': v} for k, v in QOR_METRIC_DIRECTION.items()
    ])


@bp.route('/api/versions')
@login_required
def api_get_versions():
    """获取所有版本号"""
    project_ids = request.args.get('project_ids', '')
    module_ids = request.args.get('module_ids', '')

    records = query_records_by_projects(
        proj_id_list=_resolve_project_ids(project_ids) or None,
        module_ids_str=module_ids,
        release_only=False,  # release 角色可查看所有版本 (v4.x 权限升级)
        order_desc=True,
        limit=10000,
    )
    versions = sorted(set(r.version for r in records if r.version))
    return jsonify(versions)


# =========================================================================
# Run Notes
# =========================================================================

@bp.route('/api/run_notes')
@login_required
def api_get_run_notes():
    """获取 Run 备注"""
    record_id = request.args.get('record_id', type=int)
    if not record_id:
        return jsonify([])
    rec = QorRecord.query.get_or_404(record_id)
    notes = RunNote.query.filter_by(qor_record_id=record_id).order_by(RunNote.created_at).all()
    return jsonify([n.to_dict() for n in notes])


# =========================================================================
# 对比与导出
# =========================================================================

@bp.route('/api/compare')
@login_required
def api_compare():
    """对比多个版本的 QoR 数据"""
    record_ids = request.args.get('record_ids', '')
    if not record_ids:
        return jsonify({'error': 'record_ids 必填'}), 400
    rid_list = [int(x) for x in record_ids.split(',') if x.strip().isdigit()]
    if not rid_list:
        return jsonify({'error': '无效的 record_ids'}), 400

    records = QorRecord.query.filter(QorRecord.id.in_(rid_list)).all()
    return jsonify([r.to_dict() for r in records])


@bp.route('/export')
@login_required
def export_data():
    """导出对比结果为 Excel/CSV"""
    record_ids = request.args.get('record_ids', '')
    fmt = request.args.get('format', 'csv').lower()
    if not record_ids:
        return jsonify({'error': 'record_ids 必填'}), 400
    rid_list = [int(x) for x in record_ids.split(',') if x.strip().isdigit()]
    records = QorRecord.query.filter(QorRecord.id.in_(rid_list)).all()
    if not records:
        return jsonify({'error': '无数据'}), 404

    rows = [r.to_dict() for r in records]
    df = pd.DataFrame(rows)
    if fmt == 'xlsx':
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='QoR')
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'qor_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
        )
    else:
        output = io.StringIO()
        df.to_csv(output, index=False)
        csv_data = output.getvalue().encode('utf-8-sig')
        return send_file(
            io.BytesIO(csv_data),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'qor_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
        )
