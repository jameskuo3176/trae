"""API v1 蓝图

负责纯 REST API (供 React/Vue 前端及自动化集成消费):
  - /projects (项目 CRUD)
  - /projects/{id}/members (成员管理)
  - /locks (数据锁)
  - /apikeys (API Key 管理)
  - /upload (CSV multipart 自动化上传)
  - /qor/upload (JSON 统一上传: §6.5 + 原始 DC 报告)
  - /alerts (告警规则与事件)

认证方式:
  - X-API-Key 请求头
  - 浏览器 session
"""
import json
import re
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
from services.json_upload import (
    JSONUploadError,
    validate_upload_json,
    json_to_qor_records,
    json_to_violation_records,
    json_to_notes_records,
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


# ----------------------------------------------------------------------------
# 原始 DC 报告上传处理
# ----------------------------------------------------------------------------

def _handle_dc_report_upload(dc_report: dict, user):
    """处理原始 DC 报告 JSON 上传.

    流程:
      1. 校验 DC 报告 (scheme_version, top_module, run.directory, timing.default.scenarios)
      2. 从 URL query 参数 (?project_id=&version=&mark_released=) 读取元数据
         (DC 报告本身不含这些信息, project/version 由调用方提供)
      3. 自动用 top_module 创建/查找 Module
      4. 调 convert_dc_to_qor_record 转 §6.5 record
      5. 走 save_records_to_db 落库 (与 §6.5 共用底层逻辑)
      6. 把原始 DC 报告全文写入 QorRecord.raw_dc_report (供 dashboard 表格视图)

    响应同 §6.5 上传协议, 额外字段:
      - format: 'dc_report'
      - module_name: <top_module>
    """
    # 1. 校验
    try:
        from scripts.dc_report_to_json import (
            validate_dc_report as _validate_dc,
            DCReportError,
            convert_dc_to_qor_record,
        )
        _validate_dc(dc_report)
    except ImportError:
        return jsonify({
            'error': 'DC 报告上传需要 scripts/dc_report_to_json.py 模块',
        }), 500
    except DCReportError as e:
        return jsonify({
            'error': e.message,
            'path': e.path,
        }), 400

    # 2. 从 query 参数提取 project_id / version / mark_released
    #    优先级: ?project_id= > upload.project_id (DC 报告内, 兜底) > 403
    project_id = request.args.get('project_id', type=int)
    version = request.args.get('version')
    mark_released_q = request.args.get('mark_released', '').lower() in ('1', 'true', 'yes')
    full_dir_override = request.args.get('full_dir') or None
    release_dir_override = request.args.get('release_dir') or None

    # 兼容: 允许 DC 报告内嵌一个 upload.project_id (覆盖 ?project_id=)
    inline_upload = dc_report.get('upload') or {}
    if not project_id and isinstance(inline_upload.get('project_id'), int):
        project_id = int(inline_upload['project_id'])
    if not version and isinstance(inline_upload.get('version'), str):
        version = inline_upload['version']
    if not mark_released_q and inline_upload.get('mark_released') is True:
        mark_released_q = True

    if not project_id or project_id < 1:
        return jsonify({
            'error': '缺少 project_id (通过 ?project_id=N 或 DC 报告内嵌 upload.project_id 提供)',
        }), 400
    if not version:
        return jsonify({
            'error': '缺少 version (通过 ?version=v1.0 或 DC 报告内嵌 upload.version 提供)',
        }), 400

    # 3. 权限 + 数据锁
    if not can_edit_project(user, project_id):
        return jsonify({'error': '无权限上传到此项目'}), 403
    writable, err = check_project_writable(project_id)
    if not writable:
        return jsonify({'error': err}), 403

    # 4. 转换 DC 报告 → §6.5 record (1 个 DC = 1 条 record)
    payload = convert_dc_to_qor_record(
        dc_report,
        project_id=project_id,
        version=version,
        full_dir_override=full_dir_override,
        release_dir_override=release_dir_override,
        mark_released=mark_released_q,
    )
    records = payload['records']  # 始终 1 条
    top_module = records[0]['module_name']

    # 4.1 把嵌套结构 (timing/area/cells/ratios/congestion) 摊平为顶层字段,
    #     以便 save_records_to_db (期望 wns_setup / area_total / cell_count 等顶层字段) 能正确写入
    for r in records:
        timing = r.get('timing') or {}
        setup = timing.get('setup') or {}
        if 'wns_setup' not in r and setup.get('wns') is not None:
            r['wns_setup'] = setup['wns']
        if 'tns_setup' not in r and setup.get('tns') is not None:
            r['tns_setup'] = setup['tns']
        if 'nvp_setup' not in r and setup.get('nvp') is not None:
            r['nvp_setup'] = setup['nvp']
        hold = timing.get('hold') or {}
        if 'wns_hold' not in r and hold.get('wns') is not None:
            r['wns_hold'] = hold['wns']
        if 'tns_hold' not in r and hold.get('tns') is not None:
            r['tns_hold'] = hold['tns']
        if 'nvp_hold' not in r and hold.get('nvp') is not None:
            r['nvp_hold'] = hold['nvp']

        area = r.get('area') or {}
        if 'area_total' not in r and area.get('total') is not None:
            r['area_total'] = area['total']
        if 'area_combinational' not in r and area.get('combinational') is not None:
            r['area_combinational'] = area['combinational']
        if 'area_sequential' not in r and area.get('sequential') is not None:
            r['area_sequential'] = area['sequential']
        if 'area_macro' not in r and area.get('macro') is not None:
            r['area_macro'] = area['macro']
        if 'area_black_box' not in r and area.get('memory') is not None:
            r['area_black_box'] = area['memory']
        elif 'area_black_box' not in r and area.get('black_box') is not None:
            r['area_black_box'] = area['black_box']

        cells = r.get('cells') or {}
        if 'cell_count' not in r and cells.get('cell_count') is not None:
            r['cell_count'] = cells['cell_count']
        if 'sequential_cell_count' not in r and cells.get('sequential_cell_count') is not None:
            r['sequential_cell_count'] = cells['sequential_cell_count']
        if 'instance_count' not in r and cells.get('instance_count') is not None:
            r['instance_count'] = cells['instance_count']
        if 'ram_cell_count' not in r and cells.get('ram_cell_count') is not None:
            r['ram_cell_count'] = cells['ram_cell_count']
        if 'macro_cell_count' not in r and cells.get('macro_cell_count') is not None:
            r['macro_cell_count'] = cells['macro_cell_count']

        ratios = r.get('ratios') or {}
        if 'utilization' not in r and ratios.get('utilization') is not None:
            r['utilization'] = ratios['utilization']
        if 'mbb_ratio' not in r and ratios.get('mbb_ratio') is not None:
            r['mbb_ratio'] = ratios['mbb_ratio']
        if 'clock_gating_ratio' not in r and ratios.get('clock_gating_ratio') is not None:
            r['clock_gating_ratio'] = ratios['clock_gating_ratio']

        cong = r.get('congestion') or {}
        if 'congestion_b' not in r and cong.get('max') is not None:
            r['congestion_b'] = cong['max']
        if 'congestion_h' not in r and cong.get('h') is not None:
            r['congestion_h'] = cong['h']
        if 'congestion_v' not in r and cong.get('v') is not None:
            r['congestion_v'] = cong['v']

    # 5. 切到目标项目库, 自动创建 Module
    project = Project.query.get_or_404(project_id)
    result = {
        'ok': True,
        'format': 'dc_report',
        'schema_version': '1.0',
        'saved': 0,
        'updated': 0,
        'skipped': 0,
        'record_ids': [],
        'alerts_triggered': 0,
        'module_name': top_module,
        'uploaded_by': user.username,
    }
    triggered_alerts: list = []

    with switch_to_project(project_id):
        # 自动创建/查找 Module (按 top_module)
        mod = Module.query.filter_by(project_id=project_id, name=top_module).first()
        if not mod:
            mod = Module(
                project_id=project_id,
                name=top_module,
                description=f'auto-created from DC report (top_module={top_module})',
            )
            db.session.add(mod)
            db.session.flush()
        module_id = mod.id

        # 检查数据锁
        locked_by_other, lock = check_data_lock('module', module_id, user)
        if locked_by_other:
            return jsonify({
                'error': f'模块被 {lock.user.username} 锁定',
                'lock': lock.to_dict(),
            }), 409

        saved, skipped, updated = save_records_to_db(
            records, project, module_id, version,
            source_filename='json:dc_report',
            mark_released=mark_released_q,
            owner_id=user.id,
            default_release_dir=release_dir_override,
        )
        result['saved'] = saved
        result['updated'] = updated
        result['skipped'] = skipped

        # 把 raw_dc_report + register_count 写入刚保存的 QorRecord
        # (在 commit 之前, 避免二次 commit 后 session 状态导致查询不到)
        if saved or updated:
            # 4.2a 预处理: 解析 congestion.summary_lines 注入 H/V 数值字段,
            #         转换 both_dirs_percentage 从字符串 "0.19%" → 数值 0.0019
            _dc = dc_report  # 浅拷贝引用, 直接修改原始 dict (不影响后续)
            misc = _dc.get('misc') or {}
            cong = misc.get('congestion') or {}
            # 解析 both_dirs_percentage
            bdp_raw = cong.get('both_dirs_percentage')
            if isinstance(bdp_raw, str):
                bdp_clean = bdp_raw.strip().rstrip('%')
                try:
                    bdp_val = float(bdp_clean)
                    cong['both_dirs_percentage'] = bdp_val / 100.0 if bdp_val > 1.0 else bdp_val
                except (ValueError, TypeError):
                    pass
            # 解析 H/V routing from summary_lines
            if isinstance(cong.get('summary_lines'), list):
                for line in cong['summary_lines']:
                    if not isinstance(line, str):
                        continue
                    m = re.search(r'^\s*([HV])\s+routing:.*?GRCs\s*=\s*\d+\s*\(([\d.]+)%\)', line)
                    if m:
                        direction = m.group(1).lower()  # 'h' or 'v'
                        gcrs_pct_str = m.group(2)
                        try:
                            gcrs_pct = float(gcrs_pct_str)
                            cong[direction] = gcrs_pct / 100.0 if gcrs_pct > 1.0 else gcrs_pct
                        except (ValueError, TypeError):
                            pass
            raw_json = json.dumps(_dc, ensure_ascii=False)
            for r in records:
                rd_full = r.get('full_dir') or ''
                qq = QorRecord.query.filter_by(
                    module_id=module_id,
                    version=version or 'v1',
                )
                if rd_full:
                    qq = qq.filter_by(full_dir=rd_full)
                qor = qq.first()
                if qor:
                    qor.raw_dc_report = raw_json
                    # register_count 也单独保存 (从 record 提取)
                    if r.get('register_count') is not None:
                        try:
                            qor.register_count = int(r['register_count'])
                        except (TypeError, ValueError):
                            pass
        db.session.commit()

        # 收集 record_id + 告警
        affected_records: list = []
        seen_ids: set = set()
        for r in records:
            mn = r.get('module_name')
            if not mn:
                continue
            m = Module.query.filter_by(project_id=project_id, name=mn).first()
            if not m:
                continue
            rd_full = r.get('full_dir') or ''
            qq = QorRecord.query.filter_by(module_id=m.id, version=version or 'v1')
            if rd_full:
                qq = qq.filter_by(full_dir=rd_full)
            qor = qq.first()
            if qor and qor.id not in seen_ids:
                seen_ids.add(qor.id)
                affected_records.append(qor)
        for qor in affected_records:
            result['record_ids'].append(qor.id)
            triggered_alerts.extend(check_alerts_for_new_record(qor))

    result['alerts_triggered'] = len(triggered_alerts)
    if triggered_alerts:
        result['alerts'] = [
            {'rule_id': a.get('rule_id'), 'level': a.get('level'),
             'message': a.get('message')}
            for a in triggered_alerts
        ]
    return jsonify(result)


@bp.route('/qor/upload', methods=['POST'])
@api_auth_required(required_scope='upload')
@with_db_retry()
def api_v1_qor_upload_json():
    """JSON 统一上传端点 (兼容 §6.5 上传协议 + 原始 DC 报告)

    两种输入格式:
      1. §6.5 上传协议: {schema_version, upload: {project_id, version, ...}, records: [...]}
      2. 原始 DC 报告:  {scheme_version (int), top_module, run.directory, timing, area, misc}
                         - 自动检测: 顶层含 top_module + timing + area + misc
                         - 自动用 top_module 作为 module_name, project_id/version
                           从 URL query 参数 (优先) 或 upload 段读取
                         - 原始报告全文存 QorRecord.raw_dc_report

    响应:
      {
        "ok": true,
        "schema_version": "1.0",
        "saved": 1, "updated": 0, "skipped": 0,
        "record_ids": [42], "alerts_triggered": 0,
        "format": "dc_report" | "v6.5",
        "module_name": "modulea_t",  # DC 格式时
        "uploaded_by": "admin"
      }
    """
    user = g.auth_user

    # 1. 解析 JSON 主体
    data = request.get_json(silent=True)

    # 1.1 检测格式: 原始 DC 报告 vs §6.5 上传协议
    #     DC 报告特征: 顶层同时含 top_module + timing + area + misc
    is_dc = (
        isinstance(data, dict)
        and all(k in data for k in ('top_module', 'timing', 'area', 'misc'))
    )
    if is_dc:
        return _handle_dc_report_upload(data, user)

    # 1.2 否则按 §6.5 协议处理
    try:
        data = validate_upload_json(data)
    except JSONUploadError as e:
        return jsonify({
            'error': e.message,
            'path': e.path,
        }), e.status_code

    upload = data['upload']
    project_id = upload['project_id']
    version = upload['version']
    mark_released = bool(upload.get('mark_released', False))
    default_module_id = upload.get('module_id')
    default_release_dir = upload.get('release_dir') or None
    default_full_dir = upload.get('full_dir') or None

    # 2. 权限 + 数据锁
    if not can_edit_project(user, project_id):
        return jsonify({'error': '无权限上传到此项目'}), 403
    writable, err = check_project_writable(project_id)
    if not writable:
        return jsonify({'error': err}), 403

    if default_module_id:
        locked_by_other, lock = check_data_lock('module', int(default_module_id), user)
        if locked_by_other:
            return jsonify({
                'error': f'模块被 {lock.user.username} 锁定',
                'lock': lock.to_dict(),
            }), 409
    else:
        locked_by_other, lock = check_data_lock('project', project_id, user)
        if locked_by_other:
            return jsonify({
                'error': f'项目被 {lock.user.username} 锁定',
                'lock': lock.to_dict(),
            }), 409

    project = Project.query.get_or_404(project_id)

    # 3. 汇总响应
    result = {
        'ok': True,
        'schema_version': data['schema_version'],
        'saved': 0,
        'updated': 0,
        'skipped': 0,
        'violation_paths_saved': 0,
        'violation_paths_skipped': 0,
        'notes_saved': 0,
        'notes_skipped': 0,
        'record_ids': [],
        'alerts_triggered': 0,
        'metadata_recorded': bool(data.get('metadata')),
        'uploaded_by': user.username,
    }
    triggered_alerts: list = []

    # 4a. records → save_records_to_db
    raw_records = data.get('records') or []
    if raw_records:
        try:
            records = json_to_qor_records(
                data,
                default_version=version,
                default_full_dir=default_full_dir,
                default_release_dir=default_release_dir,
            )
            if not records:
                result['warnings'] = (result.get('warnings') or []) + [
                    'records[] 全部因缺 module_name/version 被跳过',
                ]
            else:
                # 必须切到目标项目库, 否则 db_routing 兜底逻辑会把数据
                # 写入第 1 个项目库 (跨项目路由默认行为)
                with switch_to_project(project_id):
                    saved, skipped, updated = save_records_to_db(
                        records, project, default_module_id, version,
                        source_filename='json:upload',
                        mark_released=mark_released,
                        owner_id=user.id,
                        default_release_dir=default_release_dir,
                    )
                    db.session.commit()
                    result['saved'] += saved
                    result['updated'] += updated
                    result['skipped'] += skipped

                    # 收集 record_id + 触发告警
                    # 一个 request 可能包含多条 record (例如 DC 报告 N 个 scenario×path_group),
                    # 每条 record 通过 (module_id, version, full_dir) 唯一定位.
                    affected_records: list = []
                    seen_ids: set = set()
                    for r in records:
                        mn = r.get('module_name')
                        if not mn:
                            continue
                        m = Module.query.filter_by(project_id=project_id, name=mn).first()
                        if not m:
                            continue
                        # 提取本条 record 的 full_dir (与 save_records_to_db 一致)
                        rd_full = r.get('full_dir') or ''
                        if not rd_full and isinstance(r.get('extra_fields'), dict):
                            rd_full = (r['extra_fields'] or {}).get('full_dir') or ''
                        if not rd_full and isinstance(r.get('extra_fields'), str):
                            try:
                                _ef = json.loads(r['extra_fields'])
                                if isinstance(_ef, dict):
                                    rd_full = _ef.get('full_dir') or ''
                            except Exception:
                                pass
                        rec_version = version or 'v1'
                        qq = QorRecord.query.filter_by(
                            module_id=m.id, version=rec_version,
                        )
                        if rd_full:
                            qq = qq.filter_by(full_dir=rd_full)
                        qor = qq.first()
                        if qor and qor.id not in seen_ids:
                            seen_ids.add(qor.id)
                            affected_records.append(qor)
                    for qor in affected_records:
                        result['record_ids'].append(qor.id)
                        triggered_alerts.extend(check_alerts_for_new_record(qor))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('JSON upload: records save failed')
            return jsonify({
                'error': f'保存 records 失败: {e}',
                'stage': 'records',
            }), 500

    # 4b. violation_paths → save_violations_to_db
    raw_violations = data.get('violation_paths') or []
    if raw_violations:
        try:
            vp_records = json_to_violation_records(data, default_version=version)
            # 按 timing_group 分组 (CSV 端点行为)
            from collections import defaultdict
            by_group: dict = defaultdict(list)
            for v in vp_records:
                tg = v.get('timing_group') or 'default'
                by_group[tg].append(v)
            total_saved = total_skipped = 0
            with switch_to_project(project_id):
                for tg, recs in by_group.items():
                    saved, skipped = save_violations_to_db(
                        recs, project, default_module_id, version,
                        source_filename='json:upload', timing_group=tg,
                    )
                    db.session.commit()
                    total_saved += saved
                    total_skipped += skipped
            result['violation_paths_saved'] += total_saved
            result['violation_paths_skipped'] += total_skipped
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('JSON upload: violations save failed')
            return jsonify({
                'error': f'保存 violation_paths 失败: {e}',
                'stage': 'violation_paths',
            }), 500

    # 4c. notes → save_notes_to_db
    raw_notes = data.get('notes') or []
    if raw_notes:
        try:
            note_records = json_to_notes_records(data, default_full_dir=default_full_dir)
            if note_records:
                with switch_to_project(project_id):
                    saved, skipped = save_notes_to_db(
                        note_records, project, default_module_id, version,
                        source_filename='json:upload',
                        full_dir=default_full_dir,
                    )
                    db.session.commit()
                result['notes_saved'] += saved
                result['notes_skipped'] += skipped
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('JSON upload: notes save failed')
            return jsonify({
                'error': f'保存 notes 失败: {e}',
                'stage': 'notes',
            }), 500

    result['alerts_triggered'] = len(triggered_alerts)
    result['alerts'] = triggered_alerts  # 供客户端按需展示
    return jsonify(result)


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
