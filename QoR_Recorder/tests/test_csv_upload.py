import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connections

from django_app.core.db_routing import _get_project_db_alias, get_project_engine
from django_app.core.models import Module, Project, QorRecord, User
from django_app.services.csv_upload_paths import (
    UploadPathError,
    infer_module_from_path,
    normalize_relative_upload_path,
)
from django_app.services.path_derivation import derive_version
from django_app.services.csv_field_mapping import CSV_FIELD_ALIASES
from django_app.services.qor_import import CSV_FIELD_ALIASES as IMPORT_ALIASES
from django_app.services.qor_import import normalize_csv_record
from django_app.services.timing_normalization import normalize_timing_sections
from scripts.csv_to_json import csv_to_json


def _discard_dynamic_connection(alias):
    if alias in connections.databases:
        connections[alias].close()
        connections.databases.pop(alias, None)
    if hasattr(connections._connections, alias):
        delattr(connections._connections, alias)


@pytest.fixture
def csv_upload_env(tmp_path, settings, django_db_blocker):
    settings.DATA_DIR = tmp_path
    with django_db_blocker.unblock():
        admin = User.objects.create_user('csv-upload-admin', password='x', role='admin')
        project = Project.objects.create(name='CSV Upload Project')
        alias = _get_project_db_alias(project.id)
        _discard_dynamic_connection(alias)
        get_project_engine(project.id)
        call_command('migrate', database=alias, verbosity=0, interactive=False)
        module = Module.objects.using(alias).create(
            project_id=project.id,
            name='module_alu',
            owner_id=admin.id,
        )
    yield {'admin': admin, 'project': project, 'module': module, 'alias': alias}
    with django_db_blocker.unblock():
        _discard_dynamic_connection(alias)


def test_csv_legacy_aliases_are_defined_once():
    assert IMPORT_ALIASES is CSV_FIELD_ALIASES
    assert CSV_FIELD_ALIASES == {
        'total_area': 'area_total',
        'comb_area': 'area_combinational',
        'reg_area': 'area_sequential',
        'macro_area': 'area_macro',
        'total_count': 'instance_count',
        'reg_count': 'register_count',
        'macro_count': 'macro_cell_count',
    }


def test_demo_legacy_fields_and_dynamic_path_groups_are_normalized():
    record = normalize_csv_record({
        'total_area': '542',
        'comb_area': '348',
        'reg_area': '144',
        'macro_area': '50',
        'total_count': '702',
        'reg_count': '120',
        'macro_count': '2',
        'comb_count': '580',
        'stdcell_area': '492',
        'SYS_CLK_wns': '-0.15',
    })

    assert record['area_total'] == '542'
    assert record['area_combinational'] == '348'
    assert record['area_sequential'] == '144'
    assert record['area_macro'] == '50'
    assert record['instance_count'] == '702'
    assert record['register_count'] == '120'
    assert record['macro_cell_count'] == '2'
    assert record['wns_setup'] == -0.15
    assert record['extra_fields']['comb_count'] == '580'
    assert record['extra_fields']['stdcell_area'] == '492'
    assert record['extra_fields']['SYS_CLK_wns'] == '-0.15'
    expected_group = {'wns': -0.15}
    assert record['extra_fields']['path_groups'] == {
        'SYS_CLK': expected_group,
    }
    assert record['extra_fields']['clocks'] == {'SYS_CLK': expected_group}
    assert record['extra_fields']['timing_sections'] == {
        'default': {'default': {'SYS_CLK': expected_group}},
    }


def test_stdcell_area_reconstructs_total_when_total_area_missing():
    record = normalize_csv_record({
        'stdcell_area': '492',
        'macro_area': '50',
    })
    assert record['area_macro'] == '50'
    assert record['area_total'] == 542.0
    assert record['extra_fields']['stdcell_area'] == '492'


