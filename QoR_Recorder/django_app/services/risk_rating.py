"""Deterministic weekly QoR risk ratings."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


RISK_ORDER = {'unrated': -1, 'low': 0, 'medium': 1, 'high': 2}
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
