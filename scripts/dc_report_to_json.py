"""DC 报告 → QorRecord 转换器 (Python 库 + CLI).

输入: 原始 DC 报告 JSON (含 top_module, timing, area, misc, run)
输出: §6.5 嵌套结构的 record dict, 可直接交给 services.qor_import.save_records_to_db

设计原则: 1 个 DC 报告 = 1 个 run = 1 条 QorRecord.
- full_dir = run.directory (不带 scenario/path_group 后缀)
- timing.setup 字段: worst-case 聚合 (WNS=min, TNS=min, NVP=sum)
- clocks 字段: 第一个 scenario 的所有 path_groups 作为 clocks (单 scenario 约束)
- extra.scenarios: 全量 scenarios × path_groups 审计数据
- register_count: 来自 misc.fgcg.total_flops (DC 寄存器数)
- raw_dc_report: 整个 DC 报告原文, dashboard 表格视图直接渲染

CLI 用法:
    python dc_report_to_json.py <dc_report.json>
    python dc_report_to_json.py --project-id 1 --version v1.0 \\
        <dc_report.json> -o run.json
    python dc_report_to_json.py --module-name cpu_top --mark-released \\
        <dc_report.json>
"""
import argparse
import json
import re
import sys
from typing import Any, Optional

from services.qor_import import parse_source_path

# schema_version 用于 §6.5 上传协议 (区别于 DC 报告自身的 scheme_version)
SCHEMA_VERSION = '1.0'


# =========================================================================
# 类型转换工具
# =========================================================================

