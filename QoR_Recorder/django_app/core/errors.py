"""错误处理器

集中处理 400 / 403 / 404 / 500 错误, 支持 API JSON 响应与 HTML 页面两种方式。

在 urls.py 中注册:
    handler400 = 'django_app.core.errors.handler400'
    handler403 = 'django_app.core.errors.handler403'
    handler404 = 'django_app.core.errors.handler404'
    handler500 = 'django_app.core.errors.handler500'
"""
import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)


def _is_api_request(request):
    """判断是否为 API 请求"""
    if request is None:
        return False
    path = request.path or ''
    content_type = request.META.get('CONTENT_TYPE', '')
    return (
        path.startswith('/api/')
        or 'application/json' in content_type
        or request.META.get('HTTP_ACCEPT', '').startswith('application/json')
    )


def handler400(request, exception=None):
    """400 Bad Request 错误处理器

    CSRF 校验失败等 400 错误。
    """
    if _is_api_request(request):
        message = str(exception) if exception else '请求错误'
        return JsonResponse({'error': message}, status=400)

    context = {
        'code': 400,
        'message': '请求错误',
        'detail': str(exception) if exception else '',
    }
    return render(request, 'error.html', context, status=400)


def handler403(request, exception=None):
    """403 Forbidden 错误处理器"""
    if _is_api_request(request):
        message = str(exception) if exception else '无权限访问'
        return JsonResponse({'error': message}, status=403)

    context = {
        'code': 403,
        'message': '无权限访问',
        'detail': str(exception) if exception else '',
    }
    return render(request, 'error.html', context, status=403)


def handler404(request, exception=None):
    """404 Not Found 错误处理器"""
    if _is_api_request(request):
        return JsonResponse({'error': '页面不存在'}, status=404)

    context = {
        'code': 404,
        'message': '页面不存在',
        'detail': str(exception) if exception else '',
    }
    return render(request, 'error.html', context, status=404)


def handler500(request):
    """500 Internal Server Error 错误处理器"""
    if _is_api_request(request):
        return JsonResponse({'error': '服务器内部错误'}, status=500)

    context = {
        'code': 500,
        'message': '服务器内部错误',
        'detail': '',
    }
    return render(request, 'error.html', context, status=500)


def handler429(request, exception=None):
    """429 Too Many Requests 错误处理器

    Rate Limit 超限时由中间件直接返回, 此 handler 作为兜底。
    """
    retry_after = 60
    if _is_api_request(request):
        resp = JsonResponse(
            {
                'error': f'请求过于频繁, 请 {retry_after} 秒后重试',
                'retry_after': retry_after,
            },
            status=429,
        )
        resp['Retry-After'] = str(retry_after)
        return resp

    context = {
        'code': 429,
        'message': f'请求过于频繁, 请 {retry_after} 秒后重试',
        'detail': '',
    }
    return render(request, 'error.html', context, status=429)