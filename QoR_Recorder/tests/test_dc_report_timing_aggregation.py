import json
from pathlib import Path
import subprocess
import sys

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
sys.path.insert(0, str(EXAMPLES.parent / 'django_app'))

from scripts.dc_report_to_json import (  # noqa: E402
    DCReportError,
    convert_dc_to_qor_record,
    is_dc_report,
    validate_dc_report,
)
from django_app.services.timing_normalization import normalize_timing_sections  # noqa: E402
from django_app.services import json_upload  # noqa: E402


def test_demo_b_tns_sums_negative_path_groups():
    source = json.loads((EXAMPLES / 'newproject_demoB_dc_report.json').read_text())

    payload = convert_dc_to_qor_record(source)
    record = payload['records'][0]

    assert record['timing']['setup']['wns'] == pytest.approx(-15.75)
    assert record['timing']['setup']['tns'] == pytest.approx(-265.3)
    assert record['extra']['aggregate_tns_negative_sum'] == pytest.approx(-265.3)
    assert record['extra']['timing_final']['scenarios']['ss0p72v_125c'][
        'tns_total'
    ] == pytest.approx(-161.65)

    sections = normalize_timing_sections({'extra_fields': record['extra']})
    assert list(sections['default']) == ['ss0p72v_125c']
    assert sections['default']['ss0p72v_125c']['CORECLK']['wns'] == -15.75
    assert sections['default']['ss0p72v_125c']['BUSCLK']['tns'] == -44.8
    assert sections['default']['ss0p72v_125c']['DBGCLK']['nvp'] == 0


def test_nonnegative_tns_does_not_cancel_negative_violations():
    source = json.loads((EXAMPLES / 'newproject_demoB_dc_report.json').read_text())
    groups = source['timing']['default']['scenarios']['ss0p72v_125c']['path_groups']
    groups['DBGCLK']['TNS'] = 500

    payload = convert_dc_to_qor_record(source)

    assert payload['records'][0]['timing']['setup']['tns'] == pytest.approx(-265.3)


@pytest.mark.parametrize(
    'run_fields',
    [
        {'full_dir': '/project/regr_20260908/main/demo_b'},
        {'directory': '/project/regr_20260908/main/demo_b'},
        {
            'full_dir': '/project/regr_20260908/main/demo_b',
            'directory': '/project/regr_20260908/main/demo_b',
        },
        {
            'full_dir': '   ',
            'directory': '/project/regr_20260908/main/demo_b',
        },
    ],
    ids=['full-dir-only', 'directory-only', 'both-same', 'blank-full-dir'],
)
def test_native_dc_run_path_aliases_canonicalize_to_full_dir(run_fields):
    source = json.loads((EXAMPLES / 'newproject_demoB_dc_report.json').read_text())
    source['schema_version'] = source.pop('scheme_version')
    source['run'] = run_fields

    validate_dc_report(source)
    assert is_dc_report(source)

    payload = convert_dc_to_qor_record(source, project_id=2, version='v1.0')

    assert payload['schema_version'] == '1.0'
    assert payload['upload']['full_dir'] == '/project/regr_20260908/main/demo_b'
    assert payload['records'][0]['full_dir'] == '/project/regr_20260908/main/demo_b'


def test_native_dc_conflicting_run_path_aliases_are_rejected():
    source = json.loads((EXAMPLES / 'newproject_demoB_dc_report.json').read_text())
    source['run'] = {
        'full_dir': '/project/regr_20260908/main/demo_b',
        'directory': '/project/regr_20260908/main/other',
    }

    with pytest.raises(DCReportError, match='同时存在但值不同'):
        validate_dc_report(source)


def test_populated_native_scenario_preserves_uppercase_metrics(tmp_path):
    source = {
        'schema_version': 1,
        'top_module': 'core_tcgbr_t',
        'run': {
            'full_dir': (
                '/project/feint2/SYN/harbinger/weekly/syn_regr_0817/main/'
                'core_tcgbr_t_work_master0903_def0901'
            ),
        },
        'timing': {
            'default': {
                'source': (
                    '/project/feint2/SYN/harbinger/weekly/syn_regr_0817/main/'
                    'core_tcgbr_t_work_master0903_def0901/rpts/Synthesis/'
                    'Synthesis.rpt.gz'
                ),
                'status': 'ok',
                'metadata': {
                    'report': 'qor',
                    'design': 'core_tcgbr_t',
                    'scenarios': 'tt0p85v85c_typical',
                    'version': 'X-2025.06-SP3',
                    'date': 'Sat Sep 5 02:00:33 2026',
                },
                'scenarios': {
                    'tt0p85v85c_typical': {
                        'path_groups': {
                            'DFX_JTAG_TCLK': {
                                'LOL': 21,
                                'WNS': 16858,
                                'Clk_Period': 36364,
                                'TNS': 0,
                                'NVP': 0,
                            },
                        },
                    },
                },
            },
        },
    }

    input_path = tmp_path / 'Synthesis.qor_summary.json'
    output_path = tmp_path / 'upload.json'
    input_path.write_text(json.dumps(source), encoding='utf-8')
    proc = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES.parent / 'scripts' / 'dc_report_to_json.py'),
            '--project-id', '2',
            '--version', 'v1.0',
            str(input_path),
            '-o', str(output_path),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '[OK]' in proc.stderr
    payload = json.loads(output_path.read_text(encoding='utf-8'))
    record = payload['records'][0]

    assert record['timing']['setup'] == {'wns': 16858.0, 'tns': 0, 'nvp': 0}
    assert record['clocks']['DFX_JTAG_TCLK'] == {
        'period': 36364.0,
        'wns': 16858.0,
        'tns': 0.0,
        'nvp': 0,
    }
    expected_group = {
        'wns': 16858.0,
        'tns': 0.0,
        'nvp': 0,
        'period': 36364.0,
        'lol': 21,
    }
    assert record['extra']['scenarios']['tt0p85v85c_typical'][
        'DFX_JTAG_TCLK'
    ] == expected_group
    assert record['extra']['timing_sections']['default'][
        'tt0p85v85c_typical'
    ]['DFX_JTAG_TCLK'] == expected_group


