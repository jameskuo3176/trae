"""JSON 上传处理服务

负责:
  1. 校验 JSON 结构 (不依赖 jsonschema 包, 纯 Python)
  2. JSON → save_records_to_db 接受的扁平 record 格式
  3. JSON → save_violations_to_db 接受的 record 格式
  4. JSON → save_notes_to_db 接受的 record 格式

设计目标:
  - 与 CSV 上传共用底层 save_*_to_db 函数, 不绕过业务逻辑
  - 验证失败返回 400 + 详细错误路径, 便于客户端定位
  - 转换过程中尽量保留所有字段 (包括 extra) 以便审计
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django_app.services.qor_import import validate_full_dir
from django_app.services.path_derivation import PathDerivationError, derive_version, normalize_full_dir

_log = logging.getLogger(__name__)
logger = _log


# 支持的 schema_version (1.x 任意次版本, 2.0+ 不兼容)
SCHEMA_VERSION_PATTERN = re.compile(r'^1\.\d+$')

# 数值范围限制 (与 services/qor_import.py NUMERIC_RANGES 保持一致)
NUMERIC_RANGES = {
    # area
    'area_total': (0, 1e9), 'area_combinational': (0, 1e9),
    'area_sequential': (0, 1e9), 'area_black_box': (0, 1e9),
    'area_macro': (0, 1e9),
    # timing
    'wns_setup': (-1e6, 1e6), 'tns_setup': (-1e9, 1e9),
    'wns_hold': (-1e6, 1e6), 'tns_hold': (-1e9, 1e9),
    'nvp_setup': (0, 1e9), 'nvp_hold': (0, 1e9),
    # power
    'power_internal': (0, 1e6), 'power_switching': (0, 1e6),
    'power_leakage': (0, 1e6), 'power_total': (0, 1e6),
    # cells
    'cell_count': (0, 1e9), 'instance_count': (0, 1e9),
    'net_count': (0, 1e9), 'sequential_cell_count': (0, 1e9),
    # frequency
    'target_frequency': (0, 1e6), 'achieved_frequency': (0, 1e6),
    # ratios (0-1 小数, 但允许 0-100 上传时自动归一)
    'mbb_ratio': (0, 100), 'clock_gating_ratio': (0, 100),
    'utilization': (0, 100),
    # congestion
    'congestion': (0, 100), 'congestion_h': (0, 100),
    'congestion_v': (0, 100), 'congestion_b': (0, 100),
}

INT_FIELDS = {
    'nvp_setup', 'nvp_hold', 'cell_count', 'instance_count',
    'net_count', 'sequential_cell_count',
}

RATIO_FIELDS = {'mbb_ratio', 'clock_gating_ratio', 'utilization'}

CONGESTION_FIELDS = {'congestion_h', 'congestion_v', 'congestion_b'}

MAX_STR_LEN = 500
MAX_VERSION_LEN = 64


class JSONUploadError(ValueError):
    """JSON 验证/转换错误, 携带字段路径"""

    def __init__(self, path: str, message: str, status_code: int = 400):
        self.path = path
        self.message = message
        self.status_code = status_code
        super().__init__(f'{path}: {message}')


# =========================================================================
# 1. 顶层校验
# =========================================================================

def validate_upload_json(data: Any) -> dict:
    """校验 JSON 顶层结构, 返回规范化后的 dict (含默认值).

    Raises:
        JSONUploadError: 校验失败
    """
    if data is None or not isinstance(data, dict):
        raise JSONUploadError('$', '请求体必须是 JSON 对象')

    # schema_version
    sv = data.get('schema_version')
    if not sv or not isinstance(sv, str):
        raise JSONUploadError('$.schema_version', '必填, 字符串, 格式 "MAJOR.MINOR"')
    if not SCHEMA_VERSION_PATTERN.match(sv):
        raise JSONUploadError(
            '$.schema_version',
            f'不支持的 schema_version: {sv!r}, 当前仅支持 1.x',
        )

    # upload
    upload = data.get('upload')
    if not upload or not isinstance(upload, dict):
        raise JSONUploadError('$.upload', '必填, 对象')
    _validate_upload(upload, '$.upload')

    # records (可选但若有则必须为非空数组)
    records = data.get('records')
    if records is not None:
        if not isinstance(records, list) or len(records) == 0:
            raise JSONUploadError('$.records', '若提供则必须为非空数组')
        for i, rec in enumerate(records):
            _validate_record(rec, f'$.records[{i}]')

    # violation_paths (可选)
    vp = data.get('violation_paths')
    if vp is not None:
        if not isinstance(vp, list):
            raise JSONUploadError('$.violation_paths', '若提供则必须为数组')
        for i, v in enumerate(vp):
            _validate_violation_path(v, f'$.violation_paths[{i}]')

    # notes (可选)
    notes = data.get('notes')
    if notes is not None:
        if not isinstance(notes, list):
            raise JSONUploadError('$.notes', '若提供则必须为数组')
        for i, n in enumerate(notes):
            _validate_note_group(n, f'$.notes[{i}]')

    return data


def _validate_upload(upload: dict, path: str) -> None:
    pid = upload.get('project_id')
    if not isinstance(pid, int) or pid < 1:
        raise JSONUploadError(f'{path}.project_id', '必填, 整数 >= 1')

    version = upload.get('version')
    if version is not None and not isinstance(version, str):
        raise JSONUploadError(f'{path}.version', '若提供则必须为字符串；服务端会忽略并从 full_dir 派生')
    if version and len(version) > MAX_VERSION_LEN:
        raise JSONUploadError(f'{path}.version', f'长度不能超过 {MAX_VERSION_LEN}')
    full_dir = upload.get('full_dir')
    if not full_dir or not isinstance(full_dir, str):
        raise JSONUploadError(f'{path}.full_dir', '必填, 字符串；version 仅从该路径派生')
    try:
        derive_version(full_dir)
    except PathDerivationError as exc:
        raise JSONUploadError(f'{path}.full_dir', exc.message) from exc

    if 'module_id' in upload and upload['module_id'] is not None:
        if not isinstance(upload['module_id'], int) or upload['module_id'] < 1:
            raise JSONUploadError(f'{path}.module_id', '整数 >= 1')

    for fk in ('module_name', 'project_name', 'full_dir', 'release_dir', 'uploader_note'):
        v = upload.get(fk)
        if v is not None and not isinstance(v, str):
            raise JSONUploadError(f'{path}.{fk}', '若提供则必须为字符串')

    if 'mark_released' in upload and not isinstance(upload['mark_released'], bool):
        raise JSONUploadError(f'{path}.mark_released', '若提供则必须为布尔')


def _validate_record(rec: Any, path: str) -> None:
    if not isinstance(rec, dict):
        raise JSONUploadError(path, '必须为对象')
    mn = rec.get('module_name')
    if not mn or not isinstance(mn, str):
        raise JSONUploadError(f'{path}.module_name', '必填, 字符串')
    for fk in ('version', 'version_description', 'full_dir', 'release_dir',
               'source_file', 'comment'):
        v = rec.get(fk)
        if v is not None and not isinstance(v, str):
            raise JSONUploadError(f'{path}.{fk}', '若提供则必须为字符串')
    # 分组字段
    for fk in ('area', 'timing', 'power', 'cells', 'frequency',
               'ratios', 'congestion', 'clocks', 'extra'):
        v = rec.get(fk)
        if v is not None and not isinstance(v, dict):
            raise JSONUploadError(f'{path}.{fk}', '若提供则必须为对象')
    # clocks 内部
    clocks = rec.get('clocks')
    if clocks:
        for cname, cd in clocks.items():
            if not isinstance(cd, dict):
                raise JSONUploadError(f'{path}.clocks.{cname}', '必须为对象')
            for k, v in cd.items():
                if k == 'path':
                    if v is not None and not isinstance(v, str):
                        raise JSONUploadError(f'{path}.clocks.{cname}.path', '字符串')
                else:
                    if v is not None and not isinstance(v, (int, float)):
                        raise JSONUploadError(f'{path}.clocks.{cname}.{k}', '数值')


def _validate_violation_path(v: Any, path: str) -> None:
    if not isinstance(v, dict):
        raise JSONUploadError(path, '必须为对象')
    for fk, typ in [('module_name', str), ('timing_group', str)]:
        val = v.get(fk)
        if not isinstance(val, typ) or not val:
            raise JSONUploadError(f'{path}.{fk}', f'必填, {typ.__name__} 非空')
    for fk, typ in [('startpoint', str), ('endpoint', str)]:
        val = v.get(fk)
        if not isinstance(val, typ) or not val:
            raise JSONUploadError(f'{path}.{fk}', f'必填, {typ.__name__} 非空')
    if not isinstance(v.get('slack'), (int, float)):
        raise JSONUploadError(f'{path}.slack', '必填, 数值')
    if 'type' in v and v['type'] is not None:
        if v['type'] not in ('setup', 'hold'):
            raise JSONUploadError(f'{path}.type', '必须为 setup/hold')


def _validate_note_group(n: Any, path: str) -> None:
    if not isinstance(n, dict):
        raise JSONUploadError(path, '必须为对象')
    mn = n.get('module_name')
    if not mn or not isinstance(mn, str):
        raise JSONUploadError(f'{path}.module_name', '必填, 字符串')
    items = n.get('items')
    if not items or not isinstance(items, list):
        raise JSONUploadError(f'{path}.items', '必填, 非空数组')
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise JSONUploadError(f'{path}.items[{i}]', '必须为对象')
        item = it.get('item')
        if not item or not isinstance(item, str):
            raise JSONUploadError(f'{path}.items[{i}].item', '必填, 字符串')


# =========================================================================
# 2. JSON → record 转换 (供 save_records_to_db 使用)
# =========================================================================

def _coerce_num(v: Any) -> float | int | None:
    """安全数值转换"""
    if v is None or v == '':
        return None
    try:
        if isinstance(v, bool):  # bool is subclass of int
            return int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            if v != v or v in (float('inf'), float('-inf')):
                return None
            return v
        f = float(v)
        if f != f or f in (float('inf'), float('-inf')):
            return None
        return f
    except (ValueError, TypeError, OverflowError):
        return None


def _normalize_ratio(v: float) -> float:
    """0-1 / 0-100 归一为 0-1 (服务端 0-1, 接受 0-100)"""
    return v / 100.0 if v > 1.0 else v


def _sanitize_str(val: Any, max_len: int = MAX_STR_LEN) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    return s[:max_len]


def _extract_qor_fields(rec: dict) -> dict:
    """从结构化 JSON record 提取扁平字段 (与 CSV 解析后格式一致)"""
    flat: dict = {}

    # area
    a = rec.get('area') or {}
    if a.get('total') is not None:         flat['area_total'] = _coerce_num(a['total'])
    if a.get('combinational') is not None: flat['area_combinational'] = _coerce_num(a['combinational'])
    if a.get('sequential') is not None:    flat['area_sequential'] = _coerce_num(a['sequential'])
    if a.get('black_box') is not None:     flat['area_black_box'] = _coerce_num(a['black_box'])
    if a.get('macro') is not None:         flat['area_macro'] = _coerce_num(a['macro'])

    # timing
    t = rec.get('timing') or {}
    if t.get('setup'):
        ts = t['setup']
        if ts.get('wns') is not None: flat['wns_setup'] = _coerce_num(ts['wns'])
        if ts.get('tns') is not None: flat['tns_setup'] = _coerce_num(ts['tns'])
        if ts.get('nvp') is not None: flat['nvp_setup'] = _coerce_num(ts['nvp'])
    if t.get('hold'):
        th = t['hold']
        if th.get('wns') is not None: flat['wns_hold'] = _coerce_num(th['wns'])
        if th.get('tns') is not None: flat['tns_hold'] = _coerce_num(th['tns'])
        if th.get('nvp') is not None: flat['nvp_hold'] = _coerce_num(th['nvp'])

    # power
    p = rec.get('power') or {}
    for k in ('internal', 'switching', 'leakage', 'total'):
        if p.get(k) is not None:
            flat[f'power_{k}'] = _coerce_num(p[k])

    # cells
    c = rec.get('cells') or {}
    for k in ('cell_count', 'instance_count', 'net_count', 'sequential_cell_count'):
        if c.get(k) is not None:
            v = _coerce_num(c[k])
            if v is not None:
                flat[k] = int(v) if k in INT_FIELDS else v

    # frequency
    f = rec.get('frequency') or {}
    if f.get('target') is not None:   flat['target_frequency'] = _coerce_num(f['target'])
    if f.get('achieved') is not None: flat['achieved_frequency'] = _coerce_num(f['achieved'])

    # ratios
    r = rec.get('ratios') or {}
    for k in RATIO_FIELDS:
        if r.get(k) is not None:
            v = _coerce_num(r[k])
            if v is not None:
                flat[k] = _normalize_ratio(v)

    # congestion
    cg = rec.get('congestion') or {}
    for k in CONGESTION_FIELDS:
        if cg.get(k[11:]) is not None:
            v = _coerce_num(cg[k[11:]])
            if v is not None:
                flat[k] = _normalize_ratio(v)
    if cg.get('max') is not None and 'congestion' not in flat:
        v = _coerce_num(cg['max'])
        if v is not None:
            flat['congestion'] = _normalize_ratio(v)

    return flat


def _build_extra_fields(rec: dict, full_dir: str | None) -> dict:
    """构建 extra_fields 字典 (clocks, extra, version_description, full_dir)"""
    extra: dict = {}
    if 'clocks' in rec and rec['clocks']:
        extra['clocks'] = rec['clocks']
    if 'extra' in rec and rec['extra']:
        for k, v in rec['extra'].items():
            extra.setdefault(k, v)
    if 'version_description' in rec and rec['version_description']:
        extra['version_description'] = rec['version_description']
    if full_dir:
        extra['full_dir'] = full_dir
    return extra


def json_to_qor_records(
    data: dict, default_version: str | None = None,
    default_full_dir: str | None = None, default_release_dir: str | None = None,
) -> list[dict]:
    """将 JSON 顶层 records[] 转换为 save_records_to_db 接受的扁平 record 格式.

    Returns:
        list of dict, 每个元素形如:
          {
            'module_name': 'cpu_top',
            'version': 'v1.0',
            'area_total': 12345.6, 'wns_setup': -0.123, ...,
            'extra_fields': {'clocks': {...}, 'full_dir': '...', ...},
            'release_dir': 'v1.0/main/cpu',
            'source_file': 'reports/cpu_top/qor.rpt',
            'comment': 'baseline',
          }
    """
    upload = data.get('upload') or {}
    records_raw = data.get('records') or []

    out = []
    for rec in records_raw:
        # 字段优先级: record 自身 > upload 顶层 > 入参 default
        module_name = _sanitize_str(rec.get('module_name'))
        full_dir = (_sanitize_str(rec.get('full_dir')) or
                    _sanitize_str(default_full_dir) or
                    _sanitize_str(upload.get('full_dir')))
        full_dir = validate_full_dir(full_dir, 'full_dir')  # 校验绝对路径
        try:
            full_dir = normalize_full_dir(full_dir)
            version = derive_version(full_dir)
        except PathDerivationError as exc:
            raise JSONUploadError('$.records[].full_dir', exc.message) from exc
        release_dir = (_sanitize_str(rec.get('release_dir')) or
                       _sanitize_str(default_release_dir) or
                       _sanitize_str(upload.get('release_dir')))
        release_dir = validate_full_dir(release_dir, 'release_dir')  # 校验绝对路径

        if not module_name:
            # 缺少 module_name 在 record 校验时已报错, 这里防御
            continue
        if not version:
            # fallback: 用 default_version
            continue

        flat: dict = {'module_name': module_name, 'version': version}

        # full_dir: 顶层字段 + extra_fields 双重存储 (确保 CSV/JSON 融合时去重一致)
        if full_dir:
            flat['full_dir'] = full_dir

        # tag: 从 full_dir 最后一段派生, 确保 tag ↔ full_dir 一一对应
        # 与 models.py _compute_tag() 逻辑保持一致
        if full_dir:
            fd = full_dir.rstrip('/').rstrip('\\')
            parts = fd.replace('\\', '/').split('/')
            tag = parts[-1] if parts[-1] else (parts[-2] if len(parts) > 1 else fd)
            if tag:
                flat['tag'] = tag

        # version_description: 顶层字段 (与 CSV 对齐)
        vd = _sanitize_str(rec.get('version_description'))
        if vd:
            flat['version_description'] = vd

        # 数值字段
        flat.update(_extract_qor_fields(rec))

        # extra_fields
        extra = _build_extra_fields(rec, full_dir)
        if extra:
            flat['extra_fields'] = extra

        # release_dir
        if release_dir:
            flat['release_dir'] = release_dir

        # source_file / comment (供审计)
        sf = _sanitize_str(rec.get('source_file'))
        if sf:
            flat['source_file'] = sf
        comment = _sanitize_str(rec.get('comment'))
        if comment:
            flat['comment'] = comment

        out.append(flat)
    return out


# =========================================================================
# 3. JSON violation_paths → save_violations_to_db record 格式
# =========================================================================

def json_to_violation_records(
    data: dict, default_version: str | None = None,
) -> list[dict]:
    """将 JSON violation_paths[] 转换为 save_violations_to_db 接受的 record 格式"""
    upload = data.get('upload') or {}
    vps = data.get('violation_paths') or []
    out = []
    for v in vps:
        rec = {
            'module_name': _sanitize_str(v.get('module_name')),
            'version': _sanitize_str(v.get('version')) or _sanitize_str(default_version)
                       or _sanitize_str(upload.get('version')),
            'timing_group': _sanitize_str(v.get('timing_group')),
            'type': v.get('type') or 'setup',
            'slack': _coerce_num(v.get('slack')),
            'startpoint': _sanitize_str(v.get('startpoint')),
            'endpoint': _sanitize_str(v.get('endpoint')),
            'depth': _coerce_num(v.get('depth')),
            'pure_depth': _coerce_num(v.get('pure_depth')),
            'cell_delay': _coerce_num(v.get('cell_delay')),
            'net_delay': _coerce_num(v.get('net_delay')),
            'et_slack': _coerce_num(v.get('et_slack')),
            'st_slack': _coerce_num(v.get('st_slack')),
            'st_fanin': _coerce_num(v.get('st_fanin')),
            'st_fanout': _coerce_num(v.get('st_fanout')),
            'et_fanin': _coerce_num(v.get('et_fanin')),
            'et_fanout': _coerce_num(v.get('et_fanout')),
            'full_dir': _sanitize_str(v.get('full_dir')) or _sanitize_str(upload.get('full_dir')),
        }
        # 保留 extra 字段
        if v.get('clock_domain'):
            rec['clock_domain'] = _sanitize_str(v['clock_domain'])
        if v.get('extra'):
            rec['extra'] = v['extra']
        out.append(rec)
    return out


# =========================================================================
# 4. JSON notes → save_notes_to_db record 格式
# =========================================================================

def json_to_notes_records(
    data: dict, default_full_dir: str | None = None,
) -> list[dict]:
    """将 JSON notes[] 转换为 save_notes_to_db 接受的 record 格式

    notes[] 元素结构: {module_name, full_dir, items: [{item, value, category, unit, description}]}
    save_notes_to_db 接受的是扁平 record 列表, 一行一个 item.
    """
    upload = data.get('upload') or {}
    notes = data.get('notes') or []
    out = []
    for ng in notes:
        mn = _sanitize_str(ng.get('module_name'))
        if not mn:
            continue
        ng_full_dir = (_sanitize_str(ng.get('full_dir'))
                       or _sanitize_str(default_full_dir)
                       or _sanitize_str(upload.get('full_dir')))
        for it in (ng.get('items') or []):
            item = _sanitize_str(it.get('item'))
            if not item:
                continue
            value = _sanitize_str(it.get('value'))
            description = _sanitize_str(it.get('description'))
            # save_notes_to_db 期望 description 列, 把 value 合并到 description
            desc_text = description or value or ''
            if value and description and value != description:
                desc_text = f'{value}: {description}'
            out.append({
                'module_name': mn,
                'full_dir': ng_full_dir,
                'version': derive_version(ng_full_dir),
                'item': item,
                'description': desc_text,
                'category': _sanitize_str(it.get('category')),
            })
    return out