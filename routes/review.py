"""Review API 蓝图

负责 Review 流程相关 API:
  - Review 选项 (项目/模块/approved 列表)
  - Tile Review CRUD
  - Group Review CRUD
  - Subsystem Review CRUD
  - Snapshot 管理
  - 文件上传/下载
"""
import json
import os
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_login import current_user, login_required

from models import (
    db, Project, ProjectMember, QorRecord, TileReview, GroupReview,
    SubsystemReview, ReviewSnapshot, ReviewFile, DataSnapshot,
    REVIEW_STATUS_DRAFT, REVIEW_STATUS_SUBMITTED, REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_REJECTED,
)

bp = Blueprint('review', __name__)


# =========================================================================
# Review 选项 API
# =========================================================================

@bp.route('/options', methods=['GET'])
@login_required
def reviews_options():
    """返回前端表单所需的全部选项: 项目(带模块和records)、approved tile reviews、approved group reviews"""
    if current_user.is_release:
        return jsonify({
            'projects': [], 'approved_tile_reviews': [], 'approved_group_reviews': [],
        })
    projects = []
    for p in Project.query.all():
        modules = []
        for m in p.modules:
            records = [{
                'id': r.id, 'version': getattr(r, 'version', None) or getattr(r, 'name', ''),
            } for r in m.records]
            modules.append({'id': m.id, 'name': m.name, 'records': records})
        projects.append({'id': p.id, 'name': p.name, 'modules': modules})

    approved_tiles = []
    for r in TileReview.query.filter_by(status=REVIEW_STATUS_APPROVED).all():
        approved_tiles.append({
            'id': r.id, 'title': r.title, 'project_id': r.project_id,
            'module_name': r.module.name if r.module else None,
            'group_name': getattr(r, 'group_name', None) or (r.module.name if r.module else None),
            'verdict': r.verdict,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        })
    approved_groups = []
    for r in GroupReview.query.filter_by(status=REVIEW_STATUS_APPROVED).all():
        approved_groups.append({
            'id': r.id, 'title': r.title, 'project_id': r.project_id,
            'group_name': r.group_name, 'verdict': r.verdict,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        })
    return jsonify({
        'projects': projects,
        'approved_tile_reviews': approved_tiles,
        'approved_group_reviews': approved_groups,
    })


# =========================================================================
# Tile Reviews API
# =========================================================================

@bp.route('/tile', methods=['GET'])
@login_required
def list_tile_reviews():
    if current_user.is_release:
        return jsonify([])
    pid = request.args.get('project_id', type=int)
    if pid is not None:
        if not current_user.is_admin:
            member = ProjectMember.query.filter_by(project_id=pid, user_id=current_user.id).first()
            if not member:
                return jsonify({'error': 'forbidden'}), 403
    q = TileReview.query
    if pid:
        q = q.filter(TileReview.project_id == pid)
    rows = q.order_by(TileReview.created_at.desc()).limit(500).all()
    return jsonify({'items': [r.to_dict(include_detail=True) for r in rows]})


