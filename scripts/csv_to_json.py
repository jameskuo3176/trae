#!/usr/bin/env python3
"""csv_to_json.py - CSV §3 (qor 宽表) → JSON §6.5 转换器

用法:
  python scripts/csv_to_json.py qor.csv --project-id 1 --version v1.0 \\
      --full-dir /scratch/runs/v1.0 --release-dir v1.0/main/cpu \\
      -o run.json

支持:
- qor 宽表 (§3): 面积/时序/功耗/拥塞/多 clock 列自动识别
- power 简洁表 (§4): 自动识别 (无 area/timing 列时)
- violation paths (§5): 每行一条, --timing-group 必填
- notes (§6): 2 列 (item, description) 或 3 列 (+ full_dir)

向后兼容:
- 列名大小写/空格/下划线不敏感
- 0-1 / 0-100 比例字段自动归一
- 多 clock 列 (如 SRAMCLK_wns) 自动重组成 clocks 对象
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

CLOCK_PATTERN_RE = re.compile(
    r"^(.+?)_(hold_wns|hold_tns|hold_path|period|wns|tns|path)$",
    re.IGNORECASE,
)

# 数值范围字段定义 (与 save_records_to_db NUMERIC_RANGES 保持一致)
NUMERIC_FIELDS = {
    # area
    "area_total", "area_combinational", "area_sequential",
    "area_black_box", "area_macro",
    # timing
    "wns_setup", "tns_setup", "wns_hold", "tns_hold",
    # power
    "power_internal", "power_switching", "power_leakage", "power_total",
    # frequency
    "target_frequency", "achieved_frequency",
    # ratios (特殊: 0-1 或 0-100)
    "mbb_ratio", "clock_gating_ratio", "utilization",
    "congestion_h", "congestion_v", "congestion_b", "congestion",
}

INT_FIELDS = {
    "cell_count", "instance_count", "net_count", "sequential_cell_count",
    "nvp_setup", "nvp_hold",
}

RATIO_FIELDS = {"mbb_ratio", "clock_gating_ratio", "utilization"}

CONGESTION_FIELDS = {"congestion_h", "congestion_v", "congestion_b", "congestion"}


def _norm_key(k: str) -> str:
    return k.strip().lower().replace(" ", "_").replace("-", "_")


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (ValueError, TypeError):
        return None


def _to_int(v: Any) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


def _normalize_ratio(f: float) -> float:
    """0-1 ↔ 0-100 归一为 0-1"""
    return f / 100.0 if f > 1.0 else f


def _detect_data_type(rows: list[dict]) -> str:
    """根据列名判断 CSV 类型"""
    if not rows:
        return "qor"
    keys = {_norm_key(k) for k in rows[0].keys()}
    if "startpoint" in keys or "endpoint" in keys or "slack" in keys:
        return "violation"
    if "item" in keys or "description" in keys:
        return "notes"
    if keys & {"power_internal", "power_total"} and not (keys & {"area_total", "wns_setup"}):
        return "power"
    return "qor"


def _csv_to_qor_json(rows: list[dict], project_id: int, version: str,
                     full_dir: str | None, release_dir: str | None,
                     uploader_note: str | None) -> dict:
    records = []
    for row in rows:
        rec: dict = {
            "module_name": None,
            "comment":    row.get("comment") or None,
            "source_file": None,
            "area":       {},
            "timing":     {"setup": {}, "hold": {}},
            "power":      {},
            "cells":      {},
            "frequency":  {},
            "ratios":     {},
            "congestion": {},
            "clocks":     {},
            "extra":      {},
        }
        for raw_k, raw_v in row.items():
            if raw_v is None or raw_v == "":
                continue
            k = _norm_key(raw_k)
            v = raw_v

            if k == "module_name":
                rec["module_name"] = str(v).strip()
                continue
            if k == "full_dir" and full_dir is None:
                rec["full_dir"] = str(v)
                continue
            if k == "release_dir" and release_dir is None:
                rec["release_dir"] = str(v)
                continue
            if k == "tag":
                rec["extra"]["tag"] = v
                continue
            if k == "source_file":
                rec["source_file"] = str(v)
                continue

            # 多 clock 列 (保留原始大小写)
            m = CLOCK_PATTERN_RE.match(k)
            if m:
                # 从原始 raw_k 中切出 clock 名 (保留大小写)
                suf_lower = m.group(2).lower()
                # 找到 raw_k 中后缀 (case-insensitive) 的起始位置
                idx = raw_k.lower().rfind("_" + suf_lower)
                clock_name = raw_k[:idx] if idx > 0 else m.group(1)
                rec["clocks"].setdefault(clock_name, {})[suf_lower] = v if suf_lower == "path" else _to_float(v)
                continue

            # area
            if k.startswith("area_"):
                f = _to_float(v)
                if f is not None:
                    rec["area"][k[5:]] = f
                continue
            # timing
            if k in {"wns_setup", "tns_setup", "nvp_setup"}:
                rec["timing"]["setup"][k[:-6]] = _to_int(v) if k.startswith("nvp_") else _to_float(v)
                continue
            if k in {"wns_hold", "tns_hold", "nvp_hold"}:
                rec["timing"]["hold"][k[:-5]] = _to_int(v) if k.startswith("nvp_") else _to_float(v)
                continue
            # power
            if k.startswith("power_"):
                f = _to_float(v)
                if f is not None:
                    rec["power"][k[6:]] = f
                continue
            # cells
            if k in INT_FIELDS:
                f = _to_int(v)
                if f is not None:
                    rec["cells"][k] = f
                continue
            # frequency
            if k in {"target_frequency", "achieved_frequency"}:
                f = _to_float(v)
                if f is not None:
                    rec["frequency"][k] = f
                continue
            # ratios
            if k in RATIO_FIELDS:
                f = _to_float(v)
                if f is not None:
                    rec["ratios"][k] = _normalize_ratio(f)
                continue
            # congestion
            if k in CONGESTION_FIELDS:
                f = _to_float(v)
                if f is not None:
                    if k == "congestion":
                        rec["congestion"]["max"] = _normalize_ratio(f)
                    else:
                        rec["congestion"][k[11:]] = _normalize_ratio(f)
                continue
            # 未知字段 → extra
            rec["extra"][raw_k] = v

        # 清理空对象
        for k in ("area", "power", "cells", "frequency", "ratios", "congestion", "clocks", "extra"):
            if not rec[k]:
                del rec[k]
        if not rec["timing"]["setup"]:
            del rec["timing"]["setup"]
        if not rec["timing"]["hold"]:
            del rec["timing"]["hold"]
        if not rec["timing"]:
            del rec["timing"]
        if full_dir and "full_dir" not in rec:
            rec["full_dir"] = full_dir
        if release_dir and "release_dir" not in rec:
            rec["release_dir"] = release_dir
        records.append(rec)

    return {
        "schema_version": "1.0",
        "upload": {
            "project_id":    project_id,
            "version":       version,
            "full_dir":      full_dir,
            "release_dir":   release_dir,
            "uploader_note": uploader_note,
        },
        "records": records,
    }


def _csv_to_violation_json(rows: list[dict], project_id: int, version: str,
                            timing_group: str, default_type: str = "setup") -> dict:
    paths = []
    for row in rows:
        keys = {_norm_key(k): k for k in row.keys()}
        paths.append({
            "module_name":   row.get("module_name", "").strip(),
            "timing_group":  timing_group,
            "type":          row.get(keys.get("type", ""), default_type) if "type" in keys else default_type,
            "slack":         _to_float(row.get("slack") or row.get(keys.get("slack", ""))),
            "startpoint":    row.get("startpoint") or row.get(keys.get("startpoint", "")),
            "endpoint":      row.get("endpoint")   or row.get(keys.get("endpoint", "")),
            "depth":         _to_int(row.get("depth") or row.get(keys.get("depth", ""))),
            "pure_depth":    _to_int(row.get("pure_depth") or row.get(keys.get("pure_depth", ""))),
            "cell_delay":    _to_float(row.get("cell_delay") or row.get(keys.get("cell_delay", ""))),
            "net_delay":     _to_float(row.get("net_delay") or row.get(keys.get("net_delay", ""))),
            "et_slack":      _to_float(row.get("et_slack") or row.get(keys.get("et_slack", ""))),
            "st_slack":      _to_float(row.get("st_slack") or row.get(keys.get("st_slack", ""))),
            "st_fanin":      _to_int(row.get("st_fanin") or row.get(keys.get("st_fanin", ""))),
            "st_fanout":     _to_int(row.get("st_fanout") or row.get(keys.get("st_fanout", ""))),
            "et_fanin":      _to_int(row.get("et_fanin") or row.get(keys.get("et_fanin", ""))),
            "et_fanout":     _to_int(row.get("et_fanout") or row.get(keys.get("et_fanout", ""))),
        })
    return {
        "schema_version":  "1.0",
        "upload": {"project_id": project_id, "version": version},
        "records": [],  # 违例通常配合 QoR 记录, 此处可后续合并
        "violation_paths": paths,
    }


def _csv_to_notes_json(rows: list[dict], project_id: int, version: str,
                        default_module: str, full_dir: str | None) -> dict:
    items = []
    for row in rows:
        item = (row.get("item") or "").strip()
        if not item:
            continue
        items.append({
            "item":     item,
            "value":    (row.get("description") or row.get("value") or "").strip(),
            "category": row.get("category", ""),
            "unit":     row.get("unit", ""),
        })
    return {
        "schema_version": "1.0",
        "upload": {"project_id": project_id, "version": version, "full_dir": full_dir},
        "records": [],
        "notes": [{
            "module_name": default_module,
            "full_dir":    full_dir,
            "items":       items,
        }],
    }


def csv_to_json(csv_path: Path, project_id: int, version: str,
                full_dir: str | None = None,
                release_dir: str | None = None,
                timing_group: str | None = None,
                module_name: str | None = None,
                uploader_note: str | None = None,
                data_type: str | None = None) -> dict:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"CSV 文件 {csv_path} 为空")

    detected = data_type or _detect_data_type(rows)
    if detected == "violation":
        if not timing_group:
            # 从文件名提取 timing_group
            stem = csv_path.stem
            timing_group = re.sub(r"_violations?$", "", stem, flags=re.IGNORECASE)
        return _csv_to_violation_json(rows, project_id, version, timing_group)
    elif detected == "notes":
        if not module_name:
            raise ValueError("notes CSV 必须通过 --module-name 指定模块")
        return _csv_to_notes_json(rows, project_id, version, module_name, full_dir)
    else:
        return _csv_to_qor_json(rows, project_id, version,
                                full_dir, release_dir, uploader_note)


def main() -> int:
    p = argparse.ArgumentParser(description="CSV §3-§6 → JSON §6.5 转换器")
    p.add_argument("csv", type=Path, help="输入 CSV 文件")
    p.add_argument("--project-id", type=int, required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--full-dir", help="Run 工作目录")
    p.add_argument("--release-dir", help="发布目录 (v5.0)")
    p.add_argument("--module-name", help="notes CSV 用, 关联模块")
    p.add_argument("--timing-group", help="violation CSV 用, 缺省从文件名提取")
    p.add_argument("--uploader-note", help="上传备注")
    p.add_argument("--data-type", choices=["qor", "power", "violation", "notes"],
                   help="强制指定类型 (默认自动检测)")
    p.add_argument("--output", "-o", default="-", help="输出文件路径, 缺省 stdout")
    args = p.parse_args()

    try:
        data = csv_to_json(
            args.csv, args.project_id, args.version,
            full_dir=args.full_dir, release_dir=args.release_dir,
            timing_group=args.timing_group, module_name=args.module_name,
            uploader_note=args.uploader_note, data_type=args.data_type,
        )
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    if args.output == "-":
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"[OK] 已写入 {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