def test_csv_to_json_reconstructs_total_and_uses_shared_aliases(tmp_path):
    csv_path = tmp_path / 'module_alu_qor.csv'
    csv_path.write_text(
        'stdcell_area,macro_area,comb_area,reg_count,macro_count,total_count\n'
        '492,50,348,120,2,702\n',
        encoding='utf-8',
    )
    payload = csv_to_json(csv_path, project_id=1, version='fallback')
    record = payload['records'][0]
    assert record['module_name'] == 'module_alu'
    assert record['area'] == {
        'total': 542.0,
        'combinational': 348.0,
        'macro': 50.0,
    }
    assert record['cells'] == {
        'register_count': 120,
        'macro_cell_count': 2,
        'instance_count': 702,
    }
    assert record['extra']['stdcell_area'] == 492.0


def test_dynamic_path_groups_support_underscores_and_safe_empty_values():
    record = normalize_csv_record({
        'SYS_CLK_period': '2',
        'SYS_CLK_wns': '-0.15',
        'SYS_CLK_tns': '-0.42',
        'SYS_CLK_path': '3',
        'I2C_CLK_period': '5',
        'I2C_CLK_wns': '0.12',
        'I2C_CLK_tns': '0',
        'I2C_CLK_path': '0',
        'CPU_SUB_SYS_CLK_period': '1.25',
        'CPU_SUB_SYS_CLK_wns': '-0.25',
        'CPU_SUB_SYS_CLK_tns': '',
        'CPU_SUB_SYS_CLK_path': 'not-a-count',
        'CPU_SUB_SYS_CLK_hold_wns': '-0.01',
        'CPU_SUB_SYS_CLK_hold_path': '2',
        'EMPTY_CLK_wns': '',
        'BAD_CLK_tns': 'NaN',
    })

    groups = record['extra_fields']['path_groups']
    assert groups == {
        'SYS_CLK': {'period': 2.0, 'wns': -0.15, 'tns': -0.42, 'nvp': 3},
        'I2C_CLK': {'period': 5.0, 'wns': 0.12, 'tns': 0.0, 'nvp': 0},
        'CPU_SUB_SYS_CLK': {
            'period': 1.25,
            'wns': -0.25,
            'hold_wns': -0.01,
            'hold_nvp': 2,
        },
    }
    assert record['wns_setup'] == -0.25
    assert record['tns_setup'] == -0.42
    assert record['nvp_setup'] == 3
    assert record['extra_fields']['CPU_SUB_SYS_CLK_path'] == 'not-a-count'
    assert record['extra_fields']['EMPTY_CLK_wns'] == ''


def test_real_demo_csv_conversion_has_two_path_groups_per_record():
    demo_path = (
        Path(__file__).resolve().parents[1]
        / 'demo_batch_upload'
        / 'module_alu'
        / 'module_alu_qor.csv'
    )

    payload = csv_to_json(demo_path, project_id=1, version='fallback')

    assert len(payload['records']) == 6
    for converted in payload['records']:
        assert set(converted['clocks']) == {'SYS_CLK', 'I2C_CLK'}
        assert set(converted['extra']['path_groups']) == {'SYS_CLK', 'I2C_CLK'}
        assert converted['timing']['setup']
    first = payload['records'][0]
    assert first['module_name'] == 'module_alu'
    assert first['area'] == {
        'total': 542.0,
        'combinational': 348.0,
        'sequential': 144.0,
        'macro': 50.0,
    }
    assert first['cells']['instance_count'] == 702
    assert first['cells']['register_count'] == 120
    assert first['cells']['macro_cell_count'] == 2
    assert first['extra']['stdcell_area'] == 492.0
    assert first['clocks']['SYS_CLK'] == {
        'period': 2.0, 'wns': -0.15, 'tns': -0.42, 'nvp': 3,
    }
    assert first['timing']['setup'] == {
        'wns': -0.15, 'tns': -0.42, 'nvp': 3,
    }


def test_legacy_release_segments_and_controlled_fallback():
    assert derive_version('/proj/decoder/module_alu/v1') == 'v1'
    assert derive_version('/proj/decoder/module_alu/v7') == 'v7'
    assert derive_version('/proj/regr_20260831/main/v7') == 'regr_20260831'
    assert derive_version('/proj/decoder/module_alu/run', fallback='manual-v8') == 'manual-v8'