def test_empty_timing_sections_accept_metadata_scenario_strings():
    source = {
        'schema_version': 1,
        'top_module': 'io_d2dw2_t',
        'run': {'full_dir': '/project/io_d2dw2_t_work'},
        'timing': {
            'default': {
                'source': '/project/rpts/Synthesis.rpt.gz',
                'status': 'empty',
                'metadata': {'report': 'qor', 'scenarios': 'default'},
                'scenarios': 'default',
                'warnings': ['No timing path groups were found.'],
            },
            'final': {
                'source': '/project/rpts/Synthesis.report_qor_final.rpt',
                'status': 'empty',
                'metadata': {'report': 'qor', 'scenarios': 'default'},
                'scenarios': 'default',
                'warnings': ['No timing path groups were found.'],
            },
        },
        'area': {
            'tile': {
                'area': {'total': 123.5},
                'cell_count': {'total': 42, 'sequential': 7},
            },
        },
    }

    validate_dc_report(source)
    payload = convert_dc_to_qor_record(source, project_id=3, version='v1.1')
    record = payload['records'][0]

    assert record['area'] == {'total': 123.5}
    assert record['cells'] == {'cell_count': 42, 'sequential_cell_count': 7}
    assert 'timing' not in record
    assert 'clocks' not in record
    assert 'timing_sections' not in record['extra']
    assert 'scenarios' not in record['extra']
    assert record['extra']['timing_group_count'] == 0
    assert record['extra']['path_group_count'] == 0
    assert record['extra']['timing_final']['status'] == 'empty'
    assert 'scenarios' not in record['extra']['timing_final']
    assert payload['_raw_dc_report'] is source


def test_native_area_metadata_and_warning_lists_are_not_metric_payloads():
    full_dir = (
        '/project/feint2/SYN/harbinger/weekly/syn_regr_0817/main/'
        'core_tcgbr_t_work_master0903_def0901'
    )
    source = {
        'schema_version': 1,
        'top_module': 'core_tcgbr_t',
        'run': {'full_dir': full_dir},
        'timing': {
            'default': {
                'status': 'empty',
                'scenarios': 'tt0p85v85c_typical',
                'warnings': ['No timing path groups were found.'],
            },
        },
        'area': {
            'source': f'{full_dir}/rpts/Synthesis/Synthesis.dat',
            'status': 'ok',
            'metadata': {
                'report': 'area',
                'scenarios': 'tt0p85v85c_typical',
            },
            'scenarios': ['tt0p85v85c_typical'],
            'warnings': ['Area report used fallback units.'],
            'tile': {
                'area': {'total': 123.5, 'sequential': 45.25},
                'cell_count': {'total': 42, 'sequential': 7},
            },
        },
        'misc': {
            'status': 'ok',
            'warnings': ['No congestion report was found.'],
        },
    }

    validate_dc_report(source)
    payload = convert_dc_to_qor_record(
        source,
        project_id=4,
        version='syn_regr_0817',
    )
    record = payload['records'][0]

    assert record['area'] == {'total': 123.5, 'sequential': 45.25}
    assert record['cells'] == {'cell_count': 42, 'sequential_cell_count': 7}
    assert payload['_raw_dc_report']['area']['warnings'] == [
        'Area report used fallback units.',
    ]
    assert payload['_raw_dc_report']['area']['metadata']['scenarios'] == (
        'tt0p85v85c_typical'
    )


