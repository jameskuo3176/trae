"""API v1 蓝图

负责纯 REST API (供 React/Vue 前端及自动化集成消费):
  - /projects (项目 CRUD)
  - /projects/{id}/members (成员管理)
  - /locks (数据锁)
  - /apikeys (API Key 管理)
  - /upload (自动化上传)
  - /alerts (告警规则与事件)

认证方式:
  - X-API-Key 请求头
  - 浏览器 session
"""
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from flask_login import current_user

from api_auth import (
    api_auth_required, require_project_access, get_user_project_role,
    can_access_project, can_edit_project, can_manage_project,
    check_project_writable, check_data_lock,
)
from core.db import with_db_retry
from core.db_routing import switch_to_project
from models import (
    db, User, Project, Module, ProjectMember, QorRecord,
    DataLock, ApiKey, AlertRule, AlertEvent,
)
from qor_parser import parse_csv_file, parse_violation_csv, parse_notes_csv
from services.qor_import import (
    save_records_to_db, merge_power_to_db, save_violations_to_db, save_notes_to_db,
)
from alerts import check_alerts_for_new_record

bp = Blueprint('api_v1', __name__)


# =========================================================================
# 项目管理
# =========================================================================

@bp.route('/projects')
@api_auth_required()
def api_v1_list_projects():
    """获取当前用户可访问的项目列表"""
    user = g.auth_user
    projects = Project.query.order_by(Project.created_at).all()
    result = []
    for p in projects:
        if not can_access_project(user, p.id):
            continue
        # 跨库 viewonly 关系: 用 switch_to_project 切到项目库查 module 数
        try:
            with switch_to_project(p.id):
                module_count = Module.query.filter_by(project_id=p.id).count()
        except Exception:
            current_app.logger.exception(
                'api_v1_list_projects: stats failed for project_id=%s', p.id,
            )
            module_count = 0
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'my_role': get_user_project_role(user, p.id),
            'module_count': module_count,
        })
    return jsonify(result)


