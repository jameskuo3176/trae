"""Violations API 蓝图

负责违例路径相关的查询与对比。
"""
import json

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models import (
    db, QorRecord, ViolationPath, ProjectMember, Module,
)

bp = Blueprint('violations', __name__)


@bp.route('/api/violations')
@login_required
def api_get_violations():
    """获取违例路径列表"""
    record_id = request.args.get('record_id', type=int)
    timing_group = request.args.get('timing_group', '')
    limit = min(request.args.get('limit', 200, type=int), 1000)

    q = ViolationPath.query
    if record_id:
        q = q.filter(ViolationPath.qor_record_id == record_id)
    if timing_group:
        q = q.filter(ViolationPath.timing_group == timing_group)
    paths = q.order_by(ViolationPath.slack).limit(limit).all()
    return jsonify([p.to_dict() for p in paths])


@bp.route('/api/violations/source_files')
@login_required
def api_get_violation_source_files():
    """获取违例路径数据源文件列表"""
    record_id = request.args.get('record_id', type=int)
    q = ViolationPath.query
    if record_id:
        q = q.filter(ViolationPath.qor_record_id == record_id)
    files = sorted(set(p.source_file for p in q.all() if p.source_file))
    return jsonify(files)


@bp.route('/api/violations/diff')
@login_required
def api_violations_diff():
    """对比两个版本的违例路径变化

    输入参数:
      base_record_id: 基准版本 record_id
      target_record_id: 目标版本 record_id
    返回: 新增/消失/共同违例路径
    """
    base_id = request.args.get('base_record_id', type=int)
    target_id = request.args.get('target_record_id', type=int)
    if not base_id or not target_id:
        return jsonify({'error': 'base_record_id, target_record_id 必填'}), 400

    base_paths = ViolationPath.query.filter_by(qor_record_id=base_id).all()
    target_paths = ViolationPath.query.filter_by(qor_record_id=target_id).all()

    def _key(p):
        return (p.startpoint, p.endpoint, p.timing_group)

    base_set = {_key(p): p for p in base_paths}
    target_set = {_key(p): p for p in target_paths}

    new_keys = set(target_set) - set(base_set)
    removed_keys = set(base_set) - set(target_set)
    common_keys = set(base_set) & set(target_set)

    return jsonify({
        'new_count': len(new_keys),
        'removed_count': len(removed_keys),
        'common_count': len(common_keys),
        'new': [target_set[k].to_dict() for k in list(new_keys)[:100]],
        'removed': [base_set[k].to_dict() for k in list(removed_keys)[:100]],
        'common': [target_set[k].to_dict() for k in list(common_keys)[:100]],
    })


@bp.route('/api/violations/timing_groups')
@login_required
def api_get_timing_groups():
    """获取所有 timing group"""
    record_id = request.args.get('record_id', type=int)
    q = ViolationPath.query
    if record_id:
        q = q.filter(ViolationPath.qor_record_id == record_id)
    groups = sorted(set(p.timing_group for p in q.all() if p.timing_group))
    return jsonify(groups)


@bp.route('/api/violations/summary')
@login_required
def api_get_violation_summary():
    """违例路径汇总统计"""
    record_id = request.args.get('record_id', type=int)
    if not record_id:
        return jsonify({'error': 'record_id 必填'}), 400
    rec = QorRecord.query.get_or_404(record_id)
    paths = ViolationPath.query.filter_by(qor_record_id=record_id).all()
    if not paths:
        return jsonify({
            'total': 0, 'by_group': {}, 'worst_slack': None,
        })

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
                             sum(1 for p in items if p.slack is not None) if any(p.slack is not None for p in items) else None,
            } for g, items in by_group.items()
        },
        'worst_slack': min((p.slack for p in paths if p.slack is not None), default=None),
    }
    return jsonify(summary)