@bp.route('/tile', methods=['POST'])
@login_required
def create_tile_review():
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    if not data.get('project_id') or not data.get('module_id') or not data.get('title'):
        return jsonify({'error': 'project_id, module_id, title 必填'}), 400
    if not current_user.is_admin:
        member = ProjectMember.query.filter_by(project_id=data['project_id'], user_id=current_user.id).first()
        if not member or member.role not in ('owner', 'editor'):
            return jsonify({'error': 'forbidden'}), 403

    # 自动从关联的 QoR record 抓取指标快照
    snapshot = data.get('metrics_snapshot')
    if snapshot is None and data.get('record_id'):
        rec = QorRecord.query.get(data['record_id'])
        if rec:
            d = rec.to_dict()
            snapshot = {k: d[k] for k in (
                'version', 'area_total', 'area_combinational', 'area_sequential',
                'wns_setup', 'tns_setup', 'nvp_setup',
                'wns_hold', 'tns_hold', 'nvp_hold',
                'power_total', 'cell_count', 'utilization',
            ) if k in d and d[k] is not None}

    r = TileReview(
        project_id=data['project_id'],
        module_id=data['module_id'],
        record_id=data.get('record_id'),
        title=data['title'],
        period=data.get('period', 'weekly'),
        summary=data.get('summary', ''),
        verdict=data.get('verdict'),
        key_metrics=json.dumps(data.get('key_metrics', []), ensure_ascii=False) if data.get('key_metrics') else None,
        findings=json.dumps(data.get('findings', []), ensure_ascii=False) if data.get('findings') else None,
        decisions=json.dumps(data.get('decisions', []), ensure_ascii=False) if data.get('decisions') else None,
        next_steps=json.dumps(data.get('next_steps', []), ensure_ascii=False) if data.get('next_steps') else None,
        metrics_snapshot=json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
        risks=json.dumps(data.get('risks', []), ensure_ascii=False),
        created_by=current_user.id,
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(r.to_dict(include_snapshot=True)), 201


@bp.route('/tile/<int:rid>', methods=['GET', 'PATCH', 'PUT'])
@login_required
def update_tile_review(rid):
    if request.method == 'GET':
        r = TileReview.query.get_or_404(rid)
        return jsonify(r.to_dict(include_detail=True))
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    r = TileReview.query.get_or_404(rid)
    data = request.get_json() or {}
    if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
        return jsonify({'error': f'当前状态 {r.status} 不可修改'}), 400
    for k in ('title', 'period', 'summary', 'verdict'):
        if k in data:
            setattr(r, k, data[k])
    if 'risks' in data:
        r.risks = json.dumps(data['risks'], ensure_ascii=False) if data['risks'] else None
    if 'key_metrics' in data:
        r.key_metrics = json.dumps(data['key_metrics'], ensure_ascii=False) if data['key_metrics'] else None
    if 'findings' in data:
        r.findings = json.dumps(data['findings'], ensure_ascii=False) if data['findings'] else None
    if 'decisions' in data:
        r.decisions = json.dumps(data['decisions'], ensure_ascii=False) if data['decisions'] else None
    if 'next_steps' in data:
        r.next_steps = json.dumps(data['next_steps'], ensure_ascii=False) if data['next_steps'] else None
    db.session.commit()
    return jsonify(r.to_dict())


@bp.route('/tile/<int:rid>/submit', methods=['POST'])
@login_required
def submit_tile_review(rid):
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    r = TileReview.query.get_or_404(rid)
    if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
        return jsonify({'error': f'当前状态 {r.status} 不可提交'}), 400
    r.status = REVIEW_STATUS_SUBMITTED
    r.submitted_by = current_user.id
    r.submitted_at = datetime.utcnow()
    db.session.commit()
    return jsonify(r.to_dict())


@bp.route('/tile/<int:rid>/review', methods=['POST'])
@login_required
def review_tile_review(rid):
    """审批 (批准/驳回)"""
    r = TileReview.query.get_or_404(rid)
    if r.status != REVIEW_STATUS_SUBMITTED:
        return jsonify({'error': f'当前状态 {r.status} 不可审批'}), 400
    if not current_user.is_admin:
        member = ProjectMember.query.filter_by(project_id=r.project_id, user_id=current_user.id).first()
        if not member or member.role not in ('owner', 'editor'):
            return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'error': 'action 必须是 approve 或 reject'}), 400
    r.status = REVIEW_STATUS_APPROVED if action == 'approve' else REVIEW_STATUS_REJECTED
    r.reviewed_by = current_user.id
    r.reviewed_at = datetime.utcnow()
    r.review_comment = data.get('comment', '')
    db.session.commit()
    return jsonify(r.to_dict(include_detail=True))


# =========================================================================
# Group Reviews API
# =========================================================================

@bp.route('/group', methods=['GET'])
@login_required
def list_group_reviews():
    if current_user.is_release:
        return jsonify([])
    pid = request.args.get('project_id', type=int)
    q = GroupReview.query
    if pid:
        q = q.filter(GroupReview.project_id == pid)
    rows = q.order_by(GroupReview.created_at.desc()).limit(500).all()
    return jsonify({'items': [r.to_dict(include_detail=True) for r in rows]})


