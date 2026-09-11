"""Pure helpers for parsing dynamic path-group columns in wide CSV files."""
from __future__ import annotations

import math
import re
from typing import Any, Mapping


PATH_GROUP_COLUMN_RE = re.compile(
    r"^(?P<group>.+?)_"
    r"(?P<metric>hold_wns|hold_tns|hold_path|period|path|wns|tns)$",
    re.IGNORECASE,
)

_CANONICAL_METRICS = {
    "period": "period",
    "path": "nvp",
    "wns": "wns",
    "tns": "tns",
    "hold_wns": "hold_wns",
    "hold_tns": "hold_tns",
    "hold_path": "hold_nvp",
}


def _finite_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int | None:
    number = _finite_float(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def split_path_group_column(column: Any) -> tuple[str, str] | None:
    """Split a column at its final supported suffix.

    Full-match suffix detection preserves underscores in names such as
    ``CPU_SYS_CLK_wns`` and prefers the legacy compound ``hold_*`` suffixes.
    """
    name = str(column).strip()
    match = PATH_GROUP_COLUMN_RE.fullmatch(name)
    if not match:
        return None
    group = match.group("group").strip()
    if not group:
        return None
    return group, match.group("metric").lower()


def canonical_path_group_metric(source_metric: str) -> str:
    """Map a supported CSV suffix to its canonical metric name."""
    return _CANONICAL_METRICS[source_metric.lower()]


def parse_dynamic_path_groups(
    row: Mapping[Any, Any],
) -> tuple[dict[str, dict[str, float | int]], set[Any]]:
    """Return canonical path groups and all recognized source columns.

    Invalid or empty metric values are omitted, while their columns remain
    recognized so callers can retain the original values for audit if needed.
    """
    groups: dict[str, dict[str, float | int]] = {}
    recognized: set[Any] = set()
    for column, raw_value in row.items():
        parsed = split_path_group_column(column)
        if not parsed:
            continue
        recognized.add(column)
        group, source_metric = parsed
        metric = canonical_path_group_metric(source_metric)
        value = (
            _nonnegative_int(raw_value)
            if metric in {"nvp", "hold_nvp"}
            else _finite_float(raw_value)
        )
        if value is not None:
            groups.setdefault(group, {})[metric] = value
    return groups, recognized


def aggregate_setup_timing(
    groups: Mapping[str, Mapping[str, Any]],
) -> dict[str, float | int]:
    """Aggregate path groups using the established DC-report setup rules."""
    wns_values = [
        value
        for metrics in groups.values()
        if (value := _finite_float(metrics.get("wns"))) is not None
    ]
    tns_values = [
        value
        for metrics in groups.values()
        if (value := _finite_float(metrics.get("tns"))) is not None
    ]
    nvp_values = [
        value
        for metrics in groups.values()
        if (value := _nonnegative_int(metrics.get("nvp"))) is not None
    ]

    setup: dict[str, float | int] = {}
    if wns_values:
        setup["wns"] = min(wns_values)
    if tns_values:
        setup["tns"] = sum(value for value in tns_values if value < 0)
    if nvp_values:
        setup["nvp"] = sum(nvp_values)
    return setup


def build_timing_sections(
    groups: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
    """Build the canonical analysis/scenario/path-group hierarchy."""
    return {"default": {"default": dict(groups)}} if groups else {}
