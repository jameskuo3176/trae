import pytest

from django_app.services import json_upload

_SYN_REGR_FULL_DIR = (
    '/project/feint2/SYN/harbinger/weekly/syn_regr_0817/main/'
    'core_tcgbr_t_work_master0903_def0901'
)


def _syn_regr_payload(*, include_upload_version: bool = True) -> dict:
    upload = {
        'project_id': 4,
        'full_dir': _SYN_REGR_FULL_DIR,
    }
    if include_upload_version:
        upload['version'] = 'syn_regr_0817'
    return {
        'schema_version': '1.0',
        'upload': upload,
        'records': [{
            'module_name': 'core_tcgbr_t',
            'area': {'total': 123.5, 'sequential': 45.25},
            'cells': {'cell_count': 42, 'sequential_cell_count': 7},
        }],
    }


def test_syn_regr_full_dir_passes_json_validation():
    json_upload.validate_upload_json(_syn_regr_payload())


def test_syn_regr_full_dir_json_to_qor_records_uses_path_version():
    records = json_upload.json_to_qor_records(_syn_regr_payload())
    assert len(records) == 1
    record = records[0]
    assert record['version'] == 'syn_regr_0817'
    assert record['full_dir'] == _SYN_REGR_FULL_DIR
    assert record['tag'] == 'core_tcgbr_t_work_master0903_def0901'
    assert record['module_name'] == 'core_tcgbr_t'
    assert record['area_total'] == 123.5


def test_path_derived_version_wins_over_explicit_upload_version():
    payload = _syn_regr_payload(include_upload_version=True)
    payload['upload']['version'] = 'wrong-version'
    records = json_upload.json_to_qor_records(payload)
    assert records[0]['version'] == 'syn_regr_0817'


def test_explicit_upload_version_is_fallback_when_path_has_no_segment():
    payload = {
        'schema_version': '1.0',
        'upload': {
            'project_id': 4,
            'full_dir': '/project/decoder/module_alu/run',
            'version': 'manual-v8',
        },
        'records': [{'module_name': 'module_alu', 'area': {'total': 1.0}}],
    }
    json_upload.validate_upload_json(payload)
    records = json_upload.json_to_qor_records(payload)
    assert records[0]['version'] == 'manual-v8'


@pytest.mark.parametrize(
    'path_fields',
    [
        {'full_dir': _SYN_REGR_FULL_DIR},
        {'directory': _SYN_REGR_FULL_DIR},
        {'full_dir': _SYN_REGR_FULL_DIR, 'directory': _SYN_REGR_FULL_DIR},
        {'full_dir': '  ', 'directory': _SYN_REGR_FULL_DIR},
    ],
    ids=['full-dir-only', 'directory-only', 'both-same', 'blank-full-dir'],
)
def test_upload_path_aliases_normalize_to_full_dir(path_fields):
    payload = _syn_regr_payload()
    payload['upload'].pop('full_dir')
    payload['upload'].update(path_fields)

    normalized = json_upload.validate_upload_json(payload)

    assert normalized['upload']['full_dir'] == _SYN_REGR_FULL_DIR
    assert 'directory' not in normalized['upload']
    assert json_upload.json_to_qor_records(normalized)[0]['full_dir'] == _SYN_REGR_FULL_DIR


def test_conflicting_upload_path_aliases_are_rejected():
    payload = _syn_regr_payload()
    payload['upload']['directory'] = '/project/other/regr_20260908/main/core'

    with pytest.raises(json_upload.JSONUploadError, match='同时存在但值不同'):
        json_upload.validate_upload_json(payload)
