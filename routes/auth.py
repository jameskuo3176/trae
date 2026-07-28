"""认证路由

负责:
  - 登录/登出 (Web UI)
  - API v1 认证 (login/me)
"""
from datetime import datetime, timedelta

from flask import (
    Blueprint, current_app, flash, g, jsonify, redirect, render_template,
    request, session, url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from api_auth import api_auth_required
from models import ApiKey, User
from security import generate_csrf_token, get_client_ip, rate_limit

bp = Blueprint('auth', __name__)


# =========================================================================
# 登录/登出 (通过 factory.add_url_rule 注册, 保持 url_for('login') 兼容)
# =========================================================================

@rate_limit(5, 60)
def login():
    """用户登录"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # 防 session fixation
            session.clear()
            login_user(user)
            generate_csrf_token()
            next_url = request.args.get('next')
            return redirect(next_url or url_for('dashboard'))
        current_app.logger.warning('[AUTH] 登录失败: username=%s ip=%s', username, get_client_ip())
        flash('用户名或密码错误', 'error')
    return render_template('login.html')


@login_required
def logout():
    """用户登出"""
    logout_user()
    return redirect(url_for('login'))


# =========================================================================
# API v1 认证 (位于 /api/v1/auth/)
# =========================================================================

@bp.route('/api/v1/auth/login', methods=['POST'])
def api_v1_login():
    """API 登录 - 返回 API Key (供前端存储后用于后续请求)

    请求体: {"username": "...", "password": "..."}
    返回: {"api_key": "qor_xxx", "user": {...}}
    """
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'error': '用户名或密码错误'}), 401

    plaintext = ApiKey.generate_key()
    api_key = ApiKey(
        user_id=user.id,
        key_hash=ApiKey.hash_key(plaintext),
        prefix=plaintext[:12],
        name=f'login-token-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}',
        scopes='read,upload',
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.session.add(api_key)
    db.session.commit()

    return jsonify({
        'api_key': plaintext,
        'api_key_id': api_key.id,
        'user': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name,
        },
    })


@bp.route('/api/v1/auth/me')
@api_auth_required()
def api_v1_me():
    """获取当前认证用户信息"""
    user = g.auth_user
    return jsonify({
        'id': user.id,
        'username': user.username,
        'role': user.role,
        'display_name': user.display_name,
        'auth_method': g.auth_method,
    })
