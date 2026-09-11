"""Shared CSV legacy-field aliases for web upload and CLI conversion.

Django-free so ``scripts/csv_to_json.py`` can import it without ORM setup.
``normalize_csv_record`` and the JSON converter must use this dict, not copies.
"""
from __future__ import annotations

from typing import Any

CSV_FIELD_ALIASES = {
    # Legacy DC/demo exports. These mappings are semantic equivalents, not
    # fuzzy guesses.
    'total_area': 'area_total',
    'comb_area': 'area_combinational',
    'reg_area': 'area_sequential',
    'macro_area': 'area_macro',
    'total_count': 'instance_count',
    'reg_count': 'register_count',
    'macro_count': 'macro_cell_count',
}

CSV_STANDARD_FIELDS = {
    'module_name', 'version', 'tag', 'full_dir', 'release_dir', 'comment',
    'version_description', 'area_total', 'area_combinational',
    'area_sequential', 'area_black_box', 'area_macro', 'wns_setup',
    'tns_setup', 'nvp_setup', 'wns_hold', 'tns_hold', 'nvp_hold',
    'power_internal', 'power_switching', 'power_leakage', 'power_total',
    'target_frequency', 'achieved_frequency', 'cell_count', 'instance_count',
    'net_count', 'sequential_cell_count', 'ram_cell_count',
    'macro_cell_count', 'register_count', 'mbb_ratio',
    'clock_gating_ratio', 'utilization', 'congestion', 'congestion_h',
    'congestion_v', 'congestion_b',
}

STDCELL_AREA_KEY = 'stdcell_area'


def canonical_csv_field(key: str) -> str:
    """Map a stripped, lowercased CSV header to its import field name."""
    return CSV_FIELD_ALIASES.get(key, key)


def reconstruct_area_total(area_total: Any, stdcell_area: Any, macro_area: Any):
    """If total area is missing, rebuild it from stdcell_area + macro_area.

    ``stdcell_area`` has no dedicated model/dashboard column. Its semantic
    value is area_total - area_macro.
    """
    if area_total:
        return None
    try:
        return float(stdcell_area) + float(macro_area)
    except (TypeError, ValueError):
        return None
