#!/usr/bin/env python3
"""Standalone QoR workstation uploader (Python 3.8+, standard library only).

Copy this file and, optionally, ``qor_upload.env`` to a workstation.  It
uploads CSV through the legacy multipart endpoint and JSON through §6.5,
including native DC-report and CSV-to-JSON conversion without repository
modules, curl, Bash, requests, or locale-dependent subprocesses.
"""
from __future__ import annotations

import argparse
import csv
import http.client
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import ssl
import sys
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
from urllib.parse import quote, urlsplit


EXIT_USAGE = 1
EXIT_HTTP = 2
EXIT_CONVERSION = 3
SCHEMA_VERSION = "1.0"


class ClientError(Exception):
    """A user-actionable client error."""


class TransportError(ClientError):
    """A network/TLS/HTTP transport failure."""


def _safe_print(*values: object, file=None) -> None:
    """Print even when a legacy Windows console cannot encode the message."""
    if file is None:
        file = sys.stdout
    text = " ".join(str(value) for value in values)
    encoding = getattr(file, "encoding", None) or "utf-8"
    data = (text + "\n").encode(encoding, "backslashreplace")
    buffer = getattr(file, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:  # StringIO and test doubles
        file.write(data.decode(encoding, "replace"))


def load_env_file(path: Path) -> Dict[str, str]:
    """Parse KEY=VALUE without executing shell syntax."""
    result: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ClientError("无法读取配置文件 {}: {}".format(path, exc))
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ClientError("配置文件 {} 第 {} 行不是 KEY=VALUE".format(path, number))
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ClientError("配置文件 {} 第 {} 行变量名无效".format(path, number))
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        result[key] = value
    return result


def discover_config(explicit: Optional[str], environ: Mapping[str, str],
                    script_dir: Path) -> Optional[Path]:
    """Return the first configured env file, matching the shell client order."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ClientError("找不到 --env 文件: {}".format(path))
        return path
    configured = environ.get("QOR_UPLOAD_ENV")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise ClientError("QOR_UPLOAD_ENV 指向的文件不存在: {}".format(path))
        return path
    candidates = (
        script_dir / "qor_upload.env",
        Path.home() / ".qor_upload.env",
        Path.home() / ".config" / "qor-recorder" / "upload.env",
    )
    return next((path for path in candidates if path.is_file()), None)


def resolve_settings(args: argparse.Namespace, environ: Mapping[str, str],
                     script_dir: Path) -> Tuple[str, str, Dict[str, str]]:
    """Resolve CLI > process environment > env-file values."""
    config_path = discover_config(args.env_file, environ, script_dir)
    config = load_env_file(config_path) if config_path else {}
    server = args.server or environ.get("QOR_SERVER") or config.get("QOR_SERVER")
    key = environ.get("QOR_API_KEY") or config.get("QOR_API_KEY")
    if not server:
        raise ClientError("未设置 QOR_SERVER（--server、环境变量或 qor_upload.env）")
    if not key:
        raise ClientError("未设置 QOR_API_KEY（环境变量或 qor_upload.env）")
    if config_path:
        _safe_print("[INFO] 已加载配置:", config_path)
    return server.rstrip("/"), key, config


def is_json_input(path: Path) -> bool:
    if path.suffix.lower() == ".json":
        return True
    with path.open("rb") as handle:
        prefix = handle.read(4096)
    return prefix.decode("utf-8-sig", "ignore").lstrip().startswith("{")


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClientError("无法读取 JSON {}: {}".format(path, exc))
    if not isinstance(value, dict):
        raise ClientError("JSON 根节点必须是对象")
    return value


def is_dc_report(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    schema = data.get("schema_version", data.get("scheme_version"))
    return (
        ("top_module" in data and ("timing" in data or "area" in data))
        or isinstance(schema, int)
    )


def _float(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _int(value: Any) -> Optional[int]:
    number = _float(value)
    return int(number) if number is not None else None


def _metric(values: Mapping[str, Any], *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in values.items()}
    for name in names:
        if name in values:
            return values[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _mapping(container: Any, key: str) -> dict:
    value = container.get(key) if isinstance(container, dict) else None
    return value if isinstance(value, dict) else {}


def _path_alias(container: Mapping[str, Any], label: str) -> str:
    values: Dict[str, str] = {}
    for key in ("full_dir", "directory"):
        value = container.get(key)
        if value is not None and not isinstance(value, str):
            raise ClientError("{}.{} 必须是字符串".format(label, key))
        values[key] = value.strip() if isinstance(value, str) else ""
    if values["full_dir"] and values["directory"] and values["full_dir"] != values["directory"]:
        raise ClientError("{}.full_dir conflicts with {}.directory".format(label, label))
    return values["full_dir"] or values["directory"]


def validate_dc_report(data: dict) -> None:
    schema = data.get("schema_version", data.get("scheme_version"))
    if not isinstance(schema, int):
        raise ClientError("$.schema_version: schema_version/scheme_version 必须是整数")
    if not isinstance(data.get("top_module"), str) or not data["top_module"]:
        raise ClientError("$.top_module: 必填字符串")
    run = data.get("run")
    if not isinstance(run, dict) or not _path_alias(run, "run"):
        raise ClientError("$.run.full_dir: run.full_dir/run.directory 必填")
    timing = data.get("timing")
    default = timing.get("default") if isinstance(timing, dict) else None
    if not isinstance(default, dict):
        raise ClientError("$.timing.default: 必填对象")
    scenarios = default.get("scenarios")
    empty = str(default.get("status", "")).strip().lower() == "empty"
    if (not isinstance(scenarios, dict) or not scenarios) and not empty:
        raise ClientError("$.timing.default.scenarios: 必填非空对象")


def _dc_area(data: dict) -> dict:
    area = _mapping(_mapping(_mapping(data, "area"), "tile"), "area")
    result: Dict[str, float] = {}
    aliases = (
        ("total", "total"), ("combinational", "combinational"),
        ("sequential", "sequential"), ("memory", "memory"), ("macro", "macro"),
    )
    for source, target in aliases:
        value = _float(area.get(source))
        if value is not None:
            result[target] = value
    # Native DC: non_combinational → Sequential area (never combinational).
    if "sequential" not in result:
        value = _float(area.get("non_combinational"))
        if value is not None:
            result["sequential"] = value
    if "memory" in result:
        result["black_box"] = result["memory"]
    return result


def _dc_cells(data: dict) -> dict:
    tile = _mapping(_mapping(data, "area"), "tile")
    count = _mapping(tile, "cell_count")
    flop = _mapping(_mapping(data, "misc"), "flop_count")
    result: Dict[str, int] = {}
    aliases = (
        ("total", "cell_count"), ("sequential", "sequential_cell_count"),
        ("combinational", "instance_count"), ("ram", "ram_cell_count"),
        ("macro", "macro_cell_count"),
    )
    for source, target in aliases:
        value = _int(count.get(source))
        if value is not None:
            result[target] = value
    value = _int(flop.get("total_sequential_cells"))
    if value is not None:
        result["sequential_cell_count"] = value
    return result


def _ratio(value: Any) -> Optional[float]:
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip()
    number = _float(value)
    if number is None:
        return None
    return number / 100.0 if number > 1 else number


def convert_dc_to_qor_record(
    data: dict, project_id: Optional[int] = None, version: Optional[str] = None,
    module_name_override: Optional[str] = None,
    full_dir_override: Optional[str] = None,
    release_dir_override: Optional[str] = None, mark_released: bool = False,
) -> dict:
    """Convert one native DC report without changing native timing units."""
    validate_dc_report(data)
    top = module_name_override or data["top_module"]
    run_dir = (full_dir_override or "").strip() or _path_alias(data["run"], "run")
    timing = _mapping(data, "timing")
    default = _mapping(timing, "default")
    scenarios = default.get("scenarios")
    scenarios = scenarios if isinstance(scenarios, dict) else {}
    all_wns, all_tns, all_nvp = [], [], []
    clocks: Dict[str, dict] = {}
    audit: Dict[str, dict] = {}
    sections: Dict[str, dict] = {}
    first_scenario: Optional[str] = None

    for section_name, section in timing.items():
        section_scenarios = section.get("scenarios") if isinstance(section, dict) else None
        if not isinstance(section_scenarios, dict):
            continue
        normalized: Dict[str, dict] = {}
        for scenario_name, scenario in section_scenarios.items():
            groups = scenario.get("path_groups") if isinstance(scenario, dict) else None
            if not isinstance(groups, dict):
                continue
            normalized[scenario_name] = {}
            for group_name, raw in groups.items():
                if not isinstance(raw, dict):
                    continue
                entry: Dict[str, Any] = {}
                for target, aliases, converter in (
                    ("wns", ("WNS",), _float), ("tns", ("TNS",), _float),
                    ("nvp", ("NVP",), _int),
                    ("period", ("Clk_Period", "period"), _float),
                    ("lol", ("LoL", "LOL"), _int),
                ):
                    value = converter(_metric(raw, *aliases))
                    if value is not None:
                        entry[target] = value
                if raw.get("warnings"):
                    entry["warnings"] = raw["warnings"]
                normalized[scenario_name][group_name] = entry
        if normalized:
            sections[section_name] = normalized

    for scenario_name, scenario in scenarios.items():
        groups = scenario.get("path_groups") if isinstance(scenario, dict) else None
        if not isinstance(groups, dict):
            continue
        audit[scenario_name] = sections.get("default", {}).get(scenario_name, {})
        if first_scenario is None:
            first_scenario = scenario_name
        for group_name, entry in audit[scenario_name].items():
            wns, tns, nvp = entry.get("wns"), entry.get("tns"), entry.get("nvp")
            if wns is not None:
                all_wns.append(wns)
            if tns is not None:
                all_tns.append(tns)
            if nvp is not None:
                all_nvp.append(nvp)
            if scenario_name == first_scenario:
                clocks[group_name] = {
                    key: entry[key] for key in ("period", "wns", "tns", "nvp")
                    if key in entry
                }

    record: Dict[str, Any] = {"module_name": top}
    if version:
        record["version"] = version
    record["full_dir"] = run_dir
    record["release_dir"] = release_dir_override or run_dir
    area, cells = _dc_area(data), _dc_cells(data)
    if area:
        record["area"] = area
    if cells:
        record["cells"] = cells
    misc = _mapping(data, "misc")
    fgcg = _mapping(misc, "fgcg")
    register_count = _int(fgcg.get("total_flops"))
    if register_count is not None:
        record["register_count"] = register_count
        if cells:
            cells["register_count"] = register_count
        else:
            record["cells"] = {"register_count": register_count}
            cells = record["cells"]
    ratios = {}
    for source, target in (("utilization", "utilization"), ("mbb_ratio", "mbb_ratio")):
        value = _ratio(misc.get(source))
        if value is not None:
            ratios[target] = value
    gated = _ratio(_mapping(fgcg, "gated_flops").get("percentage"))
    if gated is not None:
        ratios["clock_gating_ratio"] = gated
    if ratios:
        record["ratios"] = ratios
    congestion_source = _mapping(misc, "congestion")
    congestion: Dict[str, float] = {}
    both = _ratio(congestion_source.get("both_dirs_percentage"))
    if both is not None:
        congestion["max"] = both
    for line in congestion_source.get("summary_lines", []):
        if not isinstance(line, str):
            continue
        match = re.search(
            r"^\s*([HV])\s+routing:.*?GRCs\s*=\s*\d+\s*\(([\d.]+)%\)",
            line,
        )
        if match:
            value = _ratio(match.group(2))
            if value is not None:
                congestion[match.group(1).lower()] = value
    if congestion:
        record["congestion"] = congestion
    setup: Dict[str, Any] = {}
    if all_wns:
        setup["wns"] = min(all_wns)
    if all_tns:
        setup["tns"] = sum(value for value in all_tns if value < 0)
    if all_nvp:
        setup["nvp"] = sum(all_nvp)
    if setup:
        record["timing"] = {"setup": setup}
    if clocks:
        record["clocks"] = clocks
    extra: Dict[str, Any] = {
        "default_path": default.get("source"),
        "dc_full_dir": run_dir,
        "timing_group_count": len(audit),
        "path_group_count": sum(len(groups) for groups in audit.values()),
    }
    if sections:
        extra["timing_sections"] = sections
    if audit:
        extra["scenarios"] = audit
    if all_wns:
        extra["aggregate_wns_min"] = min(all_wns)
    if all_tns:
        extra["aggregate_tns_negative_sum"] = sum(value for value in all_tns if value < 0)
    if all_nvp:
        extra["aggregate_nvp_sum"] = sum(all_nvp)
    for key in ("stage", "generated_at", "errors"):
        if data.get(key):
            extra[key] = data[key]
    metadata = default.get("metadata")
    if isinstance(metadata, dict):
        for key in ("report", "design", "version", "date"):
            if metadata.get(key):
                extra["dc_metadata_" + key] = metadata[key]
    final = _mapping(timing, "final")
    if final:
        final_summary: Dict[str, Any] = {
            "status": final.get("status"),
            "source": final.get("source"),
        }
        final_metadata = final.get("metadata")
        if isinstance(final_metadata, dict):
            final_summary["metadata"] = {
                key: value for key, value in final_metadata.items()
                if "scenario" not in str(key).lower()
            }
        scenario_summary = {}
        for scenario_name, groups in sections.get("final", {}).items():
            wns = [entry["wns"] for entry in groups.values() if "wns" in entry]
            tns = [entry["tns"] for entry in groups.values() if "tns" in entry]
            nvp = [entry["nvp"] for entry in groups.values() if "nvp" in entry]
            scenario_summary[scenario_name] = {
                "wns_worst": min(wns) if wns else None,
                "tns_total": sum(value for value in tns if value < 0) if tns else None,
                "nvp_total": sum(nvp) if nvp else None,
            }
        if scenario_summary:
            final_summary["scenarios"] = scenario_summary
        extra["timing_final"] = final_summary
    for key in ("fgcg", "vt_ratio", "flop_count", "congestion", "no_clock", "warnings"):
        if misc.get(key):
            extra["misc_" + key] = misc[key]
    block = _mapping(_mapping(data, "area"), "block")
    if block:
        extra["blocks"] = block
    record["extra"] = extra
    upload: Dict[str, Any] = {
        "module_name": top, "full_dir": run_dir,
        "release_dir": release_dir_override or run_dir,
    }
    if project_id is not None:
        upload["project_id"] = int(project_id)
    if version:
        upload["version"] = version
    if mark_released:
        upload["mark_released"] = True
    return {
        "schema_version": SCHEMA_VERSION,
        "upload": upload,
        "records": [record],
        "_raw_dc_report": data,
    }


CSV_ALIASES = {
    "total_area": "area_total", "comb_area": "area_combinational",
    "reg_area": "area_sequential", "macro_area": "area_macro",
    "total_count": "instance_count", "reg_count": "register_count",
    "macro_count": "macro_cell_count",
}
INT_FIELDS = {
    "cell_count", "instance_count", "net_count", "sequential_cell_count",
    "ram_cell_count", "macro_cell_count", "register_count",
}
RATIO_FIELDS = {"mbb_ratio", "clock_gating_ratio", "utilization"}
PATH_GROUP_RE = re.compile(
    r"^(?P<group>.+?)_(?P<metric>hold_wns|hold_tns|hold_path|period|path|wns|tns)$",
    re.I,
)


def _norm(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def _module_from_filename(path: Path) -> Optional[str]:
    stem = path.stem.strip()
    lowered = stem.casefold()
    for suffix in ("_qor_report", "_qor", "qor"):
        if lowered.endswith(suffix):
            stem = stem[:-len(suffix)].rstrip("._- ")
            break
    return stem or None


def _parse_path_groups(row: Mapping[str, Any]) -> Tuple[Dict[str, dict], set]:
    groups: Dict[str, dict] = {}
    recognized = set()
    aliases = {
        "period": "period", "path": "nvp", "wns": "wns", "tns": "tns",
        "hold_wns": "hold_wns", "hold_tns": "hold_tns", "hold_path": "hold_nvp",
    }
    for column, raw in row.items():
        match = PATH_GROUP_RE.fullmatch(str(column).strip())
        if not match:
            continue
        recognized.add(column)
        metric = aliases[match.group("metric").lower()]
        value = _int(raw) if metric in ("nvp", "hold_nvp") else _float(raw)
        if value is not None and (metric not in ("nvp", "hold_nvp") or value >= 0):
            groups.setdefault(match.group("group").strip(), {})[metric] = value
    return groups, recognized


def csv_to_json(path: Path, project_id: int, version: str, full_dir: str,
                release_dir: Optional[str] = None,
                module_name: Optional[str] = None) -> dict:
    """Convert the QoR CSV mode used by the shell client to §6.5."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ClientError("CSV 解析失败: {}".format(exc))
    if not rows:
        raise ClientError("CSV 文件为空: {}".format(path))
    records = []
    for row in rows:
        groups, group_columns = _parse_path_groups(row)
        record: Dict[str, Any] = {
            "module_name": module_name or _module_from_filename(path),
            "area": {}, "timing": {"setup": {}, "hold": {}}, "power": {},
            "cells": {}, "frequency": {}, "ratios": {}, "congestion": {},
            "clocks": {name: dict(values) for name, values in groups.items()},
            "extra": {},
        }
        if groups:
            record["extra"]["timing_sections"] = {"default": {"default": groups}}
            record["extra"]["path_groups"] = groups
        for raw_key, raw_value in row.items():
            if raw_value in (None, ""):
                continue
            normalized = _norm(raw_key)
            key = CSV_ALIASES.get(normalized, normalized)
            if key == "module_name":
                record["module_name"] = str(raw_value).strip()
            elif key == "full_dir":
                record.setdefault("full_dir", str(raw_value))
            elif key == "release_dir":
                record.setdefault("release_dir", str(raw_value))
            elif key == "tag":
                record["extra"]["tag"] = raw_value
            elif raw_key in group_columns:
                continue
            elif key.startswith("area_"):
                value = _float(raw_value)
                if value is not None:
                    record["area"][key[5:]] = value
            elif key in ("wns_setup", "tns_setup", "nvp_setup"):
                converter = _int if key.startswith("nvp_") else _float
                value = converter(raw_value)
                if value is not None:
                    record["timing"]["setup"][key[:-6]] = value
            elif key in ("wns_hold", "tns_hold", "nvp_hold"):
                converter = _int if key.startswith("nvp_") else _float
                value = converter(raw_value)
                if value is not None:
                    record["timing"]["hold"][key[:-5]] = value
            elif key.startswith("power_"):
                value = _float(raw_value)
                if value is not None:
                    record["power"][key[6:]] = value
            elif key in INT_FIELDS:
                value = _int(raw_value)
                if value is not None:
                    record["cells"][key] = value
            elif key in ("target_frequency", "achieved_frequency"):
                value = _float(raw_value)
                if value is not None:
                    record["frequency"][key] = value
            elif key in RATIO_FIELDS:
                value = _ratio(raw_value)
                if value is not None:
                    record["ratios"][key] = value
            elif key.startswith("congestion"):
                value = _ratio(raw_value)
                if value is not None:
                    record["congestion"]["max" if key == "congestion" else key[11:]] = value
            elif key == "stdcell_area":
                value = _float(raw_value)
                if value is not None:
                    record["extra"][key] = value
            else:
                record["extra"][raw_key] = raw_value
        if "total" not in record["area"]:
            stdcell = _float(record["extra"].get("stdcell_area"))
            macro = _float(record["area"].get("macro"))
            if stdcell is not None and macro is not None:
                record["area"]["total"] = stdcell + macro
        if groups:
            wns = [v["wns"] for v in groups.values() if "wns" in v]
            tns = [v["tns"] for v in groups.values() if "tns" in v]
            nvp = [v["nvp"] for v in groups.values() if "nvp" in v]
            if wns:
                record["timing"]["setup"].setdefault("wns", min(wns))
            if tns:
                record["timing"]["setup"].setdefault(
                    "tns", sum(value for value in tns if value < 0)
                )
            if nvp:
                record["timing"]["setup"].setdefault("nvp", sum(nvp))
        record.setdefault("full_dir", full_dir)
        if release_dir:
            record.setdefault("release_dir", release_dir)
        for key in ("area", "power", "cells", "frequency", "ratios",
                    "congestion", "clocks", "extra"):
            if not record[key]:
                del record[key]
        for section in ("setup", "hold"):
            if not record["timing"][section]:
                del record["timing"][section]
        if not record["timing"]:
            del record["timing"]
        records.append(record)
    return {
        "schema_version": SCHEMA_VERSION,
        "upload": {
            "project_id": project_id, "version": version,
            "full_dir": full_dir, "release_dir": release_dir,
        },
        "records": records,
    }


def inject_upload_fields(data: dict, project_id: int, version: str,
                         module_id: Optional[int], full_dir: Optional[str],
                         release_dir: Optional[str], released: bool) -> dict:
    upload = data.setdefault("upload", {})
    if not isinstance(upload, dict):
        raise ClientError("upload 必须是对象")
    canonical = _path_alias(upload, "upload")
    upload.pop("directory", None)
    upload["project_id"] = project_id
    upload["version"] = version
    if module_id is not None:
        upload["module_id"] = module_id
    if full_dir:
        canonical = full_dir
    if not canonical:
        raise ClientError("upload.full_dir 缺失；请传 --full-dir/--directory")
    upload["full_dir"] = canonical
    if release_dir:
        upload["release_dir"] = release_dir
    if released:
        upload["mark_released"] = True
    return data


class MultipartBody:
    """Repeatable, length-known multipart body streamed from disk."""

    def __init__(self, fields: Iterable[Tuple[str, str]],
                 files: Iterable[Tuple[str, Path]]):
        self.boundary = "----qor-" + secrets.token_hex(16)
        self.parts = []
        for name, value in fields:
            header = (
                "--{}\r\nContent-Disposition: form-data; name=\"{}\"\r\n\r\n"
                .format(self.boundary, name).encode("ascii")
            )
            self.parts.append((header, str(value).encode("utf-8"), None))
        for name, path in files:
            filename = path.name.replace("\\", "_").replace('"', "_")
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            header = (
                "--{}\r\nContent-Disposition: form-data; name=\"{}\"; "
                "filename=\"{}\"\r\nContent-Type: {}\r\n\r\n"
                .format(self.boundary, name, filename, content_type)
            ).encode("utf-8")
            self.parts.append((header, None, path))
        self.ending = "--{}--\r\n".format(self.boundary).encode("ascii")

    @property
    def content_type(self) -> str:
        return "multipart/form-data; boundary={}".format(self.boundary)

    @property
    def length(self) -> int:
        total = len(self.ending)
        for header, value, path in self.parts:
            total += len(header) + (len(value) if value is not None else path.stat().st_size) + 2
        return total

    def send(self, connection: http.client.HTTPConnection) -> None:
        for header, value, path in self.parts:
            connection.send(header)
            if value is not None:
                connection.send(value)
            else:
                with path.open("rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        connection.send(chunk)
            connection.send(b"\r\n")
        connection.send(self.ending)


def post(server: str, endpoint: str, api_key: str, timeout: float,
         insecure: bool = False, ca_file: Optional[str] = None,
         json_body: Optional[bytes] = None,
         multipart: Optional[MultipartBody] = None) -> Tuple[int, bytes]:
    """POST one request; keep credentials in headers and never in URLs/logs."""
    parsed = urlsplit(server)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ClientError("QOR_SERVER 必须是 http:// 或 https:// URL")
    if parsed.query or parsed.fragment:
        raise ClientError("QOR_SERVER 不应包含 query/fragment")
    context = None
    if parsed.scheme == "https":
        context = ssl.create_default_context(cafile=ca_file)
        if insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(
            parsed.hostname, parsed.port, timeout=timeout, context=context
        )
    else:
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
    base = parsed.path.rstrip("/")
    target = base + endpoint
    body_length = len(json_body) if json_body is not None else multipart.length
    content_type = "application/json; charset=utf-8" if json_body is not None else multipart.content_type
    # Host must come only from the URL netloc (http.client puts it once when
    # skip_host=False). Never putheader("Host") again — a duplicate Host makes
    # gunicorn/Django return HTTP 400 "Invalid HTTP Header: 'HOST'". Never copy
    # shell-style HOST/PORT env vars into request headers (curl does not).
    headers = (
        ("X-API-Key", api_key),
        ("Content-Type", content_type),
        ("Content-Length", str(body_length)),
        ("User-Agent", "qor-python-client/1.0"),
    )
    try:
        connection.putrequest("POST", target)
        for name, value in headers:
            connection.putheader(name, value)
        connection.endheaders()
        if json_body is not None:
            connection.send(json_body)
        else:
            multipart.send(connection)
        response = connection.getresponse()
        return response.status, response.read()
    except (OSError, http.client.HTTPException) as exc:
        raise TransportError("无法连接服务器 {}: {}".format(server, exc))
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="QoR 工作机上传客户端（单文件、仅 Python 标准库）"
    )
    parser.add_argument("project_id", type=int, help="项目 ID")
    parser.add_argument("version", help="版本标签")
    parser.add_argument("input", type=Path, help="本机 CSV 或 JSON 文件")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="强制 JSON §6.5 接口")
    mode.add_argument("--multipart", "--no-json", action="store_true",
                      help="强制 multipart CSV 接口")
    parser.add_argument("--module-id", type=int)
    parser.add_argument("--full-dir", help="Run 目录")
    parser.add_argument("--directory", help="--full-dir 的兼容别名")
    parser.add_argument("--release", action="store_true", help="标记已发布")
    parser.add_argument("--release-dir")
    parser.add_argument("--server", help="覆盖 QOR_SERVER")
    parser.add_argument("--env", dest="env_file", help="指定 qor_upload.env")
    parser.add_argument("--timeout", type=float, default=60.0, help="网络超时秒数（默认 60）")
    parser.add_argument("--ca-file", help="HTTPS 自定义 CA 文件")
    parser.add_argument("--insecure", action="store_true",
                        help="跳过 HTTPS 证书验证（仅排障）")
    return parser