@pytest.mark.parametrize('unsafe_path', [
    '',
    '/tmp/module/qor.csv',
    r'C:\tmp\module\qor.csv',
    r'base\..\secret.csv',
    'base/module/readme.txt',
])
def test_browser_upload_paths_reject_unsafe_or_non_csv_values(unsafe_path):
    with pytest.raises(UploadPathError):
        normalize_relative_upload_path(unsafe_path)


def test_browser_upload_paths_normalize_separators_and_infer_modules():
    path = normalize_relative_upload_path(
        r'demo_batch_upload\module_alu\module_alu_qor.csv',
    )
    assert path == 'demo_batch_upload/module_alu/module_alu_qor.csv'
    assert infer_module_from_path(path, 'dirname') == 'module_alu'
    assert infer_module_from_path(
        'demo_batch_upload/reports/module_ctrl_qor_report.csv',
        'filename',
        ('_qor', '_qor_report'),
    ) == 'module_ctrl'
    with pytest.raises(UploadPathError):
        infer_module_from_path('demo_batch_upload/block_qor.csv', 'dirname')


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_demo_csv_upload_imports_all_rows_into_selected_module(csv_upload_env, client):
    env = csv_upload_env
    demo_path = (
        Path(__file__).resolve().parents[1]
        / 'demo_batch_upload'
        / 'module_alu'
        / 'module_alu_qor.csv'
    )
    client.force_login(env['admin'])
    response = client.post('/api/admin/upload', {
        'project_id': str(env['project'].id),
        'module_id': str(env['module'].id),
        'files': SimpleUploadedFile(
            demo_path.name,
            demo_path.read_bytes(),
            content_type='text/csv',
        ),
    })

    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is True
    assert (body['saved'], body['updated'], body['skipped']) == (6, 0, 0)
    records = QorRecord.objects.using(env['alias']).filter(module_id=env['module'].id)
    assert set(records.values_list('version', flat=True)) == {'v1', 'v2', 'v3', 'v4', 'v5', 'v7'}
    first = records.get(version='v1')
    assert first.area_total == 542
    assert first.area_combinational == 348
    assert first.area_sequential == 144
    assert first.area_macro == 50
    assert first.instance_count == 702
    assert first.register_count == 120
    assert first.macro_cell_count == 2
    assert first.wns_setup == pytest.approx(-0.15)
    assert first.tns_setup == pytest.approx(-0.42)
    assert first.nvp_setup == 3
    extra = json.loads(first.extra_fields)
    assert extra['stdcell_area'] == '492'
    assert extra['SYS_CLK_wns'] == '-0.15'
    assert set(extra['timing_sections']['default']['default']) == {
        'SYS_CLK', 'I2C_CLK',
    }
    sections = normalize_timing_sections(first.to_dict())
    assert sections['default']['default']['SYS_CLK'] == {
        'clk_period': 2.0,
        'wns': -0.15,
        'tns': -0.42,
        'nvp': 3,
    }


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_all_skipped_upload_is_an_error_with_row_reasons(csv_upload_env, client):
    env = csv_upload_env
    client.force_login(env['admin'])
    response = client.post('/api/admin/upload', {
        'project_id': str(env['project'].id),
        'module_id': str(env['module'].id),
        'files': SimpleUploadedFile(
            'invalid.csv',
            b'area_total,full_dir\n1,\n',
            content_type='text/csv',
        ),
    })

    assert response.status_code == 422
    body = response.json()
    assert body['ok'] is False
    assert body['saved'] == body['updated'] == 0
    assert body['skipped'] == 1
    result = body['file_results'][0]
    assert result['ok'] is False
    assert result['errors'][0]['row'] == 2
    assert result['errors'][0]['code'] == 'missing_full_dir'


