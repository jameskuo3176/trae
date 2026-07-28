"""管理后台 API 蓝图

负责:
  - 项目管理 (创建/删除/锁定/解锁)
  - 模块管理
  - 数据快照管理
  - 备份管理
  - 记录管理
  - 用户管理
  - 数据上传 (CSV/Block QoR)
"""
import json
import os
import re
import shutil
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from api_auth import (
    can_access_project, can_edit_project, can_manage_project,
    check_project_writable, check_data_lock,
)
from core.db import with_db_retry
from core.db_routing import switch_to_project
from models import (
    db, User, Project, Module, QorRecord, DataSnapshot, BackupRecord,
    ProjectMember, ViolationPath,
)
from qor_parser import parse_csv_file, parse_violation_csv, parse_notes_csv
from services.qor_import import (
    save_records_to_db, merge_power_to_db, save_violations_to_db,
    save_notes_to_db, _sync_congestion,
)
from alerts import check_alerts_for_new_record

bp = Blueprint('admin', __name__)


def _project_module_record_counts(project_id: int):
    """在项目库上下文内安全统计 module/record 数量

    跨库 viewonly 关系 p.modules 是 list, .count() 是 Python list.count()
    会报 TypeError. 这里改用 switch_to_project + Module.query.count()
    走 ORM bind 路由. 若项目库文件丢失, 返回 (0, 0, False).
    """
    from core.project_db import project_db_path
    db_path = project_db_path(project_id)
    if not os.path.exists(db_path):
        return 0, 0, False
    try:
        with switch_to_project(project_id):
            module_count = Module.query.filter_by(project_id=project_id).count()
            record_count = QorRecord.query.join(
                Module, QorRecord.module_id == Module.id,
            ).filter(Module.project_id == project_id).count()
        return module_count, record_count, True
    except Exception:
        current_app.logger.exception(
            'project_db stats failed for project_id=%s', project_id,
        )
        return 0, 0, False


# =========================================================================
# 项目管理
# =========================================================================

@bp.route('/projects', methods=['POST'])
@login_required
@with_db_retry()
def admin_create_project():
    """创建新项目

    按项目分库:
      - 主库记录项目元信息
      - 同时创建独立的项目 DB 文件 (qor_p_<id>.db)
      - 把项目 DB 路径写入 Project.db_path
    """
    if not current_user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '项目名不能为空'}), 400
    if Project.query.filter_by(name=name).first():
        return jsonify({'error': '项目名已存在'}), 400
    p = Project(name=name, description=data.get('description', ''))
    db.session.add(p)
    db.session.commit()

    # 创建项目独立 DB 文件 (按项目分库)
    try:
        from core.project_db import create_project_db, project_db_path
        create_project_db(p.id)
        p.db_path = project_db_path(p.id)
        db.session.commit()
    except Exception as e:
        # 回滚: 删掉已建项目, 不留半成品
        db.session.delete(p)
        db.session.commit()
        return jsonify({'error': f'创建项目数据库失败: {e}'}), 500

    return jsonify(p.to_dict())


@bp.route('/projects/<int:project_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_project(project_id):
    """软删除项目 (隐藏, 数据保留, 可后续恢复)

    与 hard delete 不同:
      - 实际将 status 置为 'hidden', 记录 hidden_at / hidden_by
      - 数据 (模块/记录/成员/快照) 全部保留在数据库
      - 默认 /api/projects 不再列出, 需通过 /api/admin/projects/hidden 恢复
    """
    p = Project.query.get_or_404(project_id)
    if not can_manage_project(current_user, project_id):
        return jsonify({'error': '无权限'}), 403
    if p.status == 'hidden':
        return jsonify({'error': '项目已是隐藏状态'}), 400

    p.status = 'hidden'
    p.hidden_at = datetime.utcnow()
    p.hidden_by = current_user.id
    db.session.commit()
    return jsonify({
        'ok': True,
        'message': f'项目 "{p.name}" 已隐藏 (数据保留, 可在 "已隐藏项目" 中恢复)',
        'project_id': p.id,
    })


@bp.route('/projects/hidden', methods=['GET'])
@login_required
@with_db_retry()
def admin_list_hidden_projects():
    """列出所有已隐藏的项目 (仅 admin)"""
    if not current_user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    projects = Project.query.filter_by(status='hidden').order_by(Project.hidden_at.desc()).all()
    result = []
    for p in projects:
        module_count, record_count, db_ok = _project_module_record_counts(p.id)
        hider = User.query.get(p.hidden_by) if p.hidden_by else None
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'status': p.status,
            'module_count': module_count,
            'record_count': record_count,
            'project_db_exists': db_ok,
            'hidden_at': p.hidden_at.isoformat() if p.hidden_at else None,
            'hidden_by': p.hidden_by,
            'hidden_by_name': hider.username if hider else None,
            'created_at': p.created_at.isoformat() if p.created_at else None,
        })
    return jsonify(result)


@bp.route('/projects/<int:project_id>/restore', methods=['POST'])
@login_required
@with_db_retry()
def admin_restore_project(project_id):
    """恢复已隐藏的项目 (仅 admin)

    将 status 置回 'active', 清空 hidden_at / hidden_by.
    """
    if not current_user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    p = Project.query.get_or_404(project_id)
    if p.status != 'hidden':
        return jsonify({'error': f'项目状态为 {p.status}, 不需要恢复'}), 400

    p.status = 'active'
    p.hidden_at = None
    p.hidden_by = None
    db.session.commit()
    return jsonify({
        'ok': True,
        'message': f'项目 "{p.name}" 已恢复为 active',
        'project': p.to_dict(),
    })