@bp.route('/group', methods=['POST'])
@login_required
def create_group_review():
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    if not data.get('project_id') or not data.get('group_name') or not data.get('title'):
        return jsonify({'error': 'project_id, group_name, title 必填'}), 400
    if not current_user.is_admin:
        member = ProjectMember.query.filter_by(project_id=data['project_id'], user_id=current_user.id).first()
        if not member or member.role not in ('owner', 'editor'):
            return jsonify({'error': 'forbidden'}), 403

    # 自动 aggregate
    aggregate = data.get('aggregate')
    if aggregate is None and data.get('tile_review_ids'):
        tiles = TileReview.query.filter(
            TileReview.id.in_(data['tile_review_ids']),
            TileReview.status == REVIEW_STATUS_APPROVED,
        ).all()
        if tiles:
            agg = {}
            for t in tiles:
                if not t.metrics_snapshot:
                    continue
                snap = json.loads(t.metrics_snapshot)
                for k, v in snap.items():
                    if isinstance(v, (int, float)) and k != 'version':
                        agg.setdefault(k, []).append(v)
            if agg:
                aggregate = {k: {'avg': sum(v) / len(v), 'count': len(v)} for k, v in agg.items()}

    r = GroupReview(
        project_id=data['project_id'],
        group_name=data['group_name'],
        period=data.get('period', 'weekly'),
        title=data['title'],
        summary=data.get('summary', ''),
        verdict=data.get('verdict'),
        key_metrics=json.dumps(data.get('key_metrics', []), ensure_ascii=False) if data.get('key_metrics') else None,
        findings=json.dumps(data.get('findings', []), ensure_ascii=False) if data.get('findings') else None,
        decisions=json.dumps(data.get('decisions', []), ensure_ascii=False) if data.get('decisions') else None,
        next_steps=json.dumps(data.get('next_steps', []), ensure_ascii=False) if data.get('next_steps') else None,
        tile_review_ids=json.dumps(data.get('tile_review_ids', [])),
        aggregate=json.dumps(aggregate, ensure_ascii=False) if aggregate else None,
        risks=json.dumps(data.get('risks', []), ensure_ascii=False),
        leader_id=current_user.id,
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(r.to_dict()), 201


@bp.route('/group/<int:rid>', methods=['GET', 'PATCH', 'PUT'])
@login_required
def get_group_review(rid):
    if request.method == 'GET':
        r = GroupReview.query.get_or_404(rid)
        return jsonify(r.to_dict(include_detail=True))
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    r = GroupReview.query.get_or_404(rid)
    data = request.get_json() or {}
    if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
        return jsonify({'error': f'当前状态 {r.status} 不可修改'}), 400
    for k in ('title', 'period', 'summary', 'verdict', 'group_name', 'subsystem'):
        if k in data:
            setattr(r, k, data[k])
    if 'tile_review_ids' in data:
        r.tile_review_ids = json.dumps(data['tile_review_ids'], ensure_ascii=False)
    if 'risks' in data:
        r.risks = json.dumps(data['risks'], ensure_ascii=False)
    if 'key_metrics' in data:
        r.key_metrics = json.dumps(data['key_metrics'], ensure_ascii=False)
    if 'findings' in data:
        r.findings = json.dumps(data['findings'], ensure_ascii=False)
    if 'decisions' in data:
        r.decisions = json.dumps(data['decisions'], ensure_ascii=False)
    if 'next_steps' in data:
        r.next_steps = json.dumps(data['next_steps'], ensure_ascii=False)
    db.session.commit()
    return jsonify(r.to_dict())


@bp.route('/group/<int:rid>/submit', methods=['POST'])
@login_required
def submit_group_review(rid):
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    r = GroupReview.query.get_or_404(rid)
    if r.status != REVIEW_STATUS_DRAFT:
        return jsonify({'error': f'当前状态 {r.status} 不可提交'}), 400
    r.status = REVIEW_STATUS_SUBMITTED
    r.submitted_at = datetime.utcnow()
    db.session.commit()
    return jsonify(r.to_dict())


@bp.route('/group/<int:rid>/review', methods=['POST'])
@login_required
def review_group_review(rid):
    r = GroupReview.query.get_or_404(rid)
    if r.status != REVIEW_STATUS_SUBMITTED:
        return jsonify({'error': f'当前状态 {r.status} 不可审批'}), 400
    if r.leader_id == current_user.id:
        return jsonify({'error': '不能审核自己创建的 review'}), 400
    if not current_user.is_admin:
        member = ProjectMember.query.filter_by(project_id=r.project_id, user_id=current_user.id).first()
        if not member or member.role not in ('owner', 'editor'):
            return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'error': 'action 必须是 approve 或 reject'}), 400
    r.status = REVIEW_STATUS_APPROVED if action == 'approve' else REVIEW_STATUS_REJECTED
    r.reviewed_by = current_user.id
    r.reviewed_at = datetime.utcnow()
    r.review_comment = data.get('comment', '')
    db.session.commit()
    return jsonify(r.to_dict(include_detail=True))


