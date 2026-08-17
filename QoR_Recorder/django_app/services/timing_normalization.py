"""Normalize heterogeneous timing payloads without collapsing analysis types."""
from __future__ import annotations

import json
import re

_GROUP_KEYS = ('path_groups', 'path_group', 'group_paths', 'group_path')


def _dict(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
    return value if isinstance(value, dict) else {}


def _metric_name(name):
    value = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', str(name))
    value = value.replace('-', '_').replace(' ', '_')
    value = re.sub(r'_+', '_', value).strip('_').lower()
    return {
        'clk__period': 'clk_period',
        'clk_period': 'clk_period',
        'period': 'clk_period',
    }.get(value, value)


def _metrics(value):
    return {
        _metric_name(key): metric
        for key, metric in _dict(value).items()
        if key not in {'source', 'path', 'scenarios', *_GROUP_KEYS}
        and not isinstance(metric, (dict, list))
    }


def _merge_group(result, analysis, scenario, group, values):
    normalized = _metrics(values)
    if not normalized:
        return
    result.setdefault(str(analysis), {}).setdefault(str(scenario), {}).setdefault(
        str(group), {}
    ).update({
        key: value
        for key, value in normalized.items()
        if key not in result[str(analysis)][str(scenario)][str(group)]
    })


def _consume_analysis(result, analysis, value):
    value = _dict(value)
    scenarios = _dict(value.get('scenarios')) or value
    for scenario_name, scenario_value in scenarios.items():
        if scenario_name in {'source', 'status', 'metadata', 'warnings'}:
            continue
        scenario_value = _dict(scenario_value)
        groups = {}
        for key in _GROUP_KEYS:
            groups = _dict(scenario_value.get(key))
            if groups:
                break
        groups = groups or scenario_value
        for group_name, metrics in groups.items():
            if isinstance(metrics, dict):
                _merge_group(result, analysis, scenario_name, group_name, metrics)


def normalize_timing_sections(record):
    """Return analysis -> scenario -> path_group -> canonical metric mapping."""
    record = _dict(record)
    extra = _dict(record.get('extra_fields'))
    raw = _dict(record.get('raw_dc_report'))
    result = {}

    for source in (record.get('timing_sections'), extra.get('timing_sections')):
        for analysis, value in _dict(source).items():
            _consume_analysis(result, analysis, value)

    for analysis, value in _dict(raw.get('timing')).items():
        _consume_analysis(result, analysis, value)

    legacy_final = _dict(extra.get('timing_final'))
    if legacy_final:
        _consume_analysis(result, 'final', legacy_final)

    # Legacy scenarios/clocks mirror timing_sections in converted DC reports.
    # Only use those fallbacks when no richer default analysis was found.
    if 'default' not in result:
        legacy_scenarios = _dict(extra.get('scenarios'))
        if legacy_scenarios:
            _consume_analysis(result, 'default', legacy_scenarios)

    default_groups = {
        group
        for groups in result.get('default', {}).values()
        for group in groups
    }
    for source in (extra.get('path_groups'), extra.get('clocks')):
        for group, values in _dict(source).items():
            if group in default_groups:
                continue
            _merge_group(result, 'default', 'default', group, values)
            default_groups.add(group)

    return result
