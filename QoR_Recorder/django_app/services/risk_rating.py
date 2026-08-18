"""Deterministic weekly QoR risk ratings."""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


RISK_ORDER = {'unrated': -1, 'low': 0, 'medium': 1, 'high': 2}
RISK_LEVELS = ('low', 'medium', 'high')
EXCLUDED_PATH_GROUPS = frozenset({'I2C', 'C2O', 'I2O'})
DEFAULT_THRESHOLDS = {
    'tns_setup': {'medium_percent': 10.0, 'high_percent': 25.0},
    'area_total': {'medium_percent': 5.0, 'high_percent': 10.0},
    'utilization': {'medium_percent': 3.0, 'high_percent': 8.0},
}


def shanghai_week_window(value=None):
    tz = ZoneInfo('Asia/Shanghai')
    current = value or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)
    monday = current.date() - timedelta(days=current.weekday())
    start = datetime.combine(monday, time.min, tzinfo=tz)
    return start, start + timedelta(days=7)


def _worsening_percent(metric, current, baseline):
    if current is None or baseline is None:
        return None
    current, baseline = float(current), float(baseline)
    if metric == 'tns_setup':
        current_bad = abs(min(current, 0.0))
        baseline_bad = abs(min(baseline, 0.0))
        if baseline_bad == 0:
            return 0.0 if current_bad == 0 else float('inf')
        return ((current_bad - baseline_bad) / baseline_bad) * 100.0
    denominator = abs(baseline)
    if denominator < 1e-12:
        return 0.0 if current <= baseline else float('inf')
    return ((current - baseline) / denominator) * 100.0


def rate_record(current, baseline, thresholds=None):
    thresholds = thresholds or DEFAULT_THRESHOLDS
    details = []
    overall = 'low'
    rated = 0
    for metric in ('tns_setup', 'area_total', 'utilization'):
        change = _worsening_percent(metric, current.get(metric), baseline.get(metric))
        if change is None:
            details.append({'metric': metric, 'rating': 'unrated', 'reason': 'missing value'})
            continue
        rated += 1
        rule = {**DEFAULT_THRESHOLDS[metric], **(thresholds.get(metric) or {})}
        if change >= float(rule['high_percent']):
            rating = 'high'
        elif change >= float(rule['medium_percent']):
            rating = 'medium'
        else:
            rating = 'low'
        if RISK_ORDER[rating] > RISK_ORDER[overall]:
            overall = rating
        details.append({
            'metric': metric,
            'current': current.get(metric),
            'baseline': baseline.get(metric),
            'worsening_percent': None if change == float('inf') else round(change, 3),
            'rating': rating,
            'reason': (
                'new regression from zero baseline'
                if change == float('inf')
                else f'{change:.2f}% relative worsening'
            ),
        })
    if rated == 0:
        overall = 'unrated'
    return {'rating': overall, 'details': details}


def _as_mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def _metric(metrics, *names):
    for name in names:
        if name not in metrics:
            continue
        try:
            value = float(metrics[name])
        except (TypeError, ValueError):
            continue
        if value == value and value not in (float('inf'), float('-inf')):
            return value
    return None


def extract_path_groups(record):
    """Normalize every supported timing payload into path-group observations."""
    record = _as_mapping(record)
    extra = _as_mapping(record.get('extra_fields'))
    observations = []
    seen = set()

    def append(timing_type, scenario, name, metrics):
        metrics = _as_mapping(metrics)
        wns = _metric(metrics, 'WNS', 'wns')
        tns = _metric(metrics, 'TNS', 'tns')
        if wns is None and tns is None:
            return
        key = (str(timing_type or 'default'), str(scenario or ''), str(name))
        if key in seen:
            return
        seen.add(key)
        observations.append({
            'timing_type': key[0],
            'scenario': key[1],
            'path_group': key[2],
            'wns': wns,
            'tns': tns,
        })

    def append_groups(timing_type, scenario, source):
        source = _as_mapping(source)
        groups = _as_mapping(source.get('path_groups')) or source
        for name, metrics in groups.items():
            append(timing_type, scenario, name, metrics)

    timing_sections = (
        _as_mapping(record.get('timing_sections'))
        or _as_mapping(extra.get('timing_sections'))
    )
    for timing_type, scenarios in timing_sections.items():
        for scenario, source in _as_mapping(scenarios).items():
            append_groups(timing_type, scenario, source)
    for scenario, source in _as_mapping(extra.get('scenarios')).items():
        append_groups('default', scenario, source)
    if extra.get('path_groups'):
        append_groups('default', '', extra.get('path_groups'))
    if record.get('path_groups'):
        append_groups('default', '', record.get('path_groups'))

    raw = _as_mapping(record.get('raw_dc_report'))
    for timing_type, section in _as_mapping(raw.get('timing')).items():
        for scenario, source in _as_mapping(_as_mapping(section).get('scenarios')).items():
            append_groups(timing_type, scenario, source)
    return observations


