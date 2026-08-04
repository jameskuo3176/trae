"""Dashboard API 蓝图

负责:
  - 用户 Dashboard 配置 CRUD
  - Dashboard Group (项目级共享视图) CRUD
  - 用户主题
"""
import json
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from flask import current_app

import repo
from models import db, User, Project, UserDashboard, DashboardGroup

bp = Blueprint('dashboard', __name__)


# =========================================================================
# Dashboard 配置
# =========================================================================

@bp.route('/api/dashboard/save', methods=['POST'])
@login_required
def save_dashboard_config():
    """保存 Dashboard 配置"""
    data = request.get_json() or {}
    dash_id = data.get('id')
    name = (data.get('name') or 'My Dashboard').strip()
    config = data.get('config', {})
    is_default = data.get('is_default', False)

    if dash_id:
        dash = UserDashboard.query.filter_by(id=dash_id, user_id=current_user.id).first_or_404()
        dash.name = name
        dash.config = json.dumps(config, ensure_ascii=False)
        dash.is_default = is_default
    else:
        if is_default:
            # 取消其他 default
            UserDashboard.query.filter_by(user_id=current_user.id, is_default=True).update({'is_default': False})
        dash = UserDashboard(
            user_id=current_user.id,
            name=name,
            config=json.dumps(config, ensure_ascii=False),
            is_default=is_default,
        )
        db.session.add(dash)

    db.session.commit()
    return jsonify({'id': dash.id, 'name': dash.name, 'is_default': dash.is_default})


@bp.route('/api/dashboard/list')
@login_required
def list_dashboard_configs():
    """获取当前用户的 Dashboard 配置列表"""
    configs = current_user.dashboards.order_by(UserDashboard.updated_at.desc()).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'is_default': c.is_default,
        'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M') if c.updated_at else '',
    } for c in configs])


@bp.route('/api/dashboard/<int:dash_id>')
@login_required
def get_dashboard_config(dash_id):
    """获取指定 Dashboard 配置详情"""
    dash = UserDashboard.query.filter_by(id=dash_id, user_id=current_user.id).first_or_404()
    return jsonify({
        'id': dash.id,
        'name': dash.name,
        'is_default': dash.is_default,
        'config': json.loads(dash.config),
    })


@bp.route('/api/dashboard/<int:dash_id>', methods=['DELETE'])
@login_required
def delete_dashboard_config(dash_id):
    """删除 Dashboard 配置"""
    dash = UserDashboard.query.filter_by(id=dash_id, user_id=current_user.id).first_or_404()
    db.session.delete(dash)
    db.session.commit()
    return jsonify({'ok': True})


# =========================================================================
# Dashboard Group
# =========================================================================

@bp.route('/api/groups', methods=['GET'])
@login_required
def list_dashboard_groups():
    """列出当前用户可见的 group"""
    role = current_user.role
    user_id = current_user.id
    all_groups = DashboardGroup.query.all()
    visible = [g for g in all_groups if g.is_visible_to(current_user, role)]
    return jsonify([g.to_dict(include_config=False) for g in visible])


@bp.route('/api/groups', methods=['POST'])
@login_required
def create_dashboard_group():
    """创建 group (任何角色均可创建, 自己是 owner)"""
    if current_user.role == 'release':
        return jsonify({'error': 'release 角色不能创建 group'}), 403
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name 必填'}), 400
    if len(name) > 120:
        return jsonify({'error': 'name 过长 (≤120)'}), 400
    project_id = data.get('project_id')
    if project_id is not None:
        if Project.query.get(project_id) is None:
            return jsonify({'error': 'project_id 不存在'}), 400
    if DashboardGroup.query.filter_by(project_id=project_id, name=name).first():
        return jsonify({'error': '该项目下已存在同名 group'}), 400
    config = data.get('config') or {}
    if not isinstance(config, dict):
        return jsonify({'error': 'config 必须是对象'}), 400
    g = DashboardGroup(
        name=name,
        description=(data.get('description') or '').strip() or None,
        project_id=project_id,
        owner_id=current_user.id,
        member_ids=json.dumps(data.get('member_ids') or []),
        config=json.dumps(config),
        shared_default=bool(data.get('shared_default', False)),
        is_public=bool(data.get('is_public', False)),
    )
    db.session.add(g)
    db.session.commit()
    try:
        repo.sync_dashboard_group(g, 'upsert')
    except Exception as e:
        current_app.logger.warning(f'mongo sync group failed: {e}')
    return jsonify(g.to_dict()), 201


