"""Small, stable API v2 surface backed by the repository boundary."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import quote

from django.db import connection, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_http_methods

from django_app.core.decorators import api_auth_required
from django_app.core.models import (
    GlobalModule, LegacyModuleMapping, Module, Project, ProjectMember, ProjectModule,
    QorRecord, RecordAnnotation, RecordAnnotationImage, ReviewGroup, User,
)
from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.repositories import get_record_repository, mongo_readiness
from django_app.services.qor_import import associate_global_module
from django_app.services.path_derivation import PathDerivationError, derive_version
from django_app.services.record_risk import (
    clear_manual_rating,
    enrich_record_risks,
    set_manual_rating,
)


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
    project = _project(project_id)
    if project is None or project.status == 'hidden':
        return False
    return (
        user.is_admin
        or user.is_owner
        or user.is_viewer
        or user.project_memberships.filter(project_id=project_id).exists()
        or ProjectModule.objects.filter(project_id=project_id, owner_id=user.id).exists()
        or ReviewGroup.objects.filter(project_id=project_id, owner_id=user.id).exists()
    )


def _resolve_project_ids(request):
    """解析 project_ids / project_id 查询参数为可见项目 ID 列表。

    支持逗号分隔的多项目。未指定时返回全部可见项目。
    返回 None 表示参数格式非法。
    """
    raw = request.GET.get('project_ids') or request.GET.get('project_id') or ''
    if raw:
        parts = [part.strip() for part in raw.split(',') if part.strip()]
        if not parts or not all(part.isdigit() for part in parts):
            return None
        project_ids = [int(part) for part in parts]
        for pid in project_ids:
            if not _project(pid):
                return None
            if not _can_view(request.user, pid):
                return None
        return project_ids
    return [
        project.id for project in Project.objects.exclude(status='hidden').order_by('id')
        if _can_view(request.user, project.id)
    ]


def _resolve_record_module_identities(items):
    """Hydrate canonical IDs from explicit mappings, never from module names."""
    mapping_keys = set()
    candidates = []
    for item in items:
        try:
            project_id = int(item.get('project_id'))
        except (TypeError, ValueError):
            candidates.append((item, None, None, None))
            continue
        legacy_id = item.get('legacy_module_id')
        try:
            legacy_id = int(legacy_id) if legacy_id is not None else None
        except (TypeError, ValueError):
            legacy_id = None
        if legacy_id is not None:
            mapping_keys.add((project_id, legacy_id))
        candidates.append((item, project_id, legacy_id, item.get('module_id')))

    mappings = {
        (row.project_id, row.legacy_module_id): row.module_id
        for row in LegacyModuleMapping.objects.filter(
            project_id__in={key[0] for key in mapping_keys},
            legacy_module_id__in={key[1] for key in mapping_keys},
        )
    } if mapping_keys else {}

    resolved_candidates = []
    link_keys = set()
    for item, project_id, legacy_id, document_module_id in candidates:
        mapped_id = mappings.get((project_id, legacy_id))
        raw_module_id = mapped_id if mapped_id is not None else document_module_id
        try:
            module_id = int(raw_module_id) if raw_module_id is not None else None
        except (TypeError, ValueError):
            module_id = None
        resolved_candidates.append((item, project_id, legacy_id, module_id))
        if project_id is not None and module_id is not None:
            link_keys.add((project_id, module_id))

    valid_links = set(ProjectModule.objects.filter(
        project_id__in={key[0] for key in link_keys},
        module_id__in={key[1] for key in link_keys},
    ).values_list('project_id', 'module_id')) if link_keys else set()

    unresolved = []
    for item, project_id, legacy_id, module_id in resolved_candidates:
        if (project_id, module_id) in valid_links:
            item['module_id'] = module_id
            continue
        item['module_id'] = None
        detail = {
            'project_id': project_id,
            'record_id': str(item.get('id')),
            'legacy_module_id': legacy_id,
            'module_name': item.get('module_name') or '',
        }
        item['module_mapping_error'] = detail
        unresolved.append(detail)
    return unresolved


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
    project_ids = _resolve_project_ids(request)
    if project_ids is None:
        return _error('invalid_project_id', 'project_ids must be integers')

    diagnostics = []
    for pid in project_ids:
        project = _project(pid)
        try:
            get_project_engine(pid)
            alias = _get_project_db_alias(pid)
            mapped_ids = set(
                ProjectModule.objects.filter(project_id=pid).values_list('module_id', flat=True)
            )
            for legacy in Module.objects.using(alias).filter(project_id=pid):
                canonical = associate_global_module(project, legacy)
                mapped_ids.add(canonical.id)
        except Exception as exc:
            diagnostics.append({'project_id': pid, 'message': str(exc)})

    links = ProjectModule.objects.select_related('module').filter(project_id__in=project_ids)
    if len(project_ids) == 1:
        data = [{
            'id': link.module_id,
            'name': link.module.name,
            'normalized_name': link.module.normalized_name,
            'project_id': link.project_id,
            'project_ids': [link.project_id],
        } for link in links.order_by('module__normalized_name')]
    else:
        grouped = {}
        for link in links.order_by('module__normalized_name', 'project_id'):
            item = grouped.setdefault(link.module_id, {
                'id': link.module_id,
                'name': link.module.name,
                'normalized_name': link.module.normalized_name,
                'project_id': None,
                'project_ids': [],
            })
            item['project_ids'].append(link.project_id)
        data = list(grouped.values())
    return JsonResponse({
        'ok': True,
        'data': data,
        'meta': {'diagnostics': diagnostics, 'project_count': len(project_ids)},
    })


@require_GET
@api_auth_required('read')
def records(request):
    project_ids = _resolve_project_ids(request)
    if project_ids is None:
        return _error('invalid_project_id', 'project_ids must be integers')
    try:
        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(200, max(1, int(request.GET.get('page_size', 50))))
        module_id = request.GET.get('module_id')
        module_id = int(module_id) if module_id else None
    except (TypeError, ValueError):
        return _error('invalid_pagination', 'page, page_size and module_id must be integers')
    repository = get_record_repository()
    try:
        query = {
            'module_id': module_id,
            'version': request.GET.get('version') or None,
        }
        if len(project_ids) == 1:
            items, total = repository.list_records(
                project_ids[0],
                offset=(page - 1) * page_size,
                limit=page_size,
                **query,
            )
            for item in items:
                item.setdefault('project_id', project_ids[0])
        else:
            items = []
            for pid in project_ids:
                project_items, _ = repository.list_records(
                    pid, offset=0, limit=10000, **query
                )
                for item in project_items:
                    item.setdefault('project_id', pid)
                items.extend(project_items)
            items.sort(
                key=lambda item: (
                    item.get('released_at') or item.get('recorded_at') or '',
                    str(item.get('id') or ''),
                ),
                reverse=True,
            )
            total = len(items)
            start = (page - 1) * page_size
            items = items[start:start + page_size]
    except Exception as exc:
        return _error('repository_error', 'record query failed', 503, {'reason': str(exc)})
    owner_ids = {
        item.get('owner_id') for item in items if item.get('owner_id') is not None
    }
    owners = {
        user.id: user for user in User.objects.filter(id__in=owner_ids)
    }
    projects = {pid: _project(pid) for pid in project_ids}
    unmapped = _resolve_record_module_identities(items)
    repository = get_record_repository()

    def load_history(project_id, history_module_id):
        rows, _ = repository.list_records(
            project_id,
            module_id=history_module_id,
            offset=0,
            limit=10000,
        )
        for row in rows:
            row.setdefault('project_id', project_id)
        _resolve_record_module_identities(rows)
        return rows

    enrich_record_risks(items, request.user, history_loader=load_history)
    for item in items:
        item_project_id = int(item.get('project_id') or project_ids[0])
        owner = owners.get(item.get('owner_id'))
        item['project_name'] = projects[item_project_id].name
        item['uploader_id'] = item.get('owner_id')
        item['uploader_username'] = owner.username if owner else None
        item['uploader_display_name'] = owner.display_name if owner else None
        item['release_sort_at'] = item.get('released_at') or item.get('recorded_at')
    return JsonResponse({
        'ok': True,
        'data': items,
        'pagination': {
            'page': page, 'page_size': page_size, 'total': total,
            'pages': (total + page_size - 1) // page_size,
        },
        'meta': {'unmapped_modules': unmapped},
    })


def _record_child(request, project_id, record_id, method):
    if not _project(project_id):
        return _error('not_found', 'project not found', 404)
    if not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    repository = get_record_repository()
    try:
        record = repository.get_record(project_id, record_id)
        if record is None:
            return _error('not_found', 'record not found', 404)
        value = (
            record
            if method == 'get_record'
            else getattr(repository, method)(project_id, record_id)
        )
    except Exception as exc:
        return _error('repository_error', 'record query failed', 503, {'reason': str(exc)})
    if value is None:
        return _error('not_found', 'record not found', 404)
    if method == 'get_record':
        value.setdefault('project_id', project_id)
        _resolve_record_module_identities([value])
        enrich_record_risks([value], request.user)
    return JsonResponse({'ok': True, 'data': value})


@require_GET
@api_auth_required('read')
def record_detail(request, project_id, record_id):
    return _record_child(request, project_id, record_id, 'get_record')


@require_http_methods(['PUT', 'DELETE'])
@api_auth_required('read')
def record_risk(request, project_id, record_id):
    project = _project(project_id)
    if project is None:
        return _error('not_found', 'project not found', 404)
    if not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    if (
        getattr(request, 'auth_method', None) == 'api_key'
        and not request.api_key.has_scope('upload')
    ):
        return _error('forbidden', 'API Key requires upload scope', 403)
    repository = get_record_repository()
    try:
        record = repository.get_record(project_id, record_id)
    except Exception as exc:
        return _error('repository_error', 'record query failed', 503, {'reason': str(exc)})
    if record is None:
        return _error('not_found', 'record not found', 404)
    record.setdefault('project_id', project_id)
    _resolve_record_module_identities([record])
    module_id = record.get('module_id')
    if module_id is None:
        return _error('unmapped_module', 'record has no GlobalModule mapping', 409)
    try:
        if request.method == 'DELETE':
            clear_manual_rating(
                request.user, project, int(module_id), str(record_id),
            )
        else:
            try:
                body = json.loads(request.body or b'{}')
            except (TypeError, json.JSONDecodeError):
                return _error('invalid_json', 'valid JSON is required')
            set_manual_rating(
                request.user,
                project,
                int(module_id),
                str(record_id),
                body.get('rating'),
            )
        enrich_record_risks([record], request.user)
    except PermissionError as exc:
        return _error('forbidden', str(exc), 403)
    except ValueError as exc:
        return _error('invalid_rating', str(exc))
    return JsonResponse({'ok': True, 'data': record['risk']})


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


MAX_ANNOTATION_IMAGE_SIZE = 5 * 1024 * 1024
MAX_ANNOTATION_IMAGES = 6


def _valid_gif(content):
    """Strictly walk a GIF data stream and require at least one complete frame."""
    if len(content) < 14 or content[:6] not in (b'GIF87a', b'GIF89a'):
        return False
    width = int.from_bytes(content[6:8], 'little')
    height = int.from_bytes(content[8:10], 'little')
    if not width or not height:
        return False
    packed = content[10]
    offset = 13
    if packed & 0x80:
        offset += 3 * (2 ** ((packed & 0x07) + 1))
    frames = 0

    def consume_sub_blocks(position):
        saw_data = False
        while position < len(content):
            size = content[position]
            position += 1
            if size == 0:
                return position, saw_data
            if position + size > len(content):
                return None, False
            saw_data = True
            position += size
        return None, False

    while offset < len(content):
        marker = content[offset]
        offset += 1
        if marker == 0x3B:
            return frames > 0 and offset == len(content)
        if marker == 0x21:
            if offset >= len(content):
                return False
            offset += 1  # extension label
            offset, _ = consume_sub_blocks(offset)
            if offset is None:
                return False
            continue
        if marker != 0x2C or offset + 9 > len(content):
            return False
        descriptor = content[offset:offset + 9]
        image_width = int.from_bytes(descriptor[4:6], 'little')
        image_height = int.from_bytes(descriptor[6:8], 'little')
        if not image_width or not image_height:
            return False
        offset += 9
        if descriptor[8] & 0x80:
            offset += 3 * (2 ** ((descriptor[8] & 0x07) + 1))
        if offset >= len(content) or not 2 <= content[offset] <= 8:
            return False
        offset += 1
        offset, saw_image_data = consume_sub_blocks(offset)
        if offset is None or not saw_image_data:
            return False
        frames += 1
    return False


def _annotation_record(request, project_id, record_id):
    project = _project(project_id)
    if not project or not _can_view(request.user, project_id):
        return project, None, None
    get_project_engine(project_id)
    alias = _get_project_db_alias(project_id)
    record = (
        QorRecord.objects.using(alias)
        .select_related('module')
        .filter(pk=record_id)
        .first()
    )
    return project, alias, record


def _can_edit_annotation(user, project, record):
    if not project.is_writable or user.is_viewer:
        return False
    if user.is_admin or user.is_owner or record.module.can_be_managed_by(user):
        return True
    return ProjectMember.objects.filter(
        project_id=project.id,
        user=user,
        role__in=('owner', 'editor'),
    ).exists()


def _annotation_payload(annotation, project_id, record, users=None):
    if annotation is None:
        return None
    users = users or {
        user.id: user
        for user in User.objects.filter(id__in=(annotation.author_id, annotation.editor_id))
    }
    author = users.get(annotation.author_id)
    editor = users.get(annotation.editor_id)
    return {
        'id': annotation.id,
        'project_id': project_id,
        'record_id': str(annotation.qor_record_id),
        'text': annotation.text,
        'author': {
            'id': annotation.author_id,
            'username': author.username if author else None,
            'display_name': author.display_name if author else None,
        },
        'editor': {
            'id': annotation.editor_id,
            'username': editor.username if editor else None,
            'display_name': editor.display_name if editor else None,
        },
        'created_at': annotation.created_at.isoformat(),
        'updated_at': annotation.updated_at.isoformat(),
        'record': {
            'module_name': record.module.name,
            'version': record.version,
            'tag': record._compute_tag(),
            'full_dir': record.full_dir,
        },
        'images': [
            {
                'id': image.id,
                'filename': image.filename,
                'content_type': image.content_type,
                'byte_size': image.byte_size,
                'width': None,
                'height': None,
                'url': (
                    f'/api/v2/projects/{project_id}/records/{record.id}'
                    f'/annotation/images/{image.id}'
                ),
            }
            for image in annotation.images.all()
        ],
    }


def _validated_image(upload):
    if upload.size > MAX_ANNOTATION_IMAGE_SIZE:
        raise ValueError('Each image must be 5 MiB or smaller.')
    content = upload.read()
    if len(content) != upload.size or not content:
        raise ValueError('Image upload is empty or incomplete.')
    lowered = content[:2048].lower()
    if any(marker in lowered for marker in (b'<svg', b'<script', b'<html', b'<?php')):
        raise ValueError('Active or vector content is not allowed.')
    if content.startswith((b'MZ', b'PK\x03\x04', b'\x7fELF')):
        raise ValueError('Executable or archive content is not allowed.')

    content_type = None
    if content.startswith(b'\x89PNG\r\n\x1a\n') and b'IEND' in content[-64:]:
        content_type = 'image/png'
    elif content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9'):
        content_type = 'image/jpeg'
    elif _valid_gif(content):
        content_type = 'image/gif'
    elif (
        len(content) >= 16
        and content.startswith(b'RIFF')
        and content[8:12] == b'WEBP'
        and int.from_bytes(content[4:8], 'little') + 8 == len(content)
    ):
        content_type = 'image/webp'
    if content_type is None:
        raise ValueError('Only valid PNG, JPEG, WebP, or GIF images are allowed.')

    filename = get_valid_filename(upload.name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1])
    filename = (filename or f'image.{content_type.split("/")[1]}')[:180]
    return {
        'filename': filename,
        'content_type': content_type,
        'byte_size': len(content),
        'checksum': hashlib.sha256(content).hexdigest(),
        'content': content,
    }


@require_http_methods(['GET', 'POST'])
@api_auth_required('read')
def record_annotation(request, project_id, record_id):
    project, alias, record = _annotation_record(request, project_id, record_id)
    if not project or not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    if record is None:
        return _error('not_found', 'record not found', 404)
    can_edit = _can_edit_annotation(request.user, project, record)
    annotation = (
        RecordAnnotation.objects.using(alias)
        .prefetch_related('images')
        .filter(qor_record_id=record.id)
        .first()
    )
    if request.method == 'GET':
        return JsonResponse({
            'ok': True,
            'data': {
                'annotation': _annotation_payload(annotation, project_id, record),
                'can_edit': can_edit,
            },
        })
    if (
        getattr(request, 'auth_method', None) == 'api_key'
        and not request.api_key.has_scope('upload')
    ):
        return _error('forbidden', 'API Key requires upload scope', 403)
    if not can_edit:
        return _error('forbidden', 'annotation edit denied', 403)

    text = request.POST.get('text', '')
    if len(text) > 100000:
        return _error('invalid_text', 'annotation text is too long')
    try:
        keep_ids = json.loads(request.POST.get('keep_image_ids', '[]'))
        keep_ids = {int(value) for value in keep_ids}
    except (TypeError, ValueError, json.JSONDecodeError):
        return _error('invalid_images', 'keep_image_ids must be a JSON integer array')
    existing_ids = set(annotation.images.values_list('id', flat=True)) if annotation else set()
    if not keep_ids.issubset(existing_ids):
        return _error('invalid_images', 'one or more retained images do not belong to this record')
    uploads = request.FILES.getlist('images')
    if len(keep_ids) + len(uploads) > MAX_ANNOTATION_IMAGES:
        return _error('image_count', f'At most {MAX_ANNOTATION_IMAGES} images are allowed')
    try:
        validated = [_validated_image(upload) for upload in uploads]
    except ValueError as exc:
        return _error('invalid_image', str(exc))

    with transaction.atomic(using=alias):
        annotation, created = RecordAnnotation.objects.using(alias).get_or_create(
            qor_record_id=record.id,
            defaults={
                'text': text,
                'author_id': request.user.id,
                'editor_id': request.user.id,
                'created_at': timezone.now(),
                'updated_at': timezone.now(),
            },
        )
        if not created:
            annotation.text = text
            annotation.editor_id = request.user.id
            annotation.updated_at = timezone.now()
            annotation.save(using=alias, update_fields=('text', 'editor_id', 'updated_at'))
        annotation.images.using(alias).exclude(id__in=keep_ids).delete()
        for image in validated:
            RecordAnnotationImage.objects.using(alias).create(
                annotation_id=annotation.id,
                uploaded_by=request.user.id,
                **image,
            )
        if not annotation.text and not annotation.images.using(alias).exists():
            annotation.delete(using=alias)
            annotation = None
        elif annotation:
            annotation = (
                RecordAnnotation.objects.using(alias)
                .prefetch_related('images')
                .get(pk=annotation.id)
            )
    return JsonResponse({
        'ok': True,
        'data': {
            'annotation': _annotation_payload(annotation, project_id, record),
            'can_edit': can_edit,
        },
    })


@require_GET
@api_auth_required('read')
def annotation_image(request, project_id, record_id, image_id):
    project, alias, record = _annotation_record(request, project_id, record_id)
    if not project or not _can_view(request.user, project_id):
        return _error('forbidden', 'project access denied', 403)
    if record is None:
        return _error('not_found', 'record not found', 404)
    image = (
        RecordAnnotationImage.objects.using(alias)
        .filter(id=image_id, annotation__qor_record_id=record.id)
        .first()
    )
    if image is None:
        return _error('not_found', 'image not found', 404)
    response = HttpResponse(bytes(image.content), content_type=image.content_type)
    response['Content-Length'] = str(image.byte_size)
    response['Content-Disposition'] = f"inline; filename*=UTF-8''{quote(image.filename)}"
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=300'
    return response


@require_http_methods(['POST'])
@api_auth_required('read')
def annotation_batch(request):
    try:
        body = json.loads(request.body or b'{}')
        requested = body.get('records', [])
    except (TypeError, json.JSONDecodeError):
        return _error('invalid_json', 'valid JSON is required')
    if not isinstance(requested, list) or len(requested) > 200:
        return _error('invalid_records', 'records must be an array of at most 200 items')

    grouped = {}
    for item in requested:
        try:
            project_id = int(item['project_id'])
            record_id = int(item['record_id'])
        except (KeyError, TypeError, ValueError):
            return _error('invalid_records', 'each record requires integer project_id and record_id')
        if _project(project_id) and _can_view(request.user, project_id):
            grouped.setdefault(project_id, set()).add(record_id)

    results = []
    editor_flags = {}
    for project_id, record_ids in grouped.items():
        project = _project(project_id)
        get_project_engine(project_id)
        alias = _get_project_db_alias(project_id)
        records = QorRecord.objects.using(alias).select_related('module').filter(id__in=record_ids)
        record_map = {record.id: record for record in records}
        annotations = (
            RecordAnnotation.objects.using(alias)
            .prefetch_related('images')
            .filter(qor_record_id__in=record_map)
        )
        for annotation in annotations:
            record = record_map.get(annotation.qor_record_id)
            if record and (annotation.text or annotation.images.all()):
                results.append((project_id, record, annotation))
                editor_flags[(project_id, record.id)] = _can_edit_annotation(
                    request.user, project, record
                )
    user_ids = {
        value
        for _, _, annotation in results
        for value in (annotation.author_id, annotation.editor_id)
    }
    users = {user.id: user for user in User.objects.filter(id__in=user_ids)}
    return JsonResponse({
        'ok': True,
        'data': [
            {
                **_annotation_payload(annotation, project_id, record, users),
                'can_edit': editor_flags[(project_id, record.id)],
            }
            for project_id, record, annotation in results
        ],
    })


@require_GET
@api_auth_required('read')
def versions(request):
    project_ids = _resolve_project_ids(request)
    if project_ids is None:
        return _error('invalid_project_id', 'project_ids must be integers')
    try:
        query = {'offset': 0, 'limit': 10000}
        values, invalid = set(), []
        for pid in project_ids:
            rows, _ = get_record_repository().list_records(pid, **query)
            for row in rows:
                try:
                    values.add(derive_version(row.get('full_dir')))
                except PathDerivationError as exc:
                    invalid.append({'record_id': str(row.get('id')), 'error': exc.as_dict()})
    except Exception as exc:
        return _error('repository_error', 'version query failed', 503, {'reason': str(exc)})
    return JsonResponse({
        'ok': True,
        'data': sorted(values),
        'meta': {'invalid_path_count': len(invalid), 'invalid_paths': invalid[:20]},
    })