def rate_version(record):
    """Apply the fixed absolute WNS/TNS policy, with high taking priority."""
    groups = [
        group for group in extract_path_groups(record)
        if group['path_group'].strip().upper() not in EXCLUDED_PATH_GROUPS
    ]
    high = [
        group for group in groups
        if (group['wns'] is not None and group['wns'] < -100)
        or (group['tns'] is not None and group['tns'] < -50000)
    ]
    medium = [
        group for group in groups
        if (group['wns'] is not None and group['wns'] < -50)
        or (group['tns'] is not None and group['tns'] < -30000)
    ]
    rating = 'high' if high else 'medium' if medium else 'low'
    triggers = high if high else medium if medium else []
    return {
        'rating': rating,
        'auto_rating': rating,
        'details': [
            {
                **group,
                'rating': rating,
                'reason': (
                    'WNS < -100 or TNS < -50000'
                    if rating == 'high'
                    else 'WNS < -50 or TNS < -30000'
                ),
            }
            for group in triggers
        ],
        'summary': {
            'worst_wns': min(
                (group['wns'] for group in groups if group['wns'] is not None),
                default=None,
            ),
            'worst_tns': min(
                (group['tns'] for group in groups if group['tns'] is not None),
                default=None,
            ),
            'eligible_path_group_count': len(groups),
            'excluded_path_groups': sorted(EXCLUDED_PATH_GROUPS),
        },
    }


def timing_trend(current, baseline):
    """Compare worst eligible WNS/TNS; mixed movement is intentionally neutral."""
    comparable = []
    for key in ('worst_wns', 'worst_tns'):
        current_value = current.get(key)
        baseline_value = baseline.get(key)
        if current_value is not None and baseline_value is not None:
            comparable.append((current_value, baseline_value))
    if not comparable:
        return 'unknown'
    if all(current >= previous for current, previous in comparable):
        return 'unchanged' if all(
            current == previous for current, previous in comparable
        ) else 'better'
    if all(current <= previous for current, previous in comparable):
        return 'worse'
    return 'mixed'


def assess_versions(records, manual_ratings=None):
    """Assess chronological versions and carry the nearest user judgement forward."""
    manual_ratings = {
        str(key): value for key, value in (manual_ratings or {}).items()
        if value in RISK_LEVELS
    }
    ordered = sorted(
        records,
        key=lambda record: (
            str(record.get('recorded_at') or record.get('released_at') or ''),
            str(record.get('id') or ''),
        ),
    )
    results = {}
    anchor = None
    for record in ordered:
        record_id = str(record.get('id'))
        assessed = rate_version(record)
        auto_rating = assessed['auto_rating']
        manual_rating = manual_ratings.get(record_id)
        trend = None
        source = 'automatic'
        effective = auto_rating
        respected_record_id = None
        if manual_rating:
            effective = manual_rating
            source = 'manual'
            anchor = {
                'record_id': record_id,
                'rating': manual_rating,
                'summary': assessed['summary'],
            }
        elif anchor:
            trend = timing_trend(assessed['summary'], anchor['summary'])
            respected_record_id = anchor['record_id']
            if trend == 'better':
                effective = min(
                    auto_rating, anchor['rating'], key=lambda value: RISK_ORDER[value],
                )
            elif trend == 'worse':
                effective = max(
                    auto_rating, anchor['rating'], key=lambda value: RISK_ORDER[value],
                )
            elif trend == 'unchanged':
                effective = anchor['rating']
            if effective != auto_rating or trend == 'unchanged':
                source = 'user_guardrail'
        assessed.update({
            'rating': effective,
            'manual_rating': manual_rating,
            'source': source,
            'trend_from_user_judgement': trend,
            'respected_record_id': respected_record_id,
        })
        results[record_id] = assessed
    return results
