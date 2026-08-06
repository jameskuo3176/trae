"""Django 模板上下文处理器

为所有模板提供全局变量, 兼容 Flask 版本的 config/g 变量访问。
"""
from django.conf import settings


def settings_context(request):
    """将 settings 中的关键配置暴露给模板

    使用方式: 在 settings.TEMPLATES[0]['OPTIONS']['context_processors'] 中注册
        'django_app.core.context_processors.settings_context'
    """
    return {
        'ENABLE_DB_ADMIN': getattr(settings, 'ENABLE_DB_ADMIN', False),
        'DB_ADMIN_SERVER': getattr(settings, 'DB_ADMIN_SERVER', 'localhost'),
        'DB_ADMIN_NAME': getattr(settings, 'DB_ADMIN_NAME', 'qor_recorder'),
        'DEBUG': settings.DEBUG,
    }