def run(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    path = args.input.expanduser()
    if not path.is_file():
        raise ClientError("输入必须是存在的本地文件: {}".format(path))
    if args.timeout <= 0:
        raise ClientError("--timeout 必须大于 0")
    server, key, config = resolve_settings(args, environ, Path(__file__).resolve().parent)
    if args.full_dir and args.directory and args.full_dir != args.directory:
        raise ClientError("--full-dir 与 --directory 同时提供但值不同")
    full_dir = (
        args.full_dir or args.directory
        or environ.get("QOR_FULL_DIR") or config.get("QOR_FULL_DIR")
    )
    release_dir = (
        args.release_dir or environ.get("QOR_RELEASE_DIR") or config.get("QOR_RELEASE_DIR")
    )
    module_id = args.module_id
    if module_id is None:
        raw_module = environ.get("QOR_MODULE_ID") or config.get("QOR_MODULE_ID")
        module_id = int(raw_module) if raw_module else None
    released = args.release or (
        environ.get("QOR_RELEASE") or config.get("QOR_RELEASE", "0")
    ) == "1"
    detected_json = is_json_input(path)
    json_mode = args.json or (detected_json and not args.multipart)
    if detected_json and not args.json and not args.multipart:
        _safe_print("[INFO] 检测到 JSON 输入，自动使用 /api/v1/qor/upload")
    if detected_json and args.multipart:
        _safe_print("[WARN] JSON 被强制发往 CSV multipart 接口，服务端通常会拒绝")

    if json_mode:
        if detected_json:
            payload = load_json(path)
            if is_dc_report(payload):
                _safe_print("[INFO] 检测到原生 DC 报告，转换为 JSON §6.5")
                payload = convert_dc_to_qor_record(
                    payload, project_id=args.project_id, version=args.version,
                    full_dir_override=full_dir, release_dir_override=release_dir,
                    mark_released=released,
                )
        else:
            if not full_dir:
                raise ClientError("--json 上传 CSV 时必须传 --full-dir/--directory")
            _safe_print("[INFO] CSV 转换为 JSON §6.5")
            payload = csv_to_json(
                path, args.project_id, args.version, full_dir, release_dir
            )
        payload = inject_upload_fields(
            payload, args.project_id, args.version, module_id,
            full_dir, release_dir, released,
        )
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        endpoint = "/api/v1/qor/upload?project_id={}&version={}".format(
            args.project_id, quote(args.version, safe="")
        )
        _safe_print("[INFO] POST", server + endpoint, "mode=json")
        status, response_body = post(
            server, endpoint, key, args.timeout, args.insecure, args.ca_file,
            json_body=body,
        )
    else:
        fields = [
            ("project_id", str(args.project_id)), ("version", args.version),
            ("data_type", "qor"),
        ]
        if module_id is not None:
            fields.append(("module_id", str(module_id)))
        if released:
            fields.append(("mark_released", "1"))
        if release_dir:
            fields.append(("release_dir", release_dir))
        if full_dir:
            fields.append(("full_dir", full_dir))
        # New servers use files; file preserves compatibility with older ones.
        multipart = MultipartBody(fields, (("files", path), ("file", path)))
        endpoint = "/api/v1/upload"
        _safe_print("[INFO] POST", server + endpoint, "mode=multipart")
        status, response_body = post(
            server, endpoint, key, args.timeout, args.insecure, args.ca_file,
            multipart=multipart,
        )
    text = response_body.decode("utf-8", "replace")
    _safe_print("[INFO] HTTP 状态:", status)
    _safe_print("[INFO] 响应正文:", text)
    if 200 <= status < 300:
        _safe_print("[OK] 上传成功")
        return 0
    if status == 401:
        _safe_print("[FAIL] 认证失败，请检查 QOR_API_KEY", file=sys.stderr)
    elif status == 403:
        _safe_print("[FAIL] Key 无 upload 权限或账户不可用", file=sys.stderr)
    elif status == 422:
        _safe_print("[FAIL] 服务端未保存记录，请检查输入格式", file=sys.stderr)
    else:
        _safe_print("[FAIL] 上传失败（HTTP {}）".format(status), file=sys.stderr)
    return EXIT_HTTP


def main(argv: Optional[Iterable[str]] = None) -> int:
    try:
        return run(build_parser().parse_args(argv), os.environ)
    except TransportError as exc:
        _safe_print("[ERROR]", exc, file=sys.stderr)
        return EXIT_HTTP
    except ClientError as exc:
        _safe_print("[ERROR]", exc, file=sys.stderr)
        return EXIT_USAGE
    except (ValueError, TypeError) as exc:
        _safe_print("[ERROR] 参数或转换错误:", exc, file=sys.stderr)
        return EXIT_CONVERSION


if __name__ == "__main__":
    sys.exit(main())