def _demo_directory_payload():
    demo_root = Path(__file__).resolve().parents[1] / 'demo_batch_upload'
    paths = sorted(demo_root.rglob('*.csv'))
    uploads = [
        SimpleUploadedFile(path.name, path.read_bytes(), content_type='text/csv')
        for path in paths
    ]
    relative_paths = [path.relative_to(demo_root.parent).as_posix() for path in paths]
    return uploads, relative_paths


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_directory_preview_reports_every_demo_file_and_module_mapping(
    csv_upload_env, client,
):
    env = csv_upload_env
    uploads, relative_paths = _demo_directory_payload()
    client.force_login(env['admin'])
    response = client.post('/api/admin/upload_csv_preview', {
        'project_id': str(env['project'].id),
        'module_name_source': 'dirname',
        'filename_suffixes': '_qor,qor,_qor_report',
        'files': uploads,
        'file_paths': relative_paths,
    })

    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is True
    assert body['summary'] == {
        'total_files': 6,
        'valid_files': 5,
        'error_files': 1,
        'total_rows': 18,
    }
    by_path = {item['relative_path']: item for item in body['files']}
    alu = by_path['demo_batch_upload/module_alu/module_alu_qor.csv']
    assert alu['inferred_module'] == 'module_alu'
    assert alu['module_exists'] is True
    assert alu['can_auto_create'] is False
    rf = by_path['demo_batch_upload/module_rf/module_rf_qor.csv']
    assert rf['inferred_module'] == 'module_rf'
    assert rf['module_exists'] is False
    assert rf['can_auto_create'] is True
    root_file = by_path['demo_batch_upload/block_qor.csv']
    assert root_file['errors'][0]['code'] == 'invalid_upload_file'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_directory_preview_accepts_155_module_files(csv_upload_env, client, settings):
    env = csv_upload_env
    assert settings.DATA_UPLOAD_MAX_NUMBER_FILES >= 155
    uploads = [
        SimpleUploadedFile(
            f'module_{index}_qor.csv',
            b'area_total,full_dir\n1,/release/run\n',
            content_type='text/csv',
        )
        for index in range(155)
    ]
    relative_paths = [
        f'base/module_{index}/module_{index}_qor.csv'
        for index in range(155)
    ]
    client.force_login(env['admin'])

    response = client.post('/api/admin/upload_csv_preview', {
        'project_id': str(env['project'].id),
        'module_name_source': 'filename',
        'filename_suffixes': '_qor,qor,_qor_report',
        'files': uploads,
        'file_paths': relative_paths,
    })

    assert response.status_code == 200
    body = response.json()
    assert body['summary'] == {
        'total_files': 155,
        'valid_files': 155,
        'error_files': 0,
        'total_rows': 155,
    }
    assert body['files'][0]['inferred_module'] == 'module_0'
    assert body['files'][-1]['inferred_module'] == 'module_154'


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_upload_file_limit_returns_actionable_json(
    csv_upload_env, client, settings,
):
    settings.DEBUG = False
    settings.DATA_UPLOAD_MAX_NUMBER_FILES = 1
    client.force_login(csv_upload_env['admin'])
    uploads = [
        SimpleUploadedFile(f'{index}.csv', b'a\n1\n', content_type='text/csv')
        for index in range(2)
    ]

    response = client.post('/api/admin/upload_csv_preview', {'files': uploads})

    assert response.status_code == 400
    assert response.json() == {
        'error': '上传文件数量超过服务器限制（最多 1 个）',
    }


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_demo_directory_upload_isolates_root_file_and_imports_module_folders(
    csv_upload_env, client,
):
    env = csv_upload_env
    uploads, relative_paths = _demo_directory_payload()
    client.force_login(env['admin'])
    response = client.post('/api/admin/upload', {
        'project_id': str(env['project'].id),
        'module_name_source': 'dirname',
        'filename_suffixes': '_qor,qor,_qor_report',
        'files': uploads,
        'file_paths': relative_paths,
    })

    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is True
    assert (body['saved'], body['updated'], body['skipped']) == (18, 0, 0)
    assert (body['successful_files'], body['failed_files']) == (5, 1)
    assert {item['inferred_module'] for item in body['file_results'] if item['ok']} == {
        'module_alu', 'module_ctrl', 'module_mem', 'module_misc', 'module_rf',
    }
    failed = next(item for item in body['file_results'] if not item['ok'])
    assert failed['relative_path'] == 'demo_batch_upload/block_qor.csv'
    assert 'base/module_name' in failed['error']
    modules = Module.objects.using(env['alias']).filter(
        project_id=env['project'].id,
    )
    assert set(modules.values_list('name', flat=True)) == {
        'module_alu', 'module_ctrl', 'module_mem', 'module_misc', 'module_rf',
    }
    assert QorRecord.objects.using(env['alias']).count() == 18
