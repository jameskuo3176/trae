import json
import base64

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connections

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import Module, Project, ProjectMember, QorRecord, User
from django_app.services.timing_normalization import normalize_timing_sections


@pytest.fixture
def annotation_projects(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        editor = User.objects.create_user('annotation-editor', password='x', role='owner')
        viewer = User.objects.create_user('annotation-viewer', password='x', role='viewer')
        projects = [
            Project.objects.create(name='Annotation A'),
            Project.objects.create(name='Annotation B'),
        ]
        records = []
        for project in projects:
            get_project_engine(project.id)
            alias = _get_project_db_alias(project.id)
            call_command('migrate', database=alias, verbosity=0, interactive=False)
            module = Module.objects.using(alias).create(
                id=1, project_id=project.id, name=f'module-{project.id}', owner_id=editor.id
            )
            records.append(
                QorRecord.objects.using(alias).create(
                    id=1, module=module, version=f'v{project.id}', is_released=True
                )
            )
        ProjectMember.objects.create(project=projects[0], user=editor, role='editor')
    result = {
        'editor': editor,
        'viewer': viewer,
        'projects': projects,
        'records': records,
        'blocker': django_db_blocker,
    }
    yield result
    with django_db_blocker.unblock():
        for project in projects:
            alias = _get_project_db_alias(project.id)
            connections[alias].close()
            connections.databases.pop(alias, None)


VALID_GIF = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==')


def gif(name='evidence.gif', content=VALID_GIF):
    return SimpleUploadedFile(name, content, content_type='image/gif')


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_annotation_crud_images_headers_permissions_and_project_isolation(
    client, annotation_projects
):
    env = annotation_projects
    first, second = env['projects']
    editor = env['editor']
    with env['blocker'].unblock():
        client.force_login(editor)
        url = f'/api/v2/projects/{first.id}/records/1/annotation'
        response = client.post(
            url,
            {
                'text': 'Initial review evidence',
                'keep_image_ids': '[]',
                'images': [gif(), gif('second.gif')],
            },
        )
        assert response.status_code == 200
        saved = response.json()['data']['annotation']
        assert saved['text'] == 'Initial review evidence'
        assert len(saved['images']) == 2
        image = client.get(saved['images'][0]['url'])
        assert image.status_code == 200
        assert image['Content-Type'] == 'image/gif'
        assert image['X-Content-Type-Options'] == 'nosniff'
        assert image['Content-Disposition'].startswith('inline;')

        retained = saved['images'][0]['id']
        updated = client.post(
            url,
            {'text': 'Updated evidence', 'keep_image_ids': json.dumps([retained])},
        ).json()['data']['annotation']
        assert updated['text'] == 'Updated evidence'
        assert [item['id'] for item in updated['images']] == [retained]

        batch = client.post(
            '/api/v2/annotations/batch',
            data=json.dumps({
                'records': [
                    {'project_id': first.id, 'record_id': 1},
                    {'project_id': second.id, 'record_id': 1},
                ]
            }),
            content_type='application/json',
        )
        assert [(item['project_id'], item['record_id']) for item in batch.json()['data']] == [
            (first.id, '1')
        ]

        alias = _get_project_db_alias(first.id)
        QorRecord.objects.using(alias).filter(pk=1).update(is_released=False)
        client.force_login(env['viewer'])
        readable = client.get(url)
        assert readable.status_code == 200
        assert readable.json()['data']['annotation']['text'] == 'Updated evidence'
        assert readable.json()['data']['can_edit'] is False
        readable_batch = client.post(
            '/api/v2/annotations/batch',
            data=json.dumps({'records': [{'project_id': first.id, 'record_id': 1}]}),
            content_type='application/json',
        )
        assert readable_batch.status_code == 200
        assert readable_batch.json()['data'][0]['record_id'] == '1'
        assert readable_batch.json()['data'][0]['can_edit'] is False
        denied = client.post(
            url, {'text': 'viewer edit', 'keep_image_ids': json.dumps([retained])}
        )
        assert denied.status_code == 403


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_annotation_rejects_invalid_signature_size_and_count(client, annotation_projects):
    env = annotation_projects
    project = env['projects'][0]
    url = f'/api/v2/projects/{project.id}/records/1/annotation'
    with env['blocker'].unblock():
        client.force_login(env['editor'])
        invalid = client.post(
            url,
            {
                'text': '',
                'keep_image_ids': '[]',
                'images': SimpleUploadedFile(
                    'fake.png', b'<svg><script>alert(1)</script></svg>', content_type='image/png'
                ),
            },
        )
        assert invalid.status_code == 400
        assert invalid.json()['error']['code'] == 'invalid_image'

        malformed_gif = client.post(
            url,
            {
                'text': '',
                'keep_image_ids': '[]',
                'images': gif('trailer-only.gif', b'GIF89a-review-evidence;'),
            },
        )
        assert malformed_gif.status_code == 400
        assert malformed_gif.json()['error']['code'] == 'invalid_image'

        oversized = client.post(
            url,
            {
                'text': '',
                'keep_image_ids': '[]',
                'images': SimpleUploadedFile(
                    'large.gif', VALID_GIF + b'x' * (5 * 1024 * 1024)
                ),
            },
        )
        assert oversized.status_code == 400

        count = client.post(
            url,
            {
                'text': '',
                'keep_image_ids': '[]',
                'images': [gif(f'{index}.gif') for index in range(7)],
            },
        )
        assert count.status_code == 400
        assert count.json()['error']['code'] == 'image_count'


def test_timing_normalization_preserves_analysis_scenario_and_path_group():
    normalized = normalize_timing_sections({
        'extra_fields': {
            'timing_sections': {
                'default': {'slow': {'CORE': {'WNS': -2, 'TNS': -10}}},
            },
            'timing_final': {
                'scenarios': {
                    'slow': {'path_groups': {'CORE': {'WNS': -1, 'LoL': 4}}}
                }
            },
            'clocks': {'LEGACY': {'wns': -3, 'period': 900}},
        },
        'raw_dc_report': {
            'timing': {
                'future': {
                    'scenarios': {
                        'fast': {'path_groups': {'AUX': {'NVP': 2, 'Clk_Period': 1200}}}
                    }
                }
            }
        },
    })
    assert normalized['default']['slow']['CORE']['wns'] == -2
    assert normalized['final']['slow']['CORE']['wns'] == -1
    assert normalized['future']['fast']['AUX']['clk_period'] == 1200
    assert normalized['default']['default']['LEGACY']['clk_period'] == 900