# =========================================================================
# Subsystem Reviews API
# =========================================================================

@bp.route('/subsystem', methods=['GET'])
@login_required
def list_subsystem_reviews():
    if current_user.is_release:
        return jsonify([])
    pid = request.args.get('project_id', type=int)
    q = SubsystemReview.query
    if pid:
        q = q.filter(SubsystemReview.project_id == pid)
    rows = q.order_by(SubsystemReview.created_at.desc()).limit(500).all()
    return jsonify({'items': [r.to_dict(include_detail=True) for r in rows]})


@bp.route('/subsystem', methods=['POST'])
@login_required
def create_subsystem_review():
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    if not data.get('project_id') or not data.get('subsystem') or not data.get('title'):
        return jsonify({'error': 'project_id, subsystem, title 必填'}), 400
    if not current_user.is_admin:
        member = ProjectMember.query.filter_by(project_id=data['project_id'], user_id=current_user.id).first()
        if not member or member.role not in ('owner', 'editor'):
            return jsonify({'error': 'forbidden'}), 403

    # 自动 aggregate: 从 group reviews 的 aggregate 字段汇总
    aggregate = data.get('aggregate')
    if aggregate is None and data.get('group_review_ids'):
        groups = GroupReview.query.filter(
            GroupReview.id.in_(data['group_review_ids']),
            GroupReview.status == REVIEW_STATUS_APPROVED,
        ).all()
        if groups:
            agg = {}
            for g in groups:
                if not g.aggregate:
                    continue
                try:
                    g_agg = json.loads(g.aggregate)
                except (json.JSONDecodeError, TypeError):
                    continue
                for metric, info in g_agg.items():
                    if not isinstance(info, dict):
                        continue
                    avg = info.get('avg')
                    count = info.get('count', 1)
                    if avg is None:
                        continue
                    # 加权: 用 count 作权重求总平均
                    agg.setdefault(metric, []).append((avg, count))
            if agg:
                aggregate = {}
                for metric, pairs in agg.items():
                    total_weight = sum(p[1] for p in pairs)
                    if total_weight == 0:
                        continue
                    weighted_avg = sum(p[0] * p[1] for p in pairs) / total_weight
                    aggregate[metric] = {
                        'avg': weighted_avg,
                        'count': total_weight,
                    }

    r = SubsystemReview(
        project_id=data['project_id'],
        subsystem=data['subsystem'],
        period=data.get('period', 'weekly'),
        title=data['title'],
        summary=data.get('summary', ''),
        verdict=data.get('verdict'),
        key_metrics=json.dumps(data.get('key_metrics', []), ensure_ascii=False) if data.get('key_metrics') else None,
        findings=json.dumps(data.get('findings', []), ensure_ascii=False) if data.get('findings') else None,
        decisions=json.dumps(data.get('decisions', []), ensure_ascii=False) if data.get('decisions') else None,
        next_steps=json.dumps(data.get('next_steps', []), ensure_ascii=False) if data.get('next_steps') else None,
        group_review_ids=json.dumps(data.get('group_review_ids', [])),
        aggregate=json.dumps(aggregate, ensure_ascii=False) if aggregate else None,
        manager_id=current_user.id,
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(r.to_dict()), 201


@bp.route('/subsystem/<int:rid>', methods=['GET', 'PATCH', 'PUT'])
@login_required
def get_subsystem_review(rid):
    if request.method == 'GET':
        r = SubsystemReview.query.get_or_404(rid)
        return jsonify(r.to_dict(include_detail=True))
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    r = SubsystemReview.query.get_or_404(rid)
    data = request.get_json() or {}
    if r.status not in (REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED):
        return jsonify({'error': f'当前状态 {r.status} 不可修改'}), 400
    for k in ('title', 'period', 'summary', 'verdict', 'subsystem'):
        if k in data:
            setattr(r, k, data[k])
    if 'group_review_ids' in data:
        r.group_review_ids = json.dumps(data['group_review_ids'], ensure_ascii=False)
    if 'key_metrics' in data:
        r.key_metrics = json.dumps(data['key_metrics'], ensure_ascii=False)
    if 'findings' in data:
        r.findings = json.dumps(data['findings'], ensure_ascii=False)
    if 'decisions' in data:
        r.decisions = json.dumps(data['decisions'], ensure_ascii=False)
    if 'next_steps' in data:
        r.next_steps = json.dumps(data['next_steps'], ensure_ascii=False)
    db.session.commit()
    return jsonify(r.to_dict())


@bp.route('/subsystem/<int:rid>/submit', methods=['POST'])
@login_required
def submit_subsystem_review(rid):
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    r = SubsystemReview.query.get_or_404(rid)
    if r.status != REVIEW_STATUS_DRAFT:
        return jsonify({'error': f'当前状态 {r.status} 不可提交'}), 400
    r.status = REVIEW_STATUS_SUBMITTED
    r.submitted_at = datetime.utcnow()
    db.session.commit()
    return jsonify(r.to_dict())


@bp.route('/subsystem/<int:rid>/review', methods=['POST'])
@login_required
def review_subsystem_review(rid):
    r = SubsystemReview.query.get_or_404(rid)
    if r.status != REVIEW_STATUS_SUBMITTED:
        return jsonify({'error': f'当前状态 {r.status} 不可审批'}), 400
    if r.manager_id == current_user.id:
        return jsonify({'error': '不能审核自己创建的 review'}), 400
    if not current_user.is_admin:
        member = ProjectMember.query.filter_by(project_id=r.project_id, user_id=current_user.id).first()
        if not member or member.role not in ('owner', 'editor'):
            return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'error': 'action 必须是 approve 或 reject'}), 400
    r.status = REVIEW_STATUS_APPROVED if action == 'approve' else REVIEW_STATUS_REJECTED
    r.reviewed_by = current_user.id
    r.reviewed_at = datetime.utcnow()
    r.review_comment = data.get('comment', '')
    db.session.commit()
    return jsonify(r.to_dict(include_detail=True))


