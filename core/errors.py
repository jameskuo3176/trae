"""错误处理器

集中处理 400 / 403 / 404 / 429 错误, 支持 API JSON 响应与 HTML 页面两种方式。
"""
from flask import jsonify, render_template, request


def register_error_handlers(app):
    """注册全局错误处理器"""

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('error.html', code=403, message='无权限访问'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html', code=404, message='页面不存在'), 404

    @app.errorhandler(429)
    def rate_limited(e):
        """Rate Limit 超限"""
        retry_after = request.headers.get('Retry-After', '60')
        msg = f'请求过于频繁, 请 {retry_after} 秒后重试'
        if request.path.startswith('/api/') or request.is_json:
            resp = jsonify({'error': msg, 'retry_after': int(retry_after)})
            resp.headers['Retry-After'] = str(retry_after)
            return resp, 429
        return render_template('error.html', code=429, message=msg), 429

    @app.errorhandler(400)
    def bad_request(e):
        """CSRF 校验失败等 400 错误"""
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'error': str(e.description) if hasattr(e, 'description') else '请求错误'}), 400
        return render_template('error.html', code=400, message='请求错误'), 400
