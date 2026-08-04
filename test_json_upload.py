"""Smoke test for services/json_upload.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.json_upload import (
    JSONUploadError, validate_upload_json,
    json_to_qor_records, json_to_violation_records, json_to_notes_records
)

print('=== Import ===')
print('OK')

print()
print('=== validate_upload_json (valid) ===')
sample = {
    'schema_version': '1.0',
    'upload': {'project_id': 1, 'version': 'v1.0', 'module_name': 'cpu_top'},
    'records': [{
        'module_name': 'cpu_top',
        'version': 'v1.0',
        'area': {'total': 12345.6, 'combinational': 5678.9},
        'timing': {'setup': {'wns': -0.1, 'tns': -0.5, 'nvp': 12}},
        'power': {'internal': 1.2, 'total': 3.4},
        'clocks': {'SRAMCLK': {'period': 2.5, 'wns': -0.05}},
    }],
}
data = validate_upload_json(sample)
print('schema_version=', data['schema_version'])

print()
print('=== json_to_qor_records ===')
records = json_to_qor_records(data, default_version='v1.0', default_full_dir='/tmp/run')
print('count =', len(records))
for r in records:
    print('  module_name =', r['module_name'])
    print('  version     =', r['version'])
    print('  area_total  =', r.get('area_total'))
    print('  wns_setup   =', r.get('wns_setup'))
    print('  extra keys  =', list(r.get('extra_fields', {}).keys()))

print()
print('=== json_to_violation_records ===')
vp_data = {
    'schema_version': '1.0',
    'upload': {'project_id': 1, 'version': 'v1.0'},
    'violation_paths': [{
        'module_name': 'cpu_top',
        'timing_group': 'SRAMCLK',
        'slack': -0.12,
        'startpoint': 'ff_a/Q',
        'endpoint': 'ff_b/D',
    }, {
        'module_name': 'cpu_top',
        'timing_group': 'SRAMCLK',
        'slack': -0.34,
        'startpoint': 'ff_c/Q',
        'endpoint': 'ff_d/D',
        'type': 'setup',
    }],
}
vp_data = validate_upload_json(vp_data)
vps = json_to_violation_records(vp_data, default_version='v1.0')
print('count =', len(vps))
for v in vps:
    print('  module=%s, tg=%s, slack=%s' % (v['module_name'], v['timing_group'], v['slack']))

print()
print('=== json_to_notes_records ===')
notes_data = {
    'schema_version': '1.0',
    'upload': {'project_id': 1, 'version': 'v1.0', 'full_dir': '/proj/v1.0'},
    'notes': [{
        'module_name': 'cpu_top',
        'full_dir': '/proj/v1.0',
        'items': [
            {'item': 'tcl_revision', 'value': 'abc123'},
            {'item': 'corner', 'value': 'ss_125c'},
        ],
    }],
}
notes_data = validate_upload_json(notes_data)
notes = json_to_notes_records(notes_data)
print('count =', len(notes))
for n in notes:
    print('  module=%s, item=%s, desc=%s' % (n['module_name'], n['item'], n['description']))

print()
print('=== Error: schema_version 2.0 ===')
try:
    validate_upload_json({'schema_version': '2.0', 'upload': {}})
    print('FAIL')
except JSONUploadError as e:
    print('OK:', e.path, '-', e.message)

print()
print('=== Error: missing upload ===')
try:
    validate_upload_json({'schema_version': '1.0'})
    print('FAIL')
except JSONUploadError as e:
    print('OK:', e.path, '-', e.message)

print()
print('=== Error: missing project_id ===')
try:
    validate_upload_json({'schema_version': '1.0', 'upload': {'version': 'v1.0'}})
    print('FAIL')
except JSONUploadError as e:
    print('OK:', e.path, '-', e.message)

print()
print('=== Error: missing module_name in record ===')
try:
    validate_upload_json({
        'schema_version': '1.0',
        'upload': {'project_id': 1, 'version': 'v1.0'},
        'records': [{'area': {'total': 100}}],
    })
    print('FAIL')
except JSONUploadError as e:
    print('OK:', e.path, '-', e.message)

print()
print('=== Error: invalid violation_path (missing slack) ===')
try:
    validate_upload_json({
        'schema_version': '1.0',
        'upload': {'project_id': 1, 'version': 'v1.0'},
        'violation_paths': [{
            'module_name': 'cpu', 'timing_group': 'clk',
            'startpoint': 'a', 'endpoint': 'b',
        }],
    })
    print('FAIL')
except JSONUploadError as e:
    print('OK:', e.path, '-', e.message)

print()
print('=== Done ===')