# =========================================================================
# Snapshot API
# =========================================================================

@bp.route('/snapshots', methods=['GET'])
@login_required
def list_snapshots():
    """列出所有快照 (review_snapshot)"""
    pid = request.args.get('project_id', type=int)
    q = ReviewSnapshot.query
    if pid:
        q = q.filter(ReviewSnapshot.project_id == pid)
    rows = q.order_by(ReviewSnapshot.created_at.desc()).limit(500).all()
    return jsonify([r.to_dict() for r in rows])


@bp.route('/snapshots', methods=['POST'])
@bp.route('/snapshot', methods=['POST'])
@login_required
def create_snapshot():
    """创建 Review 快照 (仅 admin)"""
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    if not current_user.is_admin:
        return jsonify({'error': 'forbidden, 仅 admin 可创建 snapshot'}), 403
    data = request.get_json() or {}
    if not data.get('project_id') or not data.get('name'):
        return jsonify({'error': 'project_id, name 必填'}), 400

    # 自动从 subsystem_review 冻结数据 (如果指定了 subsystem_review_id)
    frozen = {}
    sub_review_id = data.get('subsystem_review_id')
    if sub_review_id:
        sr = SubsystemReview.query.get(sub_review_id)
        if sr and sr.project_id == data['project_id']:
            # 收集 group reviews 关联的 tile reviews -> records
            try:
                grp_ids = json.loads(sr.group_review_ids) if sr.group_review_ids else []
            except (json.JSONDecodeError, TypeError):
                grp_ids = []
            grps = GroupReview.query.filter(GroupReview.id.in_(grp_ids)).all() if grp_ids else []
            tile_ids = set()
            for g in grps:
                try:
                    tids = json.loads(g.tile_review_ids) if g.tile_review_ids else []
                except (json.JSONDecodeError, TypeError):
                    tids = []
                tile_ids.update(tids)
            tiles = TileReview.query.filter(TileReview.id.in_(tile_ids)).all() if tile_ids else []
            rec_ids = [t.record_id for t in tiles if t.record_id]
            frozen = {
                'subsystem_review_id': sr.id,
                'subsystem': sr.subsystem,
                'tile_review_ids': list(tile_ids),
                'record_ids': rec_ids,
                'aggregate': json.loads(sr.aggregate) if sr.aggregate else None,
            }
            initial_record_count = len(rec_ids)
        else:
            initial_record_count = 0
    else:
        initial_record_count = 0

    frozen_str = json.dumps(frozen, ensure_ascii=False, sort_keys=True)
    snap = ReviewSnapshot(
        project_id=data['project_id'],
        name=data['name'],
        description=data.get('description', ''),
        snapshot_type=data.get('snapshot_type', 'milestone'),
        subsystem_review_id=sub_review_id,
        frozen_data=frozen_str,
        record_count=initial_record_count,
        file_count=0,
        checksum=DataSnapshot.compute_checksum(frozen_str),
        created_by=current_user.id,
    )
    db.session.add(snap)
    db.session.commit()
    return jsonify(snap.to_dict()), 201