@bp.route('/projects', methods=['POST'])
@api_auth_required(required_scope='upload')
def api_v1_create_project():
    """创建新项目 (创建者自动成为 owner)"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '项目名不能为空'}), 400

    project = Project(name=name, description=data.get('description', ''))
    db.session.add(project)
    db.session.flush()
    member = ProjectMember(project_id=project.id, user_id=user.id, role='owner')
    db.session.add(member)
    db.session.commit()
    return jsonify({
        'id': project.id, 'name': project.name,
        'description': project.description, 'my_role': 'owner',
    }), 201


@bp.route('/projects/<int:project_id>')
@api_auth_required()
def api_v1_get_project(project_id):
    """获取项目详情"""
    user = g.auth_user
    if not can_access_project(user, project_id):
        return jsonify({'error': '无权限访问此项目'}), 403
    p = Project.query.get_or_404(project_id)
    return jsonify({
        'id': p.id, 'name': p.name, 'description': p.description,
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'my_role': get_user_project_role(user, p.id),
        'modules': [{
            'id': m.id, 'name': m.name, 'description': m.description,
            'record_count': m.qor_records.count(),
        } for m in p.modules.order_by(Module.name)],
    })


# =========================================================================
# 项目成员管理
# =========================================================================

@bp.route('/projects/<int:project_id>/members')
@api_auth_required()
def api_v1_list_members(project_id):
    """获取项目成员列表"""
    user = g.auth_user
    if not can_access_project(user, project_id):
        return jsonify({'error': '无权限'}), 403
    members = ProjectMember.query.filter_by(project_id=project_id).all()
    return jsonify([m.to_dict() for m in members])


@bp.route('/projects/<int:project_id>/members', methods=['POST'])
@api_auth_required()
def api_v1_add_member(project_id):
    """添加项目成员"""
    user = g.auth_user
    if not can_manage_project(user, project_id):
        return jsonify({'error': '需要项目管理权限'}), 403
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    role = data.get('role', 'viewer')
    if role not in ('owner', 'editor', 'viewer'):
        return jsonify({'error': '无效角色'}), 400
    target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({'error': '用户不存在'}), 404
    existing = ProjectMember.query.filter_by(project_id=project_id, user_id=target.id).first()
    if existing:
        existing.role = role
        db.session.commit()
        return jsonify(existing.to_dict())
    m = ProjectMember(project_id=project_id, user_id=target.id, role=role)
    db.session.add(m)
    db.session.commit()
    return jsonify(m.to_dict()), 201


@bp.route('/projects/<int:project_id>/members/<int:member_id>', methods=['DELETE'])
@api_auth_required()
def api_v1_remove_member(project_id, member_id):
    """移除项目成员"""
    user = g.auth_user
    if not can_manage_project(user, project_id):
        return jsonify({'error': '需要项目管理权限'}), 403
    m = ProjectMember.query.filter_by(id=member_id, project_id=project_id).first_or_404()
    if m.role == 'owner':
        owners = ProjectMember.query.filter_by(project_id=project_id, role='owner').count()
        if owners <= 1:
            return jsonify({'error': '不能移除最后一个 owner'}), 400
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# 数据锁
# =========================================================================

@bp.route('/locks')
@api_auth_required()
def api_v1_list_locks():
    """获取当前活跃的数据锁"""
    resource_type = request.args.get('resource_type')
    resource_id = request.args.get('resource_id', type=int)
    q = DataLock.query
    if resource_type:
        q = q.filter_by(resource_type=resource_type)
    if resource_id:
        q = q.filter_by(resource_id=resource_id)
    locks = q.order_by(DataLock.locked_at.desc()).all()
    return jsonify([l.to_dict() for l in locks if not l.is_expired])


@bp.route('/locks', methods=['POST'])
@api_auth_required()
def api_v1_create_lock():
    """加锁资源"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    resource_type = (data.get('resource_type') or '').strip()
    try:
        resource_id = int(data.get('resource_id'))
    except (TypeError, ValueError):
        resource_id = None
    reason = data.get('reason', '')
    duration_minutes = data.get('duration_minutes', 30)

    if resource_type not in ('project', 'module', 'record'):
        return jsonify({'error': '无效 resource_type'}), 400
    if not resource_id:
        return jsonify({'error': '缺少 resource_id'}), 400

    if resource_type == 'project':
        if not can_manage_project(user, resource_id):
            return jsonify({'error': '无权限锁定此项目'}), 403
    elif resource_type == 'module':
        mod = Module.query.get(resource_id)
        if not mod or not can_edit_project(user, mod.project_id):
            return jsonify({'error': '无权限锁定此模块'}), 403
    else:
        rec = QorRecord.query.get(resource_id)
        if not rec:
            return jsonify({'error': '记录不存在'}), 404
        mod = rec.module
        if not can_edit_project(user, mod.project_id):
            return jsonify({'error': '无权限锁定此记录'}), 403

    locked_by_other, existing = check_data_lock(resource_type, resource_id, user)
    if locked_by_other:
        return jsonify({
            'error': f'资源已被 {existing.user.username} 锁定',
            'lock': existing.to_dict(),
        }), 409

    if existing:
        db.session.delete(existing)
        db.session.flush()

    lock = DataLock(
        resource_type=resource_type,
        resource_id=resource_id,
        locked_by=user.id,
        expires_at=datetime.utcnow() + timedelta(minutes=duration_minutes),
        reason=reason,
    )
    db.session.add(lock)
    db.session.commit()
    return jsonify(lock.to_dict()), 201


@bp.route('/locks/<int:lock_id>', methods=['DELETE'])
@api_auth_required()
def api_v1_release_lock(lock_id):
    """释放锁"""
    user = g.auth_user
    lock = DataLock.query.get_or_404(lock_id)
    if lock.locked_by != user.id and not user.is_admin:
        return jsonify({'error': '只能释放自己持有的锁'}), 403
    db.session.delete(lock)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# API Key 管理
# =========================================================================

@bp.route('/apikeys')
@api_auth_required()
def api_v1_list_apikeys():
    """列出当前用户的 API Keys"""
    user = g.auth_user
    keys = ApiKey.query.filter_by(user_id=user.id).order_by(ApiKey.created_at.desc()).all()
    return jsonify([k.to_dict() for k in keys])