def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _strip_pct(v) -> Optional[float]:
    """接受 '97.78%' / '0.9778' / 0.9778 → 返回 0-100 的数值."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip('%').strip()
    return _to_float(s)


def _resolve_source(section) -> Optional[str]:
    """从 timing.<name> 段提取 source 路径."""
    if isinstance(section, dict):
        return section.get('source')
    return None


# =========================================================================
# §6.5 嵌套结构构造
# =========================================================================

def _build_area(tile_area: dict) -> dict:
    """tile.area → §6.5 area 嵌套."""
    area = {}
    if _to_float(tile_area.get('total')) is not None:
        area['total'] = _to_float(tile_area['total'])
    if _to_float(tile_area.get('combinational')) is not None:
        area['combinational'] = _to_float(tile_area['combinational'])
    elif _to_float(tile_area.get('non_combinational')) is not None:
        area['combinational'] = _to_float(tile_area['non_combinational'])
    if _to_float(tile_area.get('sequential')) is not None:
        area['sequential'] = _to_float(tile_area['sequential'])
    if _to_float(tile_area.get('memory')) is not None:
        area['memory'] = _to_float(tile_area['memory'])
        area['black_box'] = _to_float(tile_area['memory'])  # black_box = 存储面积 (memory/sram)
    if _to_float(tile_area.get('macro')) is not None:
        area['macro'] = _to_float(tile_area['macro'])
    return area


def _build_cells(tile_count: dict, flop_count: dict) -> dict:
    """tile.cell_count + flop_count → §6.5 cells 嵌套."""
    cells = {}
    if _to_int(tile_count.get('total')) is not None:
        cells['cell_count'] = _to_int(tile_count['total'])
    if _to_int(tile_count.get('sequential')) is not None:
        cells['sequential_cell_count'] = _to_int(tile_count['sequential'])
    if _to_int(tile_count.get('combinational')) is not None:
        cells['instance_count'] = _to_int(tile_count['combinational'])
    if _to_int(tile_count.get('ram')) is not None:
        cells['ram_cell_count'] = _to_int(tile_count['ram'])
    if _to_int(tile_count.get('macro')) is not None:
        cells['macro_cell_count'] = _to_int(tile_count['macro'])
    # flop_count.total_sequential_cells 覆盖 (更精确源)
    if _to_int(flop_count.get('total_sequential_cells')) is not None:
        cells['sequential_cell_count'] = _to_int(flop_count['total_sequential_cells'])
    return cells


def _build_ratios(misc: dict) -> dict:
    """misc → §6.5 ratios 嵌套 (归一为 0-1)."""
    fgcg = misc.get('fgcg') or {}
    ratios = {}
    util = _to_float(misc.get('utilization'))
    if util is not None:
        ratios['utilization'] = (util / 100.0) if util > 1.0 else util
    mbb = _strip_pct(misc.get('mbb_ratio'))
    if mbb is not None:
        ratios['mbb_ratio'] = (mbb / 100.0) if mbb > 1.0 else mbb
    cgr = _strip_pct((fgcg.get('gated_flops') or {}).get('percentage'))
    if cgr is not None:
        ratios['clock_gating_ratio'] = (cgr / 100.0) if cgr > 1.0 else cgr
    return ratios


def _build_congestion(cong: dict) -> dict:
    """misc.congestion → §6.5 congestion 嵌套 (B=both, H, V)."""
    cong_obj = {}
    bdp = _strip_pct(cong.get('both_dirs_percentage'))
    if bdp is not None:
        cong_obj['max'] = (bdp / 100.0) if bdp > 1.0 else bdp
    if isinstance(cong.get('summary_lines'), list):
        for line in cong['summary_lines']:
            if not isinstance(line, str):
                continue
            m = re.search(r'^\s*([HV])\s+routing:.*?GRCs\s*=\s*\d+\s*\(([\d.]+)%\)', line)
            if m:
                direction = m.group(1).lower()
                gcrs_pct = _to_float(m.group(2))
                if gcrs_pct is not None:
                    cong_obj[direction] = (gcrs_pct / 100.0) if gcrs_pct > 1.0 else gcrs_pct
    return cong_obj


def _build_extra_fields(dc: dict, default_scenario_name: Optional[str],
                        default_path: Optional[str]) -> dict:
    """构造 record.extra (审计用)."""
    extra = {}
    if dc.get('stage'):
        extra['stage'] = dc['stage']
    if dc.get('generated_at'):
        extra['generated_at'] = dc['generated_at']
    if default_scenario_name:
        extra['default_scenario'] = default_scenario_name
    if default_path:
        extra['default_path'] = default_path

    errs = dc.get('errors') or []
    if errs:
        extra['errors'] = errs

    # timing metadata
    default = (dc.get('timing') or {}).get('default') or {}
    md = default.get('metadata')
    if isinstance(md, dict):
        for k in ('report', 'design', 'scenarios', 'version', 'date'):
            if md.get(k):
                extra[f'dc_metadata_{k}'] = md[k]

    # timing.final → 结构化摘要
    final = (dc.get('timing') or {}).get('final')
    if isinstance(final, dict):
        fin = {
            'status': final.get('status'),
            'source': _resolve_source(final),
        }
        if 'metadata' in final:
            fin['metadata'] = final['metadata']
        sc_summary = {}
        for sname, sval in (final.get('scenarios') or {}).items():
            if not isinstance(sval, dict):
                continue
            pgs = sval.get('path_groups') or {}
            wns_list = [_to_float(p.get('WNS')) for p in pgs.values()
                        if _to_float(p.get('WNS')) is not None]
            tns_list = [_to_float(p.get('TNS')) for p in pgs.values()
                        if _to_float(p.get('TNS')) is not None]
            nvp_list = [_to_int(p.get('NVP')) for p in pgs.values()
                        if _to_int(p.get('NVP')) is not None]
            sc_summary[sname] = {
                'wns_worst': min(wns_list) if wns_list else None,
                'tns_total': sum(tns_list) if tns_list else None,
                'nvp_total': sum(x for x in nvp_list if x is not None) if nvp_list else None,
            }
        if sc_summary:
            fin['scenarios'] = sc_summary
        extra['timing_final'] = fin

    # area.block
    block = ((dc.get('area') or {}).get('block')) or {}
    if isinstance(block, dict) and block:
        extra['blocks'] = block

    # misc 全部塞
    misc = dc.get('misc') or {}
    if isinstance(misc, dict):
        for k in ('fgcg', 'vt_ratio', 'flop_count', 'congestion', 'no_clock', 'warnings'):
            v = misc.get(k)
            if v:
                extra[f'misc_{k}'] = v
    return extra


# =========================================================================
# 核心转换: 原始 DC 报告 → §6.5 record dict
# =========================================================================

def convert_dc_to_qor_record(dc: dict, *,
                             project_id: Optional[int] = None,
                             version: Optional[str] = None,
                             module_name_override: Optional[str] = None,
                             full_dir_override: Optional[str] = None,
                             release_dir_override: Optional[str] = None,
                             mark_released: bool = False) -> dict:
    """把原始 DC 报告 dict 转成 §6.5 单条 record dict.

    该函数是核心转换逻辑, 供:
    - CLI (本文件 __main__)
    - routes.api_v1 上传端点 (检测到 DC 格式时)

    Args:
        dc: 原始 DC 报告 dict (已通过 validate_dc_report 校验)
        project_id: 注入 upload.project_id (供 POST /api/v1/qor/upload 使用)
        version: 注入到 record.version
        module_name_override: 覆盖 top_module
        full_dir_override: 覆盖 run.directory
        release_dir_override: 覆盖 run.directory 作为 release_dir
        mark_released: 是否标记 is_released

    Returns:
        dict, 形如:
        {
          "schema_version": "1.0",
          "upload": {
            "project_id": ...,          # 注入
            "version": ...,
            "mark_released": ...,
            "module_name": ...,        # top_module (供 save_records_to_db 查找 module)
          },
          "records": [<record dict>],   # 始终 1 条
          "raw_dc_report": <原始 DC 报告原文 dict>,  # 透传给 QorRecord.raw_dc_report
        }
    """
    top_module = module_name_override or dc.get('top_module') or 'unknown'
    run_dir = full_dir_override or ((dc.get('run') or {}).get('directory')) or ''
    default = (dc.get('timing') or {}).get('default') or {}
    default_path = _resolve_source(default)

    # 若 full_dir 未明确指定, 尝试从 source 路径解析
    parsed_source = None
    if not run_dir and default_path:
        try:
            parsed_source = parse_source_path(default_path, top_module=top_module)
            run_dir = parsed_source['full_dir']
        except ValueError:
            pass  # 解析失败则保持 run_dir 为空

    area = dc.get('area') or {}
    tile = area.get('tile') or {}
    tile_area = tile.get('area') or {}
    tile_count = tile.get('cell_count') or {}

    misc = dc.get('misc') or {}
    fgcg = misc.get('fgcg') or {}
    cong = misc.get('congestion') or {}
    flop_count = misc.get('flop_count') or {}

    # ---- §6.5 嵌套字段 ----
    area_obj = _build_area(tile_area)
    cells_obj = _build_cells(tile_count, flop_count)
    ratios_obj = _build_ratios(misc)
    cong_obj = _build_congestion(cong)

    # register_count: 来自 misc.fgcg.total_flops (DC 报告中最贴近 "FF 数量" 的字段)
    register_count = _to_int(fgcg.get('total_flops'))

    # ---- 遍历 timing.default.scenarios × path_groups ----
    scenarios = default.get('scenarios') or {}
    all_wns: list = []
    all_tns: list = []
    all_nvp: list = []
    clocks_dict: dict = {}  # §6.5 clocks: {<clock_name>: {...}}
    first_scenario: Optional[str] = None
    scenarios_audit: dict = {}

    for sname, sval in scenarios.items():
        if not isinstance(sval, dict):
            continue
        pgs = sval.get('path_groups') or {}
        scenarios_audit[sname] = {}

        for gname, gval in pgs.items():
            if not isinstance(gval, dict):
                continue
            wns = _to_float(gval.get('WNS'))
            tns = _to_float(gval.get('TNS'))
            nvp = _to_int(gval.get('NVP'))
            period = _to_float(gval.get('Clk_Period'))
            lol = _to_int(gval.get('LoL'))

            if wns is not None:
                all_wns.append(wns)
            if tns is not None:
                all_tns.append(tns)
            if nvp is not None:
                all_nvp.append(nvp)

            if first_scenario is None:
                first_scenario = sname
            if sname == first_scenario:
                if gname not in clocks_dict:
                    clocks_dict[gname] = {}
                if period is not None:
                    clocks_dict[gname]['period'] = period
                if wns is not None:
                    clocks_dict[gname]['wns'] = wns
                if tns is not None:
                    clocks_dict[gname]['tns'] = tns
                if nvp is not None:
                    clocks_dict[gname]['nvp'] = nvp

            pg_entry: dict = {}
            if wns is not None:
                pg_entry['wns'] = wns
            if tns is not None:
                pg_entry['tns'] = tns
            if nvp is not None:
                pg_entry['nvp'] = nvp
            if period is not None:
                pg_entry['period'] = period
            if lol is not None:
                pg_entry['lol'] = lol
            if gval.get('warnings'):
                pg_entry['warnings'] = gval['warnings']
            scenarios_audit[sname][gname] = pg_entry

    # ---- 组装 record ----
    rec: dict = {}
    rec['module_name'] = top_module
    if version:
        rec['version'] = version
    if run_dir:
        rec['full_dir'] = run_dir
        rec['release_dir'] = release_dir_override or run_dir

    if area_obj:
        rec['area'] = area_obj
    if cells_obj:
        rec['cells'] = cells_obj
    if ratios_obj:
        rec['ratios'] = ratios_obj
    if cong_obj:
        rec['congestion'] = cong_obj

    # register_count 作为顶层字段 (QorRecord.register_count)
    if register_count is not None:
        rec['register_count'] = register_count

    # timing.setup (worst-case 聚合)
    timing_obj: dict = {}
    setup: dict = {}
    if all_wns:
        setup['wns'] = min(all_wns)
    if all_tns:
        setup['tns'] = min(all_tns)
    if all_nvp:
        setup['nvp'] = sum(all_nvp)
    if setup:
        timing_obj['setup'] = setup
    if timing_obj:
        rec['timing'] = timing_obj

    if clocks_dict:
        rec['clocks'] = clocks_dict

    # extra 字段 (审计 + 聚合)
    extra = _build_extra_fields(dc, first_scenario, default_path)
    if scenarios_audit:
        extra['scenarios'] = scenarios_audit
    if first_scenario:
        extra['default_scenario'] = first_scenario
    extra['default_path'] = default_path
    if run_dir:
        extra['dc_full_dir'] = run_dir
    if all_wns:
        extra['aggregate_wns_min'] = min(all_wns)
    if all_tns:
        extra['aggregate_tns_min'] = min(all_tns)
    if all_nvp:
        extra['aggregate_nvp_sum'] = sum(all_nvp)
    extra['scenario_count'] = len(scenarios_audit)
    extra['path_group_count'] = sum(len(pgs) for pgs in scenarios_audit.values())
    # 从 source 路径解析的 tag 和 version (供 dashboard 标签展示)
    if parsed_source:
        if parsed_source.get('tag'):
            extra['tag'] = parsed_source['tag']
        if parsed_source.get('version'):
            extra['parsed_version'] = parsed_source['version']
    if extra:
        rec['extra'] = extra

    # ---- 组装 §6.5 上传协议 (含原始 DC 报告) ----
    upload_section: dict = {}
    if project_id is not None:
        upload_section['project_id'] = int(project_id)
    if version:
        upload_section['version'] = version
    if mark_released:
        upload_section['mark_released'] = True
    upload_section['module_name'] = top_module  # 供 save_records_to_db 查找 module

    payload = {
        'schema_version': SCHEMA_VERSION,
        'upload': upload_section,
        'records': [rec],
        # 透传原始 DC 报告原文 (供 routes/api_v1.py 写入 QorRecord.raw_dc_report)
        '_raw_dc_report': dc,
    }
    return payload


# =========================================================================
# 校验
# =========================================================================

class DCReportError(ValueError):
    """DC 报告校验错误."""

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f'{path}: {message}')


def validate_dc_report(data: Any) -> dict:
    """校验原始 DC 报告 JSON.

    必填顶层字段: scheme_version (int), top_module (str), run.directory (str),
                 timing.default (dict), timing.default.scenarios (dict)
    """
    if data is None or not isinstance(data, dict):
        raise DCReportError('$', '请求体必须是 JSON 对象')

    sv = data.get('scheme_version')
    if not isinstance(sv, int):
        raise DCReportError('$.scheme_version', '必填, 整数')

    top_module = data.get('top_module')
    if not top_module or not isinstance(top_module, str):
        raise DCReportError('$.top_module', '必填, 字符串')

    run = data.get('run')
    if not isinstance(run, dict):
        raise DCReportError('$.run', '必填, 对象')
    if not run.get('directory') or not isinstance(run.get('directory'), str):
        raise DCReportError('$.run.directory', '必填, 字符串')

    timing = data.get('timing')
    if not isinstance(timing, dict):
        raise DCReportError('$.timing', '必填, 对象')
    default = timing.get('default')
    if not isinstance(default, dict):
        raise DCReportError('$.timing.default', '必填, 对象')
    scenarios = default.get('scenarios')
    if not isinstance(scenarios, dict) or not scenarios:
        raise DCReportError('$.timing.default.scenarios', '必填, 非空对象')

    return data


def is_dc_report(data: Any) -> bool:
    """检测 JSON 是否为原始 DC 报告 (非 §6.5 上传格式).

    判断依据: 顶层同时含 top_module, timing, area, misc.
    """
    if not isinstance(data, dict):
        return False
    return all(k in data for k in ('top_module', 'timing', 'area', 'misc'))


# =========================================================================
# CLI
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description='DC 报告 JSON → §6.5 JSON 转换 (供 /api/v1/qor/upload)',
    )
    parser.add_argument('input', help='DC 报告 JSON 文件')
    parser.add_argument('-o', '--output', help='输出文件 (默认 stdout)')
    parser.add_argument('--project-id', type=int, help='注入到 upload.project_id')
    parser.add_argument('--version', help='注入到 upload.version 和 record.version')
    parser.add_argument('--module-name', help='覆盖 top_module')
    parser.add_argument('--full-dir', help='覆盖 run.directory 作为 full_dir')
    parser.add_argument('--release-dir', help='覆盖 run.directory 作为 release_dir')
    parser.add_argument('--mark-released', action='store_true',
                        help='标记记录为已发布')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        dc = json.load(f)

    try:
        validate_dc_report(dc)
    except DCReportError as e:
        print(f'[ERROR] {e.path}: {e.message}', file=sys.stderr)
        sys.exit(2)

    payload = convert_dc_to_qor_record(
        dc,
        project_id=args.project_id,
        version=args.version,
        module_name_override=args.module_name,
        full_dir_override=args.full_dir,
        release_dir_override=args.release_dir,
        mark_released=args.mark_released,
    )

    out_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(out_text)
        print(f'[OK] 写入 {args.output} ({len(payload["records"])} record)', file=sys.stderr)
    else:
        print(out_text)


if __name__ == '__main__':
    main()