@bp.route('/api/groups/<int:gid>', methods=['GET'])
@login_required
def get_dashboard_group(gid):
    """获取 group 详情 (含 config)"""
    g = DashboardGroup.query.get_or_404(gid)
    if not g.is_visible_to(current_user, current_user.role):
        return jsonify({'error': 'forbidden'}), 403
    return jsonify(g.to_dict(include_config=True))


@bp.route('/api/groups/<int:gid>', methods=['PUT'])
@login_required
def update_dashboard_group(gid):
    """更新 group (仅 owner / admin)"""
    g = DashboardGroup.query.get_or_404(gid)
    if not g.can_edit(current_user, current_user.role):
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    if 'description' in data:
        g.description = (data.get('description') or '').strip() or None
    if 'config' in data:
        cfg = data['config']
        if not isinstance(cfg, dict):
            return jsonify({'error': 'config 必须是对象'}), 400
        g.config = json.dumps(cfg)
    if 'member_ids' in data:
        mids = data['member_ids'] or []
        if not isinstance(mids, list):
            return jsonify({'error': 'member_ids 必须是数组'}), 400
        for uid in mids:
            if not isinstance(uid, int) or User.query.get(uid) is None:
                return jsonify({'error': f'user_id {uid} 不存在'}), 400
        g.member_ids = json.dumps(mids)
    if 'shared_default' in data:
        g.shared_default = bool(data['shared_default'])
    if 'is_public' in data:
        g.is_public = bool(data['is_public'])
    if 'name' in data and data['name'] and data['name'].strip() != g.name:
        new_name = data['name'].strip()
        if DashboardGroup.query.filter(
            DashboardGroup.project_id == g.project_id,
            DashboardGroup.name == new_name,
            DashboardGroup.id != g.id,
        ).first():
            return jsonify({'error': '该项目下已存在同名 group'}), 400
        g.name = new_name
    g.updated_at = datetime.utcnow()
    db.session.commit()
    try:
        repo.sync_dashboard_group(g, 'upsert')
    except Exception as e:
        current_app.logger.warning(f'mongo sync group failed: {e}')
    return jsonify(g.to_dict())


@bp.route('/api/groups/<int:gid>', methods=['DELETE'])
@login_required
def delete_dashboard_group(gid):
    """删除 group (仅 owner / admin)"""
    g = DashboardGroup.query.get_or_404(gid)
    if not g.can_edit(current_user, current_user.role):
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(g)
    db.session.commit()
    try:
        repo.sync_dashboard_group(g, 'delete')
    except Exception as e:
        current_app.logger.warning(f'mongo delete group failed: {e}')
    return jsonify({'ok': True})


@bp.route('/api/groups/my-default', methods=['GET'])
@login_required
def my_default_group():
    """获取当前用户应自动应用的 group config"""
    if current_user.role == 'release':
        return jsonify({'group': None, 'config': None})
    user_id = current_user.id
    candidates = [g for g in DashboardGroup.query.all()
                  if g.shared_default and g.is_member(user_id)]
    if not candidates:
        return jsonify({'group': None, 'config': None})
    candidates.sort(key=lambda g: (g.project_id is None, -(g.updated_at.timestamp() if g.updated_at else 0)))
    chosen = candidates[0]
    return jsonify({
        'group': chosen.to_dict(include_config=False),
        'config': json.loads(chosen.config) if chosen.config else None,
    })


# =========================================================================
# 主题
# =========================================================================

def _validate_theme(data):
    theme = data.get('theme', '').strip() if isinstance(data, dict) else ''
    custom = data.get('custom') if isinstance(data, dict) else None
    if not theme:
        return None, 'theme 必填'
    return {'theme': theme, 'custom': custom}, None


@bp.route('/api/user/theme')
@login_required
def get_user_theme():
    """获取用户主题"""
    return jsonify({
        'theme': current_user.theme or 'default',
        'custom': json.loads(current_user.custom_theme) if current_user.custom_theme else None,
    })


@bp.route('/api/user/theme', methods=['POST'])
@login_required
def save_user_theme():
    """保存用户主题"""
    data = request.get_json() or {}
    payload, err = _validate_theme(data)
    if err:
        return jsonify({'error': err}), 400
    current_user.theme = payload['theme']
    if payload.get('custom'):
        current_user.custom_theme = json.dumps(payload['custom'], ensure_ascii=False)
    else:
        current_user.custom_theme = None
    db.session.commit()
    return jsonify({'ok': True})