def test_native_dc_non_combinational_and_total_flops_map_to_dashboard_fields():
    """Screenshot shape: non_combinational → Sequential area; total_flops → Register count."""
    source = {
        'schema_version': 1,
        'top_module': 'core_tcgbf_t',
        'run': {
            'full_dir': (
                '/project/feint2/SYN/harbinger/weekly/syn_regr_0817/main/'
                'core_tcgbf_t_work_master0903_def0901_mbistpart'
            ),
        },
        'timing': {
            'default': {
                'status': 'empty',
                'scenarios': {},
            },
        },
        'area': {
            'source': '/project/feint2/SYN/harbinger/rpts/Synthesis/Synthesis.dat',
            'status': 'ok',
            'tile': {
                'cell_count': {
                    'total': 2671402,
                    'sequential': 976904,
                    'combinational': 1694498,
                    'ram': 93,
                    'macro': 0,
                },
                'area': {
                    'total': 411493,
                    'total_cell': 411493,
                    'non_combinational': 209993,
                    'combinational': 99556,
                    'memory': 101788,
                    'macro': 0,
                    'standard_cell': 309706,
                },
            },
        },
        'misc': {
            'source': '/project/feint2/SYN/harbinger/rpts/Synthesis/Synthesis.dat',
            'status': 'ok',
            'fgcg': {
                'gated_flops': {'count': 934196, 'percentage': '97.00%'},
                'not_gated_flops': {'count': 28854, 'percentage': '3.00%'},
                'total_flops': 963050,
                'clock_gating_cells': 1,
            },
            'vt_ratio': {
                'LVTLL06': '0.00%',
                'LVT06': '99.99%',
                'ELVT06': '0.00%',
                'ULVTLL06': '0.00%',
                'ULVT06': '0.01%',
                'undefined': '0.00%',
                'SVT06': '0.00%',
                'LVT': '99.99%',
                'ULVT': '0.01%',
            },
        },
    }

    validate_dc_report(source)
    payload = convert_dc_to_qor_record(source, project_id=4, version='syn_regr_0817')
    record = payload['records'][0]

    assert record['area']['combinational'] == 99556
    assert record['area']['sequential'] == 209993
    assert record['cells']['register_count'] == 963050
    assert record['register_count'] == 963050
    # sequential cell count stays distinct from register_count
    assert record['cells']['sequential_cell_count'] == 976904
    assert record['extra']['misc_vt_ratio']['LVT06'] == '99.99%'
    assert payload['_raw_dc_report']['misc']['vt_ratio']['ULVT06'] == '0.01%'

    flat = json_upload.json_to_qor_records({
        'schema_version': '1.0',
        'upload': {
            'project_id': 4,
            'full_dir': source['run']['full_dir'],
            'version': 'syn_regr_0817',
        },
        'records': [record],
    })[0]
    assert flat['area_combinational'] == 99556
    assert flat['area_sequential'] == 209993
    assert flat['register_count'] == 963050


def test_json_upload_accepts_top_level_register_count_and_non_combinational_alias():
    records = json_upload.json_to_qor_records({
        'schema_version': '1.0',
        'upload': {
            'project_id': 4,
            'full_dir': '/project/feint2/SYN/demo/regr_20260817/main/core',
            'version': 'regr_20260817',
        },
        'records': [{
            'module_name': 'core',
            'area': {
                'total': 100,
                'combinational': 40,
                'non_combinational': 55,
            },
            'register_count': 1200,
        }],
    })
    assert records[0]['area_sequential'] == 55
    assert records[0]['register_count'] == 1200


def test_empty_native_area_metadata_does_not_fabricate_metrics():
    source = {
        'schema_version': 1,
        'top_module': 'core_tcgbr_t',
        'run': {'full_dir': '/project/regr_20260817/main/core_tcgbr_t_work'},
        'timing': {
            'default': {
                'status': 'empty',
                'scenarios': {},
            },
        },
        'area': {
            'source': '/project/rpts/Synthesis/Synthesis.dat',
            'status': 'empty',
            'metadata': {'report': 'area'},
            'warnings': ['No area values were found.'],
        },
    }

    validate_dc_report(source)
    record = convert_dc_to_qor_record(source)['records'][0]

    assert 'area' not in record
    assert 'cells' not in record


def test_area_metric_container_still_rejects_multiple_payloads():
    source = {
        'schema_version': 1,
        'top_module': 'core_tcgbr_t',
        'run': {'full_dir': '/project/regr_20260817/main/core_tcgbr_t_work'},
        'timing': {
            'default': {
                'status': 'empty',
                'scenarios': {},
            },
        },
        'area': {
            'warnings': [],
            'tile': [{'area': {'total': 1}}, {'area': {'total': 2}}],
        },
    }

    with pytest.raises(DCReportError, match=r'\$\.area\.tile'):
        validate_dc_report(source)


@pytest.mark.parametrize('group_key', [
    'path_groups', 'path_group', 'group_paths', 'group_path',
])
def test_timing_normalization_accepts_path_group_container_aliases(group_key):
    sections = normalize_timing_sections({
        'raw_dc_report': {
            'timing': {
                'default': {
                    'scenarios': {
                        'slow': {
                            group_key: {
                                'CORECLK': {'CORECLK_WNS': -3, 'CORECLK_TNS': -8},
                            },
                        },
                    },
                },
            },
        },
    })

    assert sections['default']['slow']['CORECLK'] == {
        'coreclk_wns': -3,
        'coreclk_tns': -8,
    }