@bp.route('/projects/<int:project_id>/hard_delete', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_hard_delete_project(project_id):
    """彻底删除项目 (仅 admin, 不可逆, 警告级操作)

    与软删除不同, 此操作会级联删除所有 modules / records / members / snapshots.
    仅对已隐藏项目开放 (二次确认流程), 避免误操作.
    """
    if not current_user.is_admin:
        return jsonify({'error': '需要管理员权限'}), 403
    p = Project.query.get_or_404(project_id)
    if p.status != 'hidden':
        return jsonify({'error': '只能彻底删除已隐藏项目, 请先软删除'}), 400

    # 二次确认: 调用方需传 confirm=true
    data = request.get_json(silent=True) or request.args
    if str(data.get('confirm', '')).lower() not in ('1', 'true', 'yes'):
        module_count, record_count, _ = _project_module_record_counts(p.id)
        return jsonify({
            'error': '此操作不可逆! 请传 confirm=true 二次确认',
            'warning': f'将永久删除项目 "{p.name}" 及其 {module_count} 个模块, '
                       f'{record_count} 条记录',
        }), 400

    project_name = p.name
    db.session.delete(p)
    db.session.commit()
    return jsonify({
        'ok': True,
        'message': f'项目 "{project_name}" 已彻底删除 (不可恢复)',
    })


@bp.route('/projects/<int:project_id>/lock', methods=['POST'])
@login_required
@with_db_retry()
def admin_lock_project(project_id):
    """锁定项目"""
    p = Project.query.get_or_404(project_id)
    if not can_manage_project(current_user, project_id):
        return jsonify({'error': '无权限'}), 403
    p.status = 'locked'
    p.locked_at = datetime.utcnow()
    p.locked_by = current_user.id
    p.lock_reason = (request.get_json() or {}).get('reason', '')
    db.session.commit()
    return jsonify(p.to_dict())


@bp.route('/projects/<int:project_id>/unlock', methods=['POST'])
@login_required
@with_db_retry()
def admin_unlock_project(project_id):
    """解锁项目"""
    p = Project.query.get_or_404(project_id)
    if not can_manage_project(current_user, project_id):
        return jsonify({'error': '无权限'}), 403
    p.status = 'active'
    p.locked_at = None
    p.locked_by = None
    p.lock_reason = None
    db.session.commit()
    return jsonify(p.to_dict())


# =========================================================================
# 快照管理
# =========================================================================

@bp.route('/projects/<int:project_id>/snapshots', methods=['POST'])
@login_required
def admin_create_snapshot(project_id):
    """创建项目数据快照"""
    if not can_edit_project(current_user, project_id):
        return jsonify({'error': '无权限创建此项目的快照 (需要 editor 及以上角色)'}), 403
    p = Project.query.get_or_404(project_id)
    data = request.get_json() or request.form
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '快照名称不能为空'}), 400

    records = QorRecord.query.join(Module).filter(Module.project_id == project_id).all()
    snapshot_data = [r.to_dict() for r in records]
    data_json = json.dumps(snapshot_data, ensure_ascii=False, default=str)

    snap = DataSnapshot(
        project_id=project_id,
        name=name,
        description=data.get('description', ''),
        snapshot_type=data.get('snapshot_type', 'milestone'),
        data=data_json,
        record_count=len(snapshot_data),
        checksum=DataSnapshot.compute_checksum(data_json),
        created_by=current_user.id,
    )
    db.session.add(snap)
    db.session.commit()
    return jsonify(snap.to_dict())


@bp.route('/projects/<int:project_id>/snapshots')
@login_required
def admin_list_snapshots(project_id):
    """列出项目的所有快照"""
    if not can_access_project(current_user, project_id):
        return jsonify({'error': '无权限查看此项目的快照'}), 403
    Project.query.get_or_404(project_id)
    snaps = DataSnapshot.query.filter_by(project_id=project_id).order_by(DataSnapshot.created_at.desc()).all()
    return jsonify([s.to_dict() for s in snaps])


@bp.route('/snapshots/<int:snap_id>')
@login_required
def admin_get_snapshot(snap_id):
    """获取快照详情 (含完整数据)"""
    snap = DataSnapshot.query.get_or_404(snap_id)
    if not can_access_project(current_user, snap.project_id):
        return jsonify({'error': '无权限查看此快照'}), 403
    if not snap.verify_integrity():
        return jsonify({'error': '快照数据校验失败, 可能已被篡改', 'verified': False}), 500
    return jsonify(snap.to_dict(include_data=True))


@bp.route('/snapshots/<int:snap_id>/verify', methods=['POST'])
@login_required
def admin_verify_snapshot(snap_id):
    """校验快照完整性"""
    snap = DataSnapshot.query.get_or_404(snap_id)
    ok = snap.verify_integrity()
    return jsonify({'id': snap_id, 'verified': ok, 'checksum': snap.prefix_checksum})


