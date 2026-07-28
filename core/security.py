"""安全检查与 CSRF 保护集成

封装 SECRET_KEY 启动检查、CSRF 初始化、请求前安全钩子。
"""
from flask import jsonify, request
from flask_login import current_user

# 在函数内部引用 security 模块, 允许测试时通过 monkey patch 替换
import security as _security
from security import (
    init_csrf, get_client_ip, is_default_admin_password_weak,
)


def _csrf_protect():
    """代理到 security.csrf_protect (允许测试时替换)"""
    return _security.csrf_protect()


def check_secret_key(app):
    """检查 SECRET_KEY 是否仍是默认值 (生产环境拒绝启动)"""
    sk = app.config.get('SECRET_KEY', '')
    default = app.config.get('_DEFAULT_SECRET_KEY', '')
    enforce = app.config.get('ENFORCE_SECRET_KEY', True)
    is_default = (sk == default) or not sk
    if not is_default:
        return
    # DEBUG 模式下允许默认密钥 (本地开发)
    if app.config.get('DEBUG'):
        print('[SECURITY] 警告: SECRET_KEY 仍是默认值, 仅允许 DEBUG 模式使用!')
        return
    if not enforce:
        print('[SECURITY] 警告: SECRET_KEY 仍是默认值 (ENFORCE_SECRET_KEY=0 已关闭强制检查)')
        return
    raise RuntimeError(
        '\n' + '=' * 60 + '\n'
        '[SECURITY] 致命错误: SECRET_KEY 仍是出厂默认值, 拒绝启动!\n'
        '  请设置环境变量 SECRET_KEY 为随机字符串, 例如:\n'
        '    # Linux/Mac\n'
        '    export SECRET_KEY="$(python -c "import secrets; print(secrets.token_hex(32))")"\n'
        '    # Windows PowerShell\n'
        '    $env:SECRET_KEY = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | % {[char]$_})\n'
        '  或在 .env 文件中写入:\n'
        '    SECRET_KEY=<your-random-key>\n'
        '  本地调试可临时关闭:\n'
        '    export ENFORCE_SECRET_KEY=0\n'
        '=' * 60
    )


def init_security(app):
    """初始化安全模块: SECRET_KEY 检查 + CSRF 保护"""
    check_secret_key(app)
    init_csrf(app)


def register_security_before_request(app):
    """注册全局请求前钩子: CSRF 校验 + release 角色只读拦截

    Rate Limiting 通过 @rate_limit 装饰器按端点配置。
    """
    @app.before_request
    def _security_before_request():
        # release 角色: 禁止所有写操作 (POST/PUT/DELETE/PATCH)
        if (current_user.is_authenticated
                and current_user.is_release
                and request.method in ('POST', 'PUT', 'DELETE', 'PATCH')):
            allowed_write_endpoints = {
                'user_change_own_password',
                'save_dashboard_config',
                'delete_dashboard_config',
                'save_user_theme',
            }
            if request.endpoint not in allowed_write_endpoints:
                app.logger.warning(
                    '[AUTH] release 角色尝试写操作被拒: endpoint=%s path=%s ip=%s',
                    request.endpoint, request.path, get_client_ip(),
                )
                return jsonify({'error': 'release 账号为只读权限, 不允许此操作'}), 403
        return _csrf_protect()
