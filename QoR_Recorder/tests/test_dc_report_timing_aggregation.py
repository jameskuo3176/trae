import json
from pathlib import Path
import sys

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
sys.path.insert(0, str(EXAMPLES.parent / 'django_app'))

from scripts.dc_report_to_json import convert_dc_to_qor_record  # noqa: E402
from django_app.services.timing_normalization import normalize_timing_sections  # noqa: E402


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
