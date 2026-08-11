"""Small, stable API v2 surface backed by the repository boundary."""
from __future__ import annotations

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from django_app.core.decorators import api_auth_required
from django_app.core.models import GlobalModule, Project, ProjectModule
from django_app.repositories import get_record_repository, mongo_readiness
from django_app.services.path_derivation import PathDerivationError, derive_version


def _error(code, message, status=400, details=None):
    return JsonResponse({
        'ok': False,
        'error': {'code': code, 'message': message, 'details': details or {}},
    }, status=status)


@require_GET
def live(request):
    """Process liveness probe; intentionally avoids dependency checks."""
    return JsonResponse({'ok': True, 'status': 'alive'})


def _project(project_id):
    try:
        return Project.objects.get(pk=project_id)
    except Project.DoesNotExist:
        return None


def _can_view(user, project_id):
    return user.is_admin or user.project_memberships.filter(project_id=project_id).exists()


@require_GET
def health(request):
    sql = {'ready': False}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        sql = {'ready': True}
    except Exception as exc:
        sql['error'] = str(exc)
    mongo = mongo_readiness()
    ready = sql['ready'] and mongo['ready']
    return JsonResponse({
        'ok': ready,
        'status': 'ready' if ready else 'degraded',
        'checks': {'sql': sql, 'mongo': mongo},
    }, status=200 if ready else 503)


@require_GET
@api_auth_required('read')
def modules(request):
    project_id = request.GET.get('project_id')
    if not project_id or not project_id.isdigit():
        return _error('invalid_project_id', 'project_id is required and must be an integer')
    project_id = int(project_id)
    if not _project(project_id):
        return _error('not_found', 'project not found', 404)
    if not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    links = ProjectModule.objects.select_related('module').filter(project_id=project_id)
    data = [{
        'id': link.module_id,
        'name': link.module.name,
        'normalized_name': link.module.normalized_name,
        'project_id': project_id,
    } for link in links]
    return JsonResponse({'ok': True, 'data': data})


@require_GET
@api_auth_required('read')
def records(request):
    project_id = request.GET.get('project_id')
    if not project_id or not project_id.isdigit():
        return _error('invalid_project_id', 'project_id is required and must be an integer')
    project_id = int(project_id)
    if not _project(project_id):
        return _error('not_found', 'project not found', 404)
    if not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    try:
        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(200, max(1, int(request.GET.get('page_size', 50))))
        module_id = request.GET.get('module_id')
        module_id = int(module_id) if module_id else None
    except (TypeError, ValueError):
        return _error('invalid_pagination', 'page, page_size and module_id must be integers')
    repository = get_record_repository()
    try:
        items, total = repository.list_records(
            project_id, module_id=module_id, version=request.GET.get('version') or None,
            offset=(page - 1) * page_size, limit=page_size,
        )
    except Exception as exc:
        return _error('repository_error', 'record query failed', 503, {'reason': str(exc)})
    return JsonResponse({
        'ok': True,
        'data': items,
        'pagination': {
            'page': page, 'page_size': page_size, 'total': total,
            'pages': (total + page_size - 1) // page_size,
        },
    })


def _record_child(request, project_id, record_id, method):
    if not _project(project_id):
        return _error('not_found', 'project not found', 404)
    if not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    try:
        value = getattr(get_record_repository(), method)(project_id, record_id)
    except Exception as exc:
        return _error('repository_error', 'record query failed', 503, {'reason': str(exc)})
    if value is None:
        return _error('not_found', 'record not found', 404)
    return JsonResponse({'ok': True, 'data': value})


@require_GET
@api_auth_required('read')
def record_detail(request, project_id, record_id):
    return _record_child(request, project_id, record_id, 'get_record')


@require_GET
@api_auth_required('read')
def raw_report(request, project_id, record_id):
    return _record_child(request, project_id, record_id, 'get_raw_report')


@require_GET
@api_auth_required('read')
def violations(request, project_id, record_id):
    return _record_child(request, project_id, record_id, 'list_violations')


@require_GET
@api_auth_required('read')
def notes(request, project_id, record_id):
    return _record_child(request, project_id, record_id, 'list_notes')


@require_GET
@api_auth_required('read')
def versions(request):
    project_id = request.GET.get('project_id')
    if not project_id or not project_id.isdigit():
        return _error('invalid_project_id', 'project_id is required and must be an integer')
    project_id = int(project_id)
    if not _project(project_id):
        return _error('not_found', 'project not found', 404)
    if not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    try:
        rows, _ = get_record_repository().list_records(project_id, offset=0, limit=10000)
    except Exception as exc:
        return _error('repository_error', 'version query failed', 503, {'reason': str(exc)})
    values, invalid = set(), []
    for row in rows:
        try:
            values.add(derive_version(row.get('full_dir')))
        except PathDerivationError as exc:
            invalid.append({'record_id': str(row.get('id')), 'error': exc.as_dict()})
    return JsonResponse({
        'ok': True,
        'data': sorted(values),
        'meta': {'invalid_path_count': len(invalid), 'invalid_paths': invalid[:20]},
    })