@bp.route('/snapshots/<int:snap_id>/rollback', methods=['POST'])
@login_required
@with_db_retry()
def admin_rollback_snapshot(snap_id):
    """回滚项目到指定快照状态"""
    snap = DataSnapshot.query.get(snap_id)
    if snap is None:
        return jsonify({'error': '快照不存在'}), 404
    if not can_manage_project(current_user, snap.project_id):
        return jsonify({'error': '无权限回滚此项目 (需要 owner 及以上角色)'}), 403
    if not snap.verify_integrity():
        return jsonify({'error': '快照数据校验失败, 拒绝回滚'}), 500

    writable, err = check_project_writable(snap.project_id)
    if not writable:
        return jsonify({'error': f'项目当前不可写: {err}'}), 403

    try:
        snapshot_data = json.loads(snap.data)
    except (json.JSONDecodeError, TypeError):
        return jsonify({'error': '快照数据解析失败'}), 500

    project = Project.query.get_or_404(snap.project_id)

    # 1. 创建 pre_rollback 快照
    current_records = QorRecord.query.join(Module).filter(Module.project_id == snap.project_id).all()
    current_data = [r.to_dict() for r in current_records]
    current_json = json.dumps(current_data, ensure_ascii=False, default=str)
    pre_snap = DataSnapshot(
        project_id=snap.project_id,
        name=f'[Auto] Before rollback to "{snap.name}"',
        description=f'自动创建于回滚操作, 由 {current_user.username} 触发',
        snapshot_type='custom',
        data=current_json,
        record_count=len(current_data),
        checksum=DataSnapshot.compute_checksum(current_json),
        created_by=current_user.id,
    )
    db.session.add(pre_snap)

    module_map = {m.name: m.id for m in project.modules.all()}

    for r in current_records:
        db.session.delete(r)
    db.session.flush()

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
        )
        _sync_congestion(rec)
        if item.get('extra_fields') and isinstance(item['extra_fields'], dict):
            rec.extra_fields = json.dumps(item['extra_fields'], ensure_ascii=False)
        db.session.add(rec)
        restored += 1

    db.session.commit()
    return jsonify({
        'ok': True,
        'rolled_back_to': snap.to_dict(),
        'pre_rollback_snapshot': pre_snap.to_dict(),
        'restored_count': restored,
        'skipped_count': skipped,
    })


@bp.route('/snapshots/<int:snap_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_snapshot(snap_id):
    """删除快照"""
    snap = DataSnapshot.query.get_or_404(snap_id)
    if not can_edit_project(current_user, snap.project_id):
        return jsonify({'error': '无权限删除此项目的快照 (需要 editor 及以上角色)'}), 403
    db.session.delete(snap)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# 备份管理
# =========================================================================

@bp.route('/backups')
@login_required
def admin_list_backups():
    """列出所有备份"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    backups = BackupRecord.query.order_by(BackupRecord.created_at.desc()).limit(100).all()
    return jsonify([b.to_dict() for b in backups])


@bp.route('/backups', methods=['POST'])
@login_required
def admin_create_backup():
    """手动创建备份"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    from services.backup_service import perform_backup
    result = perform_backup(backup_type='manual', user=current_user)
    return jsonify(result)


@bp.route('/backups/verify', methods=['POST'])
@login_required
def admin_verify_all_backups():
    """校验所有备份"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    from services.backup_service import verify_all_backups
    return jsonify(verify_all_backups())


# =========================================================================
# 模块管理
# =========================================================================

@bp.route('/modules', methods=['POST'])
@login_required
@with_db_retry()
def admin_create_module():
    """创建模块"""
    data = request.get_json() or request.form
    project_id = data.get('project_id')
    name = (data.get('name') or '').strip()
    if not project_id or not name:
        return jsonify({'error': '项目ID和模块名称不能为空'}), 400
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return jsonify({'error': '无效的 project_id'}), 400
    if not can_edit_project(current_user, pid):
        return jsonify({'error': '无权限在此项目创建模块 (需要 editor 及以上角色)'}), 403
    Project.query.get_or_404(project_id)
    if Module.query.filter_by(project_id=project_id, name=name).first():
        return jsonify({'error': '模块已存在'}), 400
    m = Module(project_id=project_id, name=name, description=data.get('description', ''))
    db.session.add(m)
    db.session.commit()
    return jsonify({'id': m.id, 'name': m.name})


@bp.route('/modules/<int:module_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_module(module_id):
    """删除模块"""
    m = Module.query.get_or_404(module_id)
    if m.project:
        if not can_manage_project(current_user, m.project.id):
            return jsonify({'error': '无权限删除模块 (需要 owner 及以上角色)'}), 403
        writable, err = check_project_writable(m.project.id)
        if not writable:
            return jsonify({'error': err}), 403
    else:
        if not current_user.is_admin:
            return jsonify({'error': '无权限'}), 403
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/modules/batch', methods=['POST'])
@login_required
def admin_batch_create_modules():
    """批量创建模块"""
    if request.is_json:
        data = request.get_json()
        project_id = data.get('project_id')
        module_names = data.get('module_names', [])
    else:
        project_id = request.form.get('project_id')
        module_list_text = request.form.get('module_list', '')
        module_names = [n.strip() for n in module_list_text.replace(',', '\n').split('\n') if n.strip()]

    if not project_id:
        return jsonify({'error': '请选择项目'}), 400
    if not module_names:
        return jsonify({'error': '模块名称列表不能为空'}), 400

    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return jsonify({'error': '无效的 project_id'}), 400
    if not can_edit_project(current_user, pid):
        return jsonify({'error': '无权限在此项目批量创建模块 (需要 editor 及以上角色)'}), 403

    Project.query.get_or_404(project_id)

    created = []
    skipped = []
    for name in module_names:
        name = name.strip()
        if not name:
            continue
        if Module.query.filter_by(project_id=project_id, name=name).first():
            skipped.append(name)
        else:
            m = Module(project_id=project_id, name=name)
            db.session.add(m)
            created.append(name)

    db.session.commit()

    return jsonify({
        'ok': True,
        'created_count': len(created),
        'skipped_count': len(skipped),
        'created': created,
        'skipped': skipped,
        'message': f'创建 {len(created)} 个模块' + (f'，跳过 {len(skipped)} 个已存在' if skipped else ''),
    })


# =========================================================================
# 记录管理
# =========================================================================

@bp.route('/records/<int:record_id>', methods=['DELETE'])
@login_required
@with_db_retry()
def admin_delete_record(record_id):
    """删除单条 QoR 记录"""
    r = QorRecord.query.get_or_404(record_id)

    if current_user.is_release:
        return jsonify({'error': '无权限 (release 角色不可删除)'}), 403

    if r.module and r.module.project:
        writable, err = check_project_writable(r.module.project.id)
        if not writable:
            return jsonify({'error': err}), 403

    is_admin = bool(current_user.is_admin)

    if not is_admin:
        if not (r.module and r.module.project and can_edit_project(current_user, r.module.project.id)):
            return jsonify({'error': '无权限删除此项目记录 (需要项目 owner/editor 角色)'}), 403
        if r.owner_id != current_user.id:
            return jsonify({
                'error': '无权限: 该记录由其他用户上传, 您只能删除自己上传的记录',
                'owner_username': r.owner.username if r.owner else None,
            }), 403

    db.session.delete(r)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/records/owners')
@login_required
def admin_list_record_owners():
    """返回上传过 QoR 记录的用户列表"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    rows = db.session.query(QorRecord.owner_id).filter(QorRecord.owner_id.isnot(None)).distinct().all()
    owner_ids = [r[0] for r in rows if r[0] is not None]
    if not owner_ids:
        return jsonify([])
    users = User.query.filter(User.id.in_(owner_ids)).order_by(User.username).all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'display_name': u.display_name or u.username,
    } for u in users])