@bp.route('/apikeys', methods=['POST'])
@api_auth_required()
def api_v1_create_apikey():
    """创建新 API Key (明文仅返回一次)"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    scopes = data.get('scopes', 'read')
    days = data.get('expires_in_days')

    if not name:
        return jsonify({'error': '请填写 API Key 名称'}), 400
    for s in scopes.split(','):
        if s.strip() not in ('read', 'upload', 'admin'):
            return jsonify({'error': f'无效 scope: {s}'}), 400

    plaintext = ApiKey.generate_key()
    api_key = ApiKey(
        user_id=user.id,
        key_hash=ApiKey.hash_key(plaintext),
        prefix=plaintext[:12],
        name=name,
        scopes=scopes,
        expires_at=datetime.utcnow() + timedelta(days=days) if days else None,
    )
    db.session.add(api_key)
    db.session.commit()
    return jsonify({
        'id': api_key.id,
        'key': plaintext,
        'name': api_key.name,
        'prefix': api_key.prefix,
        'scopes': api_key.scopes,
        'expires_at': api_key.expires_at.isoformat() if api_key.expires_at else None,
    }), 201


@bp.route('/apikeys/<int:key_id>', methods=['DELETE'])
@api_auth_required()
def api_v1_revoke_apikey(key_id):
    """吊销 API Key"""
    user = g.auth_user
    k = ApiKey.query.filter_by(id=key_id, user_id=user.id).first_or_404()
    k.revoked = True
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# 自动化上传 (DC 流程)
# =========================================================================

@bp.route('/upload', methods=['POST'])
@api_auth_required(required_scope='upload')
@with_db_retry()
def api_v1_upload():
    """自动化数据上传端点 (支持 API Key 认证)"""
    user = g.auth_user

    project_id = request.form.get('project_id')
    module_id = request.form.get('module_id')
    version = request.form.get('version', '').strip()
    data_type = request.form.get('data_type', 'qor')
    mark_released = request.form.get('mark_released') in ('1', 'true', 'on', 'yes')
    upload_full_dir = request.form.get('full_dir', '').strip() if data_type == 'notes' else ''
    # 整批统一 release_dir (覆盖 CSV 自带值)
    upload_release_dir = request.form.get('release_dir', '').strip() or None
    # 限制长度
    if upload_release_dir and len(upload_release_dir) > 500:
        return jsonify({'error': 'release_dir 长度不能超过 500'}), 400

    if not project_id:
        return jsonify({'error': '缺少 project_id'}), 400
    if not can_edit_project(user, int(project_id)):
        return jsonify({'error': '无权限上传到此项目'}), 403

    writable, err = check_project_writable(int(project_id))
    if not writable:
        return jsonify({'error': err}), 403

    if module_id:
        locked_by_other, lock = check_data_lock('module', int(module_id), user)
        if locked_by_other:
            return jsonify({'error': f'模块被 {lock.user.username} 锁定', 'lock': lock.to_dict()}), 409
    else:
        locked_by_other, lock = check_data_lock('project', int(project_id), user)
        if locked_by_other:
            return jsonify({'error': f'项目被 {lock.user.username} 锁定', 'lock': lock.to_dict()}), 409

    project = Project.query.get_or_404(project_id)

    files = request.files.getlist('files')
    if not files:
        if 'file' in request.files:
            files = [request.files['file']]
    files = [f for f in files if f and f.filename and f.filename.lower().endswith('.csv')]
    if not files:
        return jsonify({'error': '请上传至少一个 CSV 文件'}), 400

    total_saved = total_skipped = total_updated = total_merged = 0
    file_results = []
    triggered_alerts = []

    for f in files:
        content = f.read()
        try:
            if data_type == 'violation':
                result = parse_violation_csv(content, filename=f.filename)
            elif data_type == 'notes':
                result = parse_notes_csv(content, filename=f.filename, default_full_dir=upload_full_dir)
            else:
                result = parse_csv_file(content, default_project=project.name,
                                        default_module=None, default_version=version or None)
            records = result['records']
            stats = result['stats']
        except Exception as e:
            file_results.append({'filename': f.filename, 'ok': False, 'error': str(e)})
            continue

        if not records:
            file_results.append({'filename': f.filename, 'ok': False, 'error': '无有效数据'})
            continue

        try:
            if data_type == 'power':
                merged, created = merge_power_to_db(
                    records, project, module_id, version, f.filename,
                    mark_released=mark_released, owner_id=user.id,
                )
                db.session.commit()
                total_merged += merged
                total_saved += created
            elif data_type == 'violation':
                saved, skipped = save_violations_to_db(records, project, module_id, version, f.filename, stats.get('timing_group'))
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
            elif data_type == 'notes':
                saved, skipped = save_notes_to_db(records, project, module_id, version, f.filename, full_dir=upload_full_dir or None)
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
            else:
                saved, skipped, updated = save_records_to_db(
                    records, project, module_id, version, f.filename,
                    mark_released=mark_released, owner_id=user.id,
                    default_release_dir=upload_release_dir,
                )
                db.session.commit()
                affected_mods = set()
                for r in records:
                    mn = r.get('module_name')
                    if mn:
                        m = Module.query.filter_by(project_id=project.id, name=mn).first()
                        if m:
                            affected_mods.add(m.id)
                    elif module_id:
                        affected_mods.add(int(module_id))
                for mid in affected_mods:
                    rec_version = version or 'v1'
                    qor = QorRecord.query.filter_by(module_id=mid, version=rec_version).first()
                    if qor:
                        triggered_alerts.extend(check_alerts_for_new_record(qor))
                total_saved += saved
                total_skipped += skipped
                total_updated += updated
            file_results.append({
                'filename': f.filename, 'ok': True,
                'saved': saved if data_type != 'power' else created,
                'stats': stats,
            })
        except Exception as e:
            db.session.rollback()
            file_results.append({'filename': f.filename, 'ok': False, 'error': str(e)})

    return jsonify({
        'ok': True,
        'saved_count': total_saved,
        'skipped_count': total_skipped,
        'updated_count': total_updated,
        'merged_count': total_merged,
        'alerts_triggered': len(triggered_alerts),
        'file_count': len(files),
        'file_results': file_results,
        'uploaded_by': user.username,
    })


# =========================================================================
# 告警规则与事件
# =========================================================================

@bp.route('/alerts/rules')
@api_auth_required()
def api_v1_list_alert_rules():
    """获取告警规则列表"""
    user = g.auth_user
    project_id = request.args.get('project_id', type=int)
    if project_id and not can_access_project(user, project_id):
        return jsonify({'error': '无权限'}), 403
    q = AlertRule.query
    if project_id:
        q = q.filter_by(project_id=project_id)
    if not user.is_admin:
        accessible = db.session.query(ProjectMember.project_id).filter_by(user_id=user.id).subquery()
        q = q.filter(AlertRule.project_id.in_(accessible))
    rules = q.order_by(AlertRule.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rules])


@bp.route('/alerts/rules', methods=['POST'])
@api_auth_required()
def api_v1_create_alert_rule():
    """创建告警规则"""
    user = g.auth_user
    data = request.get_json(silent=True) or {}
    try:
        project_id = int(data.get('project_id'))
    except (TypeError, ValueError):
        project_id = None
    if not project_id:
        return jsonify({'error': '缺少 project_id'}), 400
    if not can_manage_project(user, project_id):
        return jsonify({'error': '需要项目管理权限'}), 403
    if data.get('direction') not in ('worsen', 'improve', 'threshold'):
        return jsonify({'error': '无效 direction'}), 400

    rule = AlertRule(
        project_id=project_id,
        module_id=data.get('module_id'),
        metric=data.get('metric', 'wns_setup'),
        direction=data.get('direction', 'worsen'),
        threshold=data.get('threshold'),
        window_size=data.get('window_size', 1),
        sensitivity=data.get('sensitivity', 0.2),
        enabled=data.get('enabled', True),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify(rule.to_dict()), 201


@bp.route('/alerts/rules/<int:rule_id>', methods=['PUT', 'DELETE'])
@api_auth_required()
def api_v1_modify_alert_rule(rule_id):
    """更新或删除告警规则"""
    user = g.auth_user
    rule = AlertRule.query.get_or_404(rule_id)
    if not can_manage_project(user, rule.project_id):
        return jsonify({'error': '无权限'}), 403
    if request.method == 'DELETE':
        db.session.delete(rule)
        db.session.commit()
        return jsonify({'ok': True})
    data = request.get_json(silent=True) or {}
    for field in ('metric', 'direction', 'threshold', 'window_size', 'sensitivity', 'enabled', 'module_id'):
        if field in data:
            setattr(rule, field, data[field])
    db.session.commit()
    return jsonify(rule.to_dict())


@bp.route('/alerts/events')
@api_auth_required()
def api_v1_list_alert_events():
    """获取告警事件列表"""
    user = g.auth_user
    project_id = request.args.get('project_id', type=int)
    acknowledged = request.args.get('acknowledged')
    limit = min(request.args.get('limit', 100, type=int), 500)

    q = AlertEvent.query.join(AlertRule)
    if project_id:
        if not can_access_project(user, project_id):
            return jsonify({'error': '无权限'}), 403
        q = q.filter(AlertRule.project_id == project_id)
    elif not user.is_admin:
        accessible = db.session.query(ProjectMember.project_id).filter_by(user_id=user.id).subquery()
        q = q.filter(AlertRule.project_id.in_(accessible))

    if acknowledged == 'true':
        q = q.filter(AlertEvent.acknowledged_by.isnot(None))
    elif acknowledged == 'false':
        q = q.filter(AlertEvent.acknowledged_by.is_(None))

    events = q.order_by(AlertEvent.triggered_at.desc()).limit(limit).all()
    return jsonify([e.to_dict() for e in events])


@bp.route('/alerts/events/<int:event_id>/acknowledge', methods=['POST'])
@api_auth_required()
def api_v1_acknowledge_event(event_id):
    """确认告警事件"""
    user = g.auth_user
    ev = AlertEvent.query.get_or_404(event_id)
    rule = ev.rule
    if not can_access_project(user, rule.project_id):
        return jsonify({'error': '无权限'}), 403
    ev.acknowledged_by = user.id
    ev.acknowledged_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ev.to_dict())