@bp.route('/snapshots/<int:rid>/verify', methods=['GET'])
@login_required
def verify_snapshot(rid):
    """校验快照完整性"""
    snap = ReviewSnapshot.query.get_or_404(rid)
    ok = snap.verify_integrity()
    return jsonify({'id': rid, 'verified': ok})


@bp.route('/snapshot/<int:rid>', methods=['GET'])
@bp.route('/snapshots/<int:rid>', methods=['GET'])
@login_required
def get_snapshot(rid):
    snap = ReviewSnapshot.query.get_or_404(rid)
    return jsonify(snap.to_dict(include_data=True))


@bp.route('/snapshot/<int:rid>', methods=['DELETE'])
@bp.route('/snapshots/<int:rid>', methods=['DELETE'])
@login_required
def delete_snapshot(rid):
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    snap = ReviewSnapshot.query.get_or_404(rid)
    if snap.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(snap)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/snapshot/<int:rid>/upload', methods=['POST'])
@bp.route('/snapshots/<int:rid>/upload', methods=['POST'])
@login_required
def upload_snapshot_file(rid):
    """上传快照附件"""
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    snap = ReviewSnapshot.query.get_or_404(rid)
    if 'file' not in request.files:
        return jsonify({'error': '缺少文件'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': '文件名为空'}), 400

    upload_dir = current_app.config['UPLOAD_FOLDER']
    snap_dir = os.path.join(upload_dir, 'review_snapshots', str(rid))
    os.makedirs(snap_dir, exist_ok=True)

    # 防路径穿越
    safe_name = os.path.basename(f.filename)
    storage_path = os.path.join(snap_dir, safe_name)
    f.save(storage_path)

    file_size = os.path.getsize(storage_path)
    # 计算文件 SHA256 校验和 (用于完整性校验)
    import hashlib
    with open(storage_path, 'rb') as _fp:
        file_checksum = hashlib.sha256(_fp.read()).hexdigest()
    rf = ReviewFile(
        snapshot_id=rid,
        filename=safe_name,
        storage_path=storage_path,
        file_size=file_size,
        content_type=f.mimetype or 'application/octet-stream',
        checksum=file_checksum,
        category=request.form.get('category', 'rpt'),
        description=request.form.get('description', ''),
        uploaded_by=current_user.id,
    )
    db.session.add(rf)
    # 更新 snapshot 的 file_count
    snap.file_count = (snap.file_count or 0) + 1
    db.session.commit()
    return jsonify(rf.to_dict()), 201


@bp.route('/file/<int:fid>/download', methods=['GET'])
@login_required
def download_review_file(fid):
    if current_user.is_release:
        return jsonify({'error': 'forbidden'}), 403
    rf = ReviewFile.query.get_or_404(fid)
    if not os.path.exists(rf.storage_path):
        return jsonify({'error': 'file not found'}), 404
    return send_file(rf.storage_path, as_attachment=True, download_name=rf.filename)