# =========================================================================
# 数据上传 - QoR
# =========================================================================

@bp.route('/upload', methods=['POST'])
@login_required
@with_db_retry()
def admin_upload_csv():
    """上传 QoR / Power / Violation / Notes CSV"""
    project_id = request.form.get('project_id')
    module_id = request.form.get('module_id')
    version = request.form.get('version', '').strip()
    data_type = request.form.get('data_type', 'qor')
    mark_released = request.form.get('mark_released') in ('1', 'true', 'on', 'yes')
    upload_full_dir = request.form.get('full_dir', '').strip() if data_type == 'notes' else ''

    if not project_id:
        return jsonify({'error': '缺少 project_id'}), 400
    if not can_edit_project(current_user, int(project_id)):
        return jsonify({'error': '无权限上传到此项目'}), 403

    writable, err = check_project_writable(int(project_id))
    if not writable:
        return jsonify({'error': err}), 403

    if module_id:
        locked_by_other, lock = check_data_lock('module', int(module_id), current_user)
        if locked_by_other:
            return jsonify({'error': f'模块被 {lock.user.username} 锁定', 'lock': lock.to_dict()}), 409
    else:
        locked_by_other, lock = check_data_lock('project', int(project_id), current_user)
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

    file_paths = request.form.getlist('file_paths') if 'file_paths' in request.form else []
    file_paths = file_paths if len(file_paths) == len(files) else [f.filename for f in files]

    # 模块名提取辅助
    module_name_source = request.form.get('module_name_source', 'csv').strip()
    filename_suffixes = request.form.get('filename_suffixes', '_qor,qor,_qor_report').strip()
    _suffix_tokens = tuple(s.strip().lower() for s in filename_suffixes.split(',') if s.strip())

    def _extract_module_from_filename(fname):
        base = os.path.basename(fname or '')
        name, _ext = os.path.splitext(base)
        name_lower = name.lower()
        changed = True
        while changed:
            changed = False
            for tok in _suffix_tokens:
                if name_lower.endswith(tok) and len(name_lower) > len(tok):
                    name = name[: -len(tok)]
                    name_lower = name.lower()
                    changed = True
        return name.strip() or None

    def _extract_module_from_dirname(fname):
        parent = os.path.basename(os.path.dirname(fname or ''))
        return parent.strip() or None

    total_saved = total_skipped = total_updated = total_merged = 0
    file_results = []
    triggered_alerts = []

    for file_idx, file in enumerate(files):
        file_content = file.read()
        file_path = file_paths[file_idx] if file_idx < len(file_paths) else file.filename

        try:
            if data_type == 'violation':
                result = parse_violation_csv(file_content, filename=file.filename)
            elif data_type == 'notes':
                result = parse_notes_csv(file_content, filename=file.filename, default_full_dir=upload_full_dir)
            else:
                file_default_module = None
                if not module_id:
                    if module_name_source == 'filename':
                        file_default_module = _extract_module_from_filename(file_path)
                    elif module_name_source == 'dirname':
                        file_default_module = _extract_module_from_dirname(file_path)
                        if not file_default_module:
                            file_default_module = _extract_module_from_filename(file_path)
                    else:
                        file_default_module = _extract_module_from_dirname(file_path) or \
                                              _extract_module_from_filename(file_path)
                result = parse_csv_file(
                    file_content,
                    default_project=project.name,
                    default_module=file_default_module,
                    default_version=version or None,
                )
            records = result['records']
            stats = result['stats']
        except Exception as e:
            file_results.append({
                'filename': file.filename, 'ok': False, 'error': f'CSV 解析失败: {str(e)}',
            })
            continue

        if not records:
            file_results.append({
                'filename': file.filename, 'ok': False, 'error': '文件中没有有效数据', 'stats': stats,
            })
            continue

        try:
            triggered_alerts = []
            if data_type == 'power':
                merged, created = merge_power_to_db(
                    records, project, module_id, version, file.filename,
                    mark_released=mark_released,
                    owner_id=current_user.id if current_user.is_authenticated else None,
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
                    qors = QorRecord.query.filter_by(module_id=mid).all()
                    for q in qors:
                        if q.version == (version or r.get('version') or 'v1'):
                            evts = check_alerts_for_new_record(q)
                            triggered_alerts.extend(evts)
                total_merged += merged
                total_saved += created
                file_results.append({
                    'filename': file.filename, 'ok': True, 'saved': created, 'merged': merged,
                    'stats': stats, 'alerts_triggered': len(triggered_alerts),
                })
            elif data_type == 'violation':
                saved, skipped = save_violations_to_db(records, project, module_id, version, file.filename, stats.get('timing_group'))
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
                file_results.append({
                    'filename': file.filename, 'ok': True, 'saved': saved, 'skipped': skipped, 'stats': stats,
                })
            elif data_type == 'notes':
                saved, skipped = save_notes_to_db(records, project, module_id, version, file.filename, full_dir=upload_full_dir or None)
                db.session.commit()
                total_saved += saved
                total_skipped += skipped
                file_results.append({
                    'filename': file.filename, 'ok': True, 'saved': saved, 'skipped': skipped, 'stats': stats,
                })
            else:
                saved, skipped, updated = save_records_to_db(
                    records, project, module_id, version, file.filename,
                    mark_released=mark_released,
                    owner_id=current_user.id if current_user.is_authenticated else None,
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
                        evts = check_alerts_for_new_record(qor)
                        triggered_alerts.extend(evts)
                total_saved += saved
                total_skipped += skipped
                total_updated += updated
                file_results.append({
                    'filename': file.filename, 'ok': True, 'saved': saved, 'updated': updated,
                    'skipped': skipped, 'stats': stats, 'alerts_triggered': len(triggered_alerts),
                })
        except Exception as e:
            db.session.rollback()
            file_results.append({
                'filename': file.filename, 'ok': False, 'error': f'数据库保存失败: {str(e)}',
            })

    if data_type == 'power':
        msg = f'功耗数据合并完成: 合并 {total_merged} 条，新建 {total_saved} 条'
    else:
        msg = f'成功导入 {total_saved} 条记录'
        if total_updated:
            msg += f'，更新 {total_updated} 条'
        if total_skipped:
            msg += f'，跳过 {total_skipped} 条'

    return jsonify({
        'ok': True,
        'saved_count': total_saved,
        'skipped_count': total_skipped,
        'merged_count': total_merged,
        'updated_count': total_updated,
        'data_type': data_type,
        'file_count': len(files),
        'file_results': file_results,
        'message': msg,
    })


# =========================================================================
# Block QoR 上传
# =========================================================================

@bp.route('/upload_block_qor', methods=['POST'])
@login_required
@with_db_retry()
def admin_upload_block_qor():
    """上传 block_qor.csv 补充 FlopCount / FlopCount_incr 到已有 QoR 记录"""
    project_id = request.form.get('project_id')
    pid = None
    if project_id:
        try:
            pid = int(project_id)
        except (ValueError, TypeError):
            return jsonify({'error': '无效的 project_id'}), 400
        if not can_edit_project(current_user, pid):
            return jsonify({'error': '无权限补充此项目数据 (需要 editor 及以上角色)'}), 403

    files = request.files.getlist('files')
    if not files:
        if 'file' in request.files:
            files = [request.files['file']]
    files = [f for f in files if f and f.filename and f.filename.lower().endswith('.csv')]
    if not files:
        return jsonify({'error': '请上传至少一个 CSV 文件'}), 400

    file_paths = request.form.getlist('file_paths') if 'file_paths' in request.form else []
    file_paths = file_paths if len(file_paths) == len(files) else [f.filename for f in files]

    import csv as _csv
    import io as _io

    def _parse_int_safe(v):
        if v is None:
            return None
        try:
            return int(float(str(v).strip()))
        except (ValueError, TypeError):
            return None

    def _normalize_header(h):
        return (h or '').strip().lower().replace(' ', '_')

    BLOCK_HEADER_ALIASES = {
        'fulldir': 'full_dir',
        'full_dir': 'full_dir',
        'flopcount': 'flop_count',
        'flop_count': 'flop_count',
        'flopcount_incr': 'flop_count_incr',
        'flop_count_incr': 'flop_count_incr',
    }

    # 预加载所有 QorRecord 的 full_dir 索引
    q = QorRecord.query
    if pid:
        q = q.join(Module).filter(Module.project_id == pid)
    all_qors = q.all()
    full_dir_index = {}
    for r in all_qors:
        fd = r.full_dir
        if not fd and r.extra_fields:
            try:
                ef = json.loads(r.extra_fields) if isinstance(r.extra_fields, str) else r.extra_fields
                if isinstance(ef, dict):
                    fd = ef.get('full_dir')
            except (ValueError, TypeError):
                fd = None
        if fd:
            full_dir_index.setdefault(str(fd).lower(), []).append(r)

    total_updated = 0
    total_missed = 0
    total_conflict = 0
    file_results = []

    for file_idx, file in enumerate(files):
        file_content = file.read()
        file_path = file_paths[file_idx] if file_idx < len(file_paths) else file.filename

        try:
            text_content = file_content.decode('utf-8-sig', errors='replace')
            reader = _csv.reader(_io.StringIO(text_content))
            rows = list(reader)
        except Exception as e:
            file_results.append({'filename': file.filename, 'ok': False, 'error': f'CSV 解析失败: {e}'})
            continue

        if len(rows) < 2:
            file_results.append({'filename': file.filename, 'ok': False, 'error': '文件无数据行'})
            continue

        headers = [_normalize_header(h) for h in rows[0]]
        col_map = {}
        for idx, h in enumerate(headers):
            std = BLOCK_HEADER_ALIASES.get(h)
            if std and std not in col_map:
                col_map[std] = idx

        if 'full_dir' not in col_map:
            file_results.append({'filename': file.filename, 'ok': False, 'error': 'CSV 缺少 Fulldir 列 (匹配键)'})
            continue

        fd_idx = col_map['full_dir']
        flop_idx = col_map.get('flop_count')
        flop_incr_idx = col_map.get('flop_count_incr')

        file_updated = 0
        file_missed = 0
        file_conflict = 0
        skipped_no_flop = 0
        missed_samples = []
        conflict_samples = []

        for row in rows[1:]:
            if not row or all(not c.strip() for c in row if c):
                continue
            if fd_idx >= len(row):
                continue
            fd_value = (row[fd_idx] or '').strip()
            if not fd_value or fd_value.lower() in ('-', 'n/a', 'none'):
                continue

            flop_val = _parse_int_safe(row[flop_idx]) if flop_idx is not None and flop_idx < len(row) else None
            flop_incr_val = _parse_int_safe(row[flop_incr_idx]) if flop_incr_idx is not None and flop_incr_idx < len(row) else None
            if flop_val is None and flop_incr_val is None:
                skipped_no_flop += 1
                continue

            matches = full_dir_index.get(fd_value.lower(), [])
            if len(matches) == 0:
                file_missed += 1
                if len(missed_samples) < 3:
                    missed_samples.append(fd_value)
                continue
            if len(matches) > 1:
                file_conflict += 1
                if len(conflict_samples) < 3:
                    conflict_samples.append(fd_value)
                continue

            rec = matches[0]
            try:
                extra = json.loads(rec.extra_fields) if rec.extra_fields else {}
                if isinstance(extra, str):
                    extra = json.loads(extra)
                if not isinstance(extra, dict):
                    extra = {}
            except (ValueError, TypeError):
                extra = {}

            changed = False
            if flop_val is not None and extra.get('FlopCount') != flop_val:
                extra['FlopCount'] = flop_val
                changed = True
            if flop_incr_val is not None and extra.get('FlopCount_incr') != flop_incr_val:
                extra['FlopCount_incr'] = flop_incr_val
                changed = True

            if changed:
                rec.extra_fields = json.dumps(extra, ensure_ascii=False)
                db.session.add(rec)
                file_updated += 1

        db.session.commit()

        file_results.append({
            'filename': file.filename, 'ok': True, 'updated': file_updated,
            'missed': file_missed, 'conflict': file_conflict, 'skipped_no_flop': skipped_no_flop,
            'missed_samples': missed_samples, 'conflict_samples': conflict_samples,
            'total_rows': len(rows) - 1,
        })
        total_updated += file_updated
        total_missed += file_missed
        total_conflict += file_conflict

    msg = f'补充完成: 更新 {total_updated} 条'
    if total_missed:
        msg += f'，未匹配 {total_missed} 条'
    if total_conflict:
        msg += f'，冲突 {total_conflict} 条'

    return jsonify({
        'ok': True,
        'updated_count': total_updated,
        'missed_count': total_missed,
        'conflict_count': total_conflict,
        'file_count': len(files),
        'file_results': file_results,
        'message': msg,
    })


# =========================================================================
# CSV 预览 (dry-run)
# =========================================================================

@bp.route('/upload_csv_preview', methods=['POST'])
@login_required
def admin_upload_csv_preview():
    """CSV 预览 (dry-run): 仅解析不写入 DB"""
    project_id = request.form.get('project_id')
    if not project_id:
        return jsonify({'error': '请选择项目'}), 400
    try:
        pid = int(project_id)
    except (ValueError, TypeError):
        return jsonify({'error': '无效的 project_id'}), 400
    if not can_edit_project(current_user, pid):
        return jsonify({'error': '无权限预览此项目数据 (需要 editor 及以上角色)'}), 403

    files = request.files.getlist('files')
    files = [f for f in files if f and f.filename and f.filename.lower().endswith('.csv')]
    if not files:
        return jsonify({'error': '请选择至少一个 CSV 文件'}), 400

    file_paths = request.form.getlist('file_paths') if 'file_paths' in request.form else []
    file_paths = file_paths if len(file_paths) == len(files) else [f.filename for f in files]

    version = request.form.get('version', '').strip()
    module_id = request.form.get('module_id')
    module_name_source = request.form.get('module_name_source', 'csv').strip()
    filename_suffixes = request.form.get('filename_suffixes', '_qor,qor,_qor_report').strip()
    _suffix_tokens = tuple(s.strip().lower() for s in filename_suffixes.split(',') if s.strip())

    def _extract_module_from_filename(fname):
        base = os.path.basename(fname or '')
        name, _ext = os.path.splitext(base)
        name_lower = name.lower()
        changed = True
        while changed:
            changed = False
            for tok in _suffix_tokens:
                if name_lower.endswith(tok) and len(name_lower) > len(tok):
                    name = name[: -len(tok)]
                    name_lower = name.lower()
                    changed = True
        return name.strip() or None

    def _extract_module_from_dirname(fname):
        parent = os.path.basename(os.path.dirname(fname or ''))
        return parent.strip() or None

    project = Project.query.get_or_404(project_id)
    file_reports = []
    for file_idx, file in enumerate(files):
        file_content = file.read()
        file_path = file_paths[file_idx] if file_idx < len(file_paths) else file.filename
        try:
            file_default_module = None
            if not module_id:
                if module_name_source == 'filename':
                    file_default_module = _extract_module_from_filename(file_path)
                elif module_name_source == 'dirname':
                    file_default_module = _extract_module_from_dirname(file_path)
                    if not file_default_module:
                        file_default_module = _extract_module_from_filename(file_path)
                else:
                    file_default_module = _extract_module_from_dirname(file_path) or \
                                          _extract_module_from_filename(file_path)
            result = parse_csv_file(
                file_content,
                default_project=project.name,
                default_module=file_default_module,
                default_version=version if version else None,
            )
            records = result['records']
            stats = result['stats']

            new_count = 0
            update_count = 0
            skip_count = 0
            warnings = []
            sample_records = []

            for rec in records[:3]:
                sample_records.append({
                    'module_name': rec.get('module_name'),
                    'version': rec.get('version') or version,
                    'area_total': rec.get('area_total'),
                    'wns_setup': rec.get('wns_setup'),
                    'cell_count': rec.get('cell_count'),
                })

            mod_cache = {}
            for rec in records:
                mod_name = (rec.get('module_name') or '').strip()
                if not mod_name:
                    skip_count += 1
                    continue
                rec_version = (rec.get('version') or version or 'v1').strip()
                if mod_name not in mod_cache:
                    mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                    mod_cache[mod_name] = mod.id if mod else None
                mod_id = mod_cache[mod_name]
                if mod_id:
                    existing = QorRecord.query.filter_by(module_id=mod_id, version=rec_version).first()
                    if existing:
                        update_count += 1
                    else:
                        new_count += 1
                else:
                    new_count += 1

                for f in ['area_total', 'wns_setup', 'tns_setup', 'cell_count']:
                    v = rec.get(f)
                    if v is not None:
                        try:
                            fv = float(v)
                            if fv != fv or fv in (float('inf'), float('-inf')):
                                warnings.append(f"{mod_name}/{rec_version}: {f} 值异常 ({v})")
                            elif f.startswith('area') and fv < 0:
                                warnings.append(f"{mod_name}/{rec_version}: {f} 为负数 ({v})")
                            elif f == 'area_total' and fv > 1e9:
                                warnings.append(f"{mod_name}/{rec_version}: {f} 异常大 ({v})")
                        except (ValueError, TypeError):
                            warnings.append(f"{mod_name}/{rec_version}: {f} 无法解析 ({v})")

            file_reports.append({
                'filename': file.filename, 'ok': True,
                'total_rows': stats.get('total_rows', 0), 'parsed': len(records),
                'would_create': new_count, 'would_update': update_count, 'would_skip': skip_count,
                'warnings': warnings[:20], 'warning_count': len(warnings),
                'sample': sample_records,
            })
        except Exception as e:
            file_reports.append({'filename': file.filename, 'ok': False, 'error': f'解析失败: {str(e)}'})

    return jsonify({
        'ok': True, 'dry_run': True, 'file_reports': file_reports,
        'message': '预览完成，数据未写入数据库',
    })


# =========================================================================
# QoR 发布管理
# =========================================================================

@bp.route('/qor/<int:record_id>/release', methods=['POST'])
@login_required
@with_db_retry()
def admin_toggle_release(record_id):
    """切换记录的发布状态"""
    r = QorRecord.query.get_or_404(record_id)
    if not current_user.is_admin:
        if r.module and r.module.project:
            if not can_edit_project(current_user, r.module.project.id):
                return jsonify({'error': '无权限'}), 403
    r.is_released = not r.is_released
    if r.is_released:
        r.released_at = datetime.utcnow()
        r.released_by = current_user.id
    else:
        r.released_at = None
        r.released_by = None
    db.session.commit()
    return jsonify({'id': r.id, 'is_released': r.is_released})


@bp.route('/qor/batch_release', methods=['POST'])
@login_required
@with_db_retry()
def admin_batch_release():
    """批量切换发布状态

    请求: {record_ids: [int], released: bool}
    响应: {ok: True, updated: int, skipped: int, failed: [{id, reason}]}
    """
    data = request.get_json() or {}
    record_ids = data.get('record_ids', [])
    if not record_ids:
        return jsonify({'error': 'record_ids 必填'}), 400
    if not isinstance(record_ids, list):
        return jsonify({'error': 'record_ids 必须为数组'}), 400
    # 限长防止滥用
    if len(record_ids) > 1000:
        return jsonify({'error': f'单次最多 1000 条, 当前 {len(record_ids)} 条'}), 400

    released = bool(data.get('released', True))
    updated = 0
    skipped = 0
    failed = []  # [{id, reason}]

    # 一次性查出所有记录, 避免 N+1
    records = QorRecord.query.filter(QorRecord.id.in_(record_ids)).all()
    records_map = {r.id: r for r in records}

    for rid in record_ids:
        r = records_map.get(rid)
        if not r:
            skipped += 1
            failed.append({'id': rid, 'reason': '记录不存在'})
            continue
        # 权限检查: 非 admin 必须有项目编辑权 + 是该记录 owner
        if not current_user.is_admin:
            if not (r.module and r.module.project and can_edit_project(current_user, r.module.project.id)):
                skipped += 1
                failed.append({'id': rid, 'reason': '无项目编辑权限'})
                continue
            if r.owner_id != current_user.id:
                skipped += 1
                failed.append({'id': rid, 'reason': '非记录 owner'})
                continue
        r.is_released = released
        if released:
            r.released_at = datetime.utcnow()
            r.released_by = current_user.id
        else:
            r.released_at = None
            r.released_by = None
        updated += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'数据库提交失败: {e}'}), 500

    return jsonify({
        'ok': True,
        'updated': updated,
        'skipped': skipped,
        'failed': failed,
    })


# =========================================================================
# 用户管理
# =========================================================================

@bp.route('/users')
@login_required
def admin_list_users():
    """获取用户列表"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    users = User.query.order_by(User.created_at).all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'role': u.role,
        'display_name': u.display_name,
        'created_at': u.created_at.strftime('%Y-%m-%d %H:%M') if u.created_at else '',
    } for u in users])


@bp.route('/users', methods=['POST'])
@login_required
def admin_create_user():
    """创建用户"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    role = data.get('role', 'user')
    display_name = data.get('display_name', '')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400
    if role not in ('admin', 'user', 'release'):
        return jsonify({'error': '无效的角色'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '用户名已存在'}), 400

    user = User(username=username, role=role, display_name=display_name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({'id': user.id, 'username': user.username, 'role': user.role})


@bp.route('/users/batch', methods=['POST'])
@login_required
def admin_batch_create_users():
    """批量创建用户"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    data = request.get_json() or {}

    raw = data.get('usernames', [])
    if isinstance(raw, str):
        usernames = [u.strip() for u in re.split(r'[\n,;\s]+', raw) if u.strip()]
    else:
        usernames = [str(u).strip() for u in raw if str(u).strip()]

    if not usernames:
        return jsonify({'error': '用户名列表不能为空'}), 400

    password = data.get('password') or '123456'
    role = data.get('role', 'user')
    if role not in ('admin', 'user', 'release'):
        return jsonify({'error': '无效的角色'}), 400

    created = []
    skipped = []

    existing = set(u.username for u in User.query.filter(
        User.username.in_(usernames),
    ).all())

    for uname in usernames:
        if uname in existing:
            skipped.append({'username': uname, 'reason': '用户名已存在'})
            continue
        user = User(username=uname, role=role)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.flush()
            created.append({'id': user.id, 'username': uname})
            existing.add(uname)
        except Exception as e:
            db.session.rollback()
            skipped.append({'username': uname, 'reason': str(e)})

    db.session.commit()
    return jsonify({
        'created': created,
        'skipped': skipped,
        'total': len(usernames),
        'default_password': password,
    })


@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
def admin_reset_user_password(user_id):
    """管理员重置指定用户的密码"""
    if not current_user.is_admin:
        return jsonify({'error': '无权限'}), 403
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    data = request.get_json(silent=True) or {}
    new_password = data.get('password') or 'Reset@123'

    user.set_password(new_password)
    db.session.commit()
    return jsonify({'ok': True, 'username': user.username, 'reset_to': new_password})


# =========================================================================
# 用户自助 (修改自己密码)
# =========================================================================

@bp.route('/user/password', methods=['POST'])
@login_required
def user_change_own_password():
    """用户修改自己的密码"""
    data = request.get_json() or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return jsonify({'error': '旧密码和新密码不能为空'}), 400
    if not current_user.check_password(old_password):
        return jsonify({'error': '旧密码错误'}), 400
    if old_password == new_password:
        return jsonify({'error': '新密码不能与旧密码相同'}), 400

    current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'ok': True})
