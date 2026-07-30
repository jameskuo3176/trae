"""QoR CSV 文件解析器（增强容错版）

支持解析 Design Compiler 综合后导出的 QoR CSV 文件。
解析器会自动识别常见的列名变体，将数据映射到标准字段。

容错能力:
  - 自动检测编码 (UTF-8 BOM / UTF-8 / GBK / Latin-1)
  - 跳过空行和全空行
  - 处理列数不一致的行 (多余值忽略，缺失值补 None)
  - 处理重复列名 (保留最后一个)
  - 处理 None 列名 (无表头的多余列)
  - 安全数值解析: 科学计数法、千分位逗号、带单位后缀、百分比
  - 识别多种"空值"表示: -, N/A, NA, NULL, None, 空, 等
  - 跳过所有映射字段均为空的行
  - 返回解析统计信息 (总数/跳过/错误)
  - 支持 Windows/Unix 换行符混用
  - 去除值首尾空白

支持的 CSV 列名（不区分大小写，忽略空格、下划线、连字符差异）:

面积类:
  - area_total, total_area, area
  - area_combinational, combinational_area, comb_area
  - area_sequential, sequential_area, seq_area
  - area_black_box, black_box_area, bb_area
  - area_macro, macro_area

时序类:
  - wns_setup, wns, worst_negative_slack, setup_wns
  - tns_setup, tns, total_negative_slack, setup_tns
  - nvp_setup, num_violating_paths, violating_paths
  - wns_hold, hold_wns
  - tns_hold, hold_tns
  - nvp_hold, hold_nvp

功耗类:
  - power_internal, internal_power
  - power_switching, switching_power
  - power_leakage, leakage_power
  - power_total, total_power, power

统计类:
  - cell_count, cells, num_cells
  - instance_count, instances, num_instances
  - net_count, nets, num_nets
  - sequential_cell_count, seq_cells

频率类:
  - target_frequency, target_freq, freq_target
  - achieved_frequency, achieved_freq, freq

版本/模块信息:
  - version, commit, revision, tag
  - module, module_name
  - project, project_name
"""
import csv
import io
import json
import os
import re
import logging

logger = logging.getLogger(__name__)


# 字段别名映射：标准字段名 -> 可能的 CSV 列名变体列表
FIELD_ALIASES = {
    # 面积
    'area_total': ['area_total', 'total_area', 'area', 'area_total_um2', 'total_cell_area'],
    'area_combinational': ['area_combinational', 'combinational_area', 'comb_area', 'area_comb', 'combinational'],
    'area_sequential': ['area_sequential', 'sequential_area', 'seq_area', 'area_seq', 'sequential', 'reg_area', 'regarea'],
    'area_black_box': ['area_black_box', 'black_box_area', 'bb_area', 'area_bb', 'blackbox'],
    'area_macro': ['area_macro', 'macro_area', 'area_macro_cell', 'macro'],

    # 时序 - Setup
    'wns_setup': ['wns_setup', 'wns', 'worst_negative_slack', 'setup_wns', 'worst_slack', 'slack', 'wns_settings'],
    'tns_setup': ['tns_setup', 'tns', 'total_negative_slack', 'setup_tns'],
    'nvp_setup': ['nvp_setup', 'nvp', 'num_violating_paths', 'violating_paths', 'num_violations', 'nvp_setup_count', 'violating'],
    # 时序 - Hold
    'wns_hold': ['wns_hold', 'hold_wns', 'worst_hold_slack', 'holdslack', 'hold_slack'],
    'tns_hold': ['tns_hold', 'hold_tns'],
    'nvp_hold': ['nvp_hold', 'hold_nvp', 'hold_violating'],

    # 功耗
    'power_internal': ['power_internal', 'internal_power', 'int_power', 'internalpower'],
    'power_switching': ['power_switching', 'switching_power', 'sw_power', 'switchingpower', 'net_power'],
    'power_leakage': ['power_leakage', 'leakage_power', 'leak_power', 'leakagepower', 'cell_leakage_power'],
    'power_total': ['power_total', 'total_power', 'power', 'totalpower'],

    # 统计
    'cell_count': ['cell_count', 'cells', 'num_cells', 'total_cells', 'cellcount', 'total_count', 'totalcount'],
    'instance_count': ['instance_count', 'instances', 'num_instances', 'total_instances', 'inst_count'],
    'net_count': ['net_count', 'nets', 'num_nets', 'total_nets', 'netcount'],
    'sequential_cell_count': ['sequential_cell_count', 'seq_cells', 'num_seq_cells', 'register_count', 'seq_cell_count', 'ff_count', 'reg_count', 'regcount'],

    # 频率
    'target_frequency': ['target_frequency', 'target_freq', 'freq_target', 'clock_frequency', 'clock_freq', 'target_clock'],
    'achieved_frequency': ['achieved_frequency', 'achieved_freq', 'freq', 'frequency', 'max_freq', 'fmax'],

    # 物理实现指标
    'mbb_ratio': ['mbb_ratio', 'mbb', 'multi_bit_ratio', 'mbff_ratio'],
    'clock_gating_ratio': ['clock_gating_ratio', 'cg_ratio', 'clock_gating', 'gating_ratio'],
    'utilization': ['utilization', 'util', 'placement_utilization', 'util_ratio'],
    # 拥塞指数: H=水平 / V=垂直 / B=Both(综合)
    # 旧字段 congestion 仍接受, 作为兼容入口 (等同于 congestion_b)
    'congestion': ['congestion', 'cong', 'congestion_index'],
    'congestion_h': ['congestion_h', 'congestion_horizontal', 'h_congestion', 'congestionh', 'cong_h'],
    'congestion_v': ['congestion_v', 'congestion_vertical', 'v_congestion', 'congestionv', 'cong_v'],
    'congestion_b': ['congestion_b', 'congestion_both', 'b_congestion', 'congestionb', 'cong_b'],

    # 元数据
    'version': ['version', 'commit', 'revision', 'tag', 'label', 'run_id', 'run', 'build'],
    'module_name': ['module', 'module_name', 'design', 'design_name', 'top_module', 'top', 'hierarchical_cell', 'instance'],
    'project_name': ['project', 'project_name', 'project_id', 'block'],

    # 发布目录 (对外发布路径, 与 full_dir 区分: full_dir 是运行时目录, release_dir 是 release 账号可见的目录)
    'release_dir': ['release_dir', 'releasedir', 'release_path', 'releasepath', 'release_directory'],
}

# 空值表示集合（不区分大小写）
NULL_VALUES = frozenset({
    '', '-', '--', '---', 'n/a', 'na', 'n.a.', 'null', 'none', 'nil',
    'nan', 'undefined', '空', '无', '未知', 'missing', 'empty',
})

# 浮点字段列表
FLOAT_FIELDS = frozenset([
    'area_total', 'area_combinational', 'area_sequential', 'area_black_box', 'area_macro',
    'wns_setup', 'tns_setup', 'wns_hold', 'tns_hold',
    'power_internal', 'power_switching', 'power_leakage', 'power_total',
    'target_frequency', 'achieved_frequency',
    # 物理实现指标
    'mbb_ratio', 'clock_gating_ratio', 'utilization',
    'congestion', 'congestion_h', 'congestion_v', 'congestion_b',
])

# 整数字段列表
INT_FIELDS = frozenset([
    'nvp_setup', 'nvp_hold', 'cell_count', 'instance_count',
    'net_count', 'sequential_cell_count',
])


def normalize_key(key):
    """标准化列名：转小写，去除空格、下划线、连字符、点号"""
    if key is None:
        return ''
    return re.sub(r'[\s_\-\.]+', '', str(key).strip().lower())


def build_alias_lookup():
    """构建 别名 -> 标准字段名 的反查字典"""
    lookup = {}
    for std_field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            norm = normalize_key(alias)
            if norm and norm not in lookup:
                lookup[norm] = std_field
        # 标准字段名本身也加入
        norm_std = normalize_key(std_field)
        if norm_std and norm_std not in lookup:
            lookup[norm_std] = std_field
    return lookup


ALIAS_LOOKUP = build_alias_lookup()

# 多时钟列匹配模式: {CLOCKNAME}_{period|wns|tns|path|hold_wns|hold_tns|hold_path}
# 注意: hold_* 必须放最前, 否则非贪婪匹配会截成 {CLOCKNAME='SYS_CLK_hold' field='wns'}
CLOCK_FIELD_PATTERN = re.compile(
    r'^(.+?)_(hold_wns|hold_tns|hold_path|period|wns|tns|path)$',
    re.IGNORECASE
)


# 接口类时钟 (累加 TNS / 路径数时排除, 违例/余量都不计入主指标)
# - 业务规则: 接口时钟的违例由外部协议决定, 不应反映到 chip 内部时序聚合
# - 支持子串匹配 (大写): "I2C_CLK" / "I2C_BUS" 都会命中
# - 留空可关闭此规则: 设为 []
EXCLUDED_CLOCK_PATTERNS = ['I2C', 'C2O', 'I2O']


def _is_excluded_clock(clock_name):
    """判断某时钟是否属于"接口类", 累加时排除"""
    if not EXCLUDED_CLOCK_PATTERNS:
        return False
    n = (clock_name or '').upper()
    return any(pat.upper() in n for pat in EXCLUDED_CLOCK_PATTERNS)


def is_null_value(value):
    """判断值是否为空值表示"""
    if value is None:
        return True
    s = str(value).strip().lower()
    return s in NULL_VALUES


def parse_float(value):
    """安全解析浮点数

    支持:
      - 科学计数法: 1.23e-4, 1.23E+5
      - 千分位逗号: 1,234.56
      - 带单位后缀: 1234.5um2, 1.5ns, 2.3mW, 500MHz
      - 百分比: 85%
      - 括号备注: 1234.5 (estimated)
      - 正负号: -0.15, +1.2
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
            return f if not (f != f) else None  # NaN check
        except (ValueError, TypeError, OverflowError):
            return None

    s = str(value).strip()
    if not s or s.lower() in NULL_VALUES:
        return None

    # 去除括号及括号内内容: "1234.5 (estimated)" -> "1234.5"
    s = re.sub(r'\s*\(.*?\)\s*', '', s)

    # 去除常见单位后缀 (不区分大小写)
    s = re.sub(r'\s*(um2|um|nm|mw|uw|nw|w|ns|ps|ghz|mhz|khz|hz)\b\s*', '', s, flags=re.IGNORECASE)

    # 去除百分号
    s = s.replace('%', '')

    # 去除千分位逗号 (仅当逗号后面跟3位数字时)
    s = re.sub(r',(?=\d{3}\b)', '', s)

    # 去除首尾空白和正号
    s = s.strip().lstrip('+')

    if not s:
        return None

    try:
        f = float(s)
        # 检查 NaN / Infinity
        if f != f:  # NaN
            return None
        if f in (float('inf'), float('-inf')):
            return None
        return f
    except (ValueError, TypeError, OverflowError):
        return None


def parse_int(value):
    """安全解析整数

    支持:
      - 浮点字符串: "123.0" -> 123
      - 带单位: "123 cells" -> 123
      - 千分位: "1,234" -> 1234
    """
    f = parse_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except (ValueError, OverflowError):
        return None


def detect_encoding(file_content_bytes):
    """检测文件编码

    优先级: UTF-8 BOM > UTF-8 > GBK > GB2312 > Latin-1
    """
    if not file_content_bytes:
        return 'utf-8'

    # UTF-8 BOM
    if file_content_bytes.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    # UTF-16 BOM
    if file_content_bytes.startswith(b'\xff\xfe') or file_content_bytes.startswith(b'\xfe\xff'):
        return 'utf-16'

    # 尝试 UTF-8
    try:
        file_content_bytes.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass

    # 尝试 GBK (中文 Windows 环境常用)
    try:
        file_content_bytes.decode('gbk')
        return 'gbk'
    except UnicodeDecodeError:
        pass

    # 尝试 GB2312
    try:
        file_content_bytes.decode('gb2312')
        return 'gb2312'
    except UnicodeDecodeError:
        pass

    # Latin-1 不会失败，作为最后手段
    return 'latin-1'


def clean_text(text):
    """清理文本内容"""
    if not text:
        return text
    # 统一换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # 去除 BOM
    if text.startswith('\ufeff'):
        text = text[1:]
    # 去除文件末尾多余空行
    text = text.rstrip() + '\n'
    return text


def deduplicate_headers(fieldnames):
    """处理重复列名，保留首次出现的位置

    对于重复的列名，后续的会被标记为 None (忽略)。
    同时处理 None 列名 (无表头的多余列)。
    """
    seen = set()
    cleaned = []
    for name in fieldnames:
        if name is None:
            cleaned.append(None)
            continue
        name_stripped = name.strip() if isinstance(name, str) else str(name).strip()
        if not name_stripped:
            cleaned.append(None)
            continue
        if name_stripped in seen:
            # 重复列名，忽略
            cleaned.append(None)
        else:
            seen.add(name_stripped)
            cleaned.append(name_stripped)
    return cleaned


def parse_csv_file(file_content_bytes, default_project=None, default_module=None, default_version=None):
    """解析 QoR CSV 文件内容（增强容错版）

    Args:
        file_content_bytes: CSV 文件的字节内容
        default_project: 默认项目名（如果 CSV 中没有）
        default_module: 默认模块名
        default_version: 默认版本号

    Returns:
        dict: {
            'records': list[dict],    # 解析出的记录列表
            'stats': {                # 解析统计
                'total_rows': int,        # 数据行总数 (不含表头)
                'parsed': int,            # 成功解析的记录数
                'skipped_empty': int,     # 跳过的空行数
                'skipped_no_data': int,   # 跳过的无有效数据行数
                'errors': int,            # 解析出错行数
                'field_map': dict,        # 列名映射
                'extra_columns': list,    # 未识别的额外列
            }
        }
    """
    stats = {
        'total_rows': 0,
        'parsed': 0,
        'skipped_empty': 0,
        'skipped_no_data': 0,
        'errors': 0,
        'field_map': {},
        'extra_columns': [],
        'clocks': [],
    }

    if not file_content_bytes:
        return {'records': [], 'stats': stats}

    # 检测编码并解码
    encoding = detect_encoding(file_content_bytes)
    try:
        text = file_content_bytes.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text = file_content_bytes.decode('latin-1')

    text = clean_text(text)

    # 使用 csv.reader 手动处理，以获得更好的容错能力
    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except csv.Error as e:
        logger.error('CSV 读取失败: %s', e)
        stats['errors'] = 1
        return {'records': [], 'stats': stats}

    if not rows:
        return {'records': [], 'stats': stats}

    # 第一行作为表头
    raw_headers = rows[0]
    headers = deduplicate_headers(raw_headers)

    # 建立列名映射: 标准字段名 -> 列索引
    field_map = {}     # 标准字段名 -> 列索引
    extra_cols = {}    # 列名 -> 列索引
    clock_cols = {}    # 时钟名 -> {field_type: col_idx}
    for idx, header in enumerate(headers):
        if header is None:
            continue
        norm = normalize_key(header)
        if norm in ALIAS_LOOKUP:
            std_field = ALIAS_LOOKUP[norm]
            # 首次映射优先
            if std_field not in field_map:
                field_map[std_field] = idx
        else:
            # 检测多时钟列: {CLOCKNAME}_{period|wns|tns|path} (header 大小写不敏感)
            m = CLOCK_FIELD_PATTERN.match(header.strip())
            if m:
                clock_name = m.group(1)
                field_type = m.group(2).lower()
                if clock_name not in clock_cols:
                    clock_cols[clock_name] = {}
                clock_cols[clock_name][field_type] = idx
            else:
                # 额外列: 用标准化名做 key (大小写/空格/下划线不敏感), 避免重复
                if norm and norm not in extra_cols:
                    extra_cols[norm] = (header.strip(), idx)

    stats['field_map'] = {std: headers[idx] for std, idx in field_map.items()}
    stats['extra_columns'] = list(extra_cols.keys())
    stats['clocks'] = list(clock_cols.keys())

    # 原始列名 -> 标准字段名 的反查 (供详情页"映射到"列展示)
    # 格式: { 原始CSV列名: 标准字段名 | "extra" | "clocks.{CLKNAME}.{field_type}" }
    col_mapping = {}
    for std_field, col_idx in field_map.items():
        if col_idx < len(headers) and headers[col_idx] is not None:
            col_mapping[headers[col_idx]] = std_field
    for col_norm, (col_name, _col_idx) in extra_cols.items():
        if col_name not in col_mapping:
            col_mapping[col_name] = 'extra'
    for clock_name, fields in clock_cols.items():
        for ftype, cidx in fields.items():
            if cidx < len(headers) and headers[cidx] is not None:
                col_mapping[headers[cidx]] = f'clocks.{clock_name}.{ftype}'

    records = []

    for row_idx, row in enumerate(rows[1:], start=2):
        stats['total_rows'] += 1

        # 跳过空行
        if not row or all(cell is None or str(cell).strip() == '' for cell in row):
            stats['skipped_empty'] += 1
            continue

        # 捕获原始 CSV 行 (列名 -> 原始字符串值), 用于详情页"原始 CSV 数据"展示
        # 保留所有列 (含映射到标准字段的列) 的原始字符串, 反映上传时的真实数据
        raw_csv = {}
        for header, col_idx in zip(headers, range(len(headers))):
            if header is None:
                continue
            if col_idx < len(row):
                raw_val = row[col_idx]
                if raw_val is None:
                    raw_val = ''
                else:
                    raw_val = str(raw_val).strip()
                # 即使空值也保留 (用空字符串), 反映原始 CSV 的完整性
                raw_csv[header] = raw_val

        try:
            record = {}
            extra_fields = {}
            has_valid_data = False

            # 提取标准字段
            for std_field, col_idx in field_map.items():
                if col_idx < len(row):
                    value = row[col_idx]
                    if value is not None:
                        value = value.strip()
                    if std_field in FLOAT_FIELDS:
                        parsed = parse_float(value)
                        if parsed is not None:
                            has_valid_data = True
                        record[std_field] = parsed
                    elif std_field in INT_FIELDS:
                        parsed = parse_int(value)
                        if parsed is not None:
                            has_valid_data = True
                        record[std_field] = parsed
                    else:
                        # 文本字段
                        if value and not is_null_value(value):
                            record[std_field] = value
                            if std_field in ('module_name', 'project_name', 'version'):
                                has_valid_data = True
                        else:
                            record[std_field] = None
                else:
                    # 列索引超出当前行长度，补 None
                    record[std_field] = None

            # 提取额外字段
            for col_norm, (col_name, col_idx) in extra_cols.items():
                if col_idx < len(row):
                    value = row[col_idx]
                    if value is not None and str(value).strip() and not is_null_value(value):
                        extra_fields[col_name] = value.strip()

            # 提取多时钟数据
            if clock_cols:
                clock_data = {}
                all_wns = []                # 所有时钟 wns (含正数, 仅用于 min 聚合)
                all_tns_for_sum = []        # 用于 sum 聚合的 tns (排除接口 + 正数按 0)
                all_path_for_sum = []       # 用于 sum 聚合的 path (排除接口)
                excluded_clocks = []        # 调试/统计: 本行被排除的时钟
                for clock_name, fields in clock_cols.items():
                    cd = {}
                    excluded = _is_excluded_clock(clock_name)
                    for ftype, cidx in fields.items():
                        if cidx < len(row):
                            raw_val = row[cidx]
                            if raw_val is not None:
                                raw_val = raw_val.strip()
                            if ftype in ('wns', 'tns', 'period', 'hold_wns', 'hold_tns'):
                                parsed = parse_float(raw_val)
                                if parsed is not None:
                                    cd[ftype] = parsed
                                    if ftype == 'wns':
                                        all_wns.append(parsed)
                                    elif ftype == 'tns':
                                        if not excluded:
                                            all_tns_for_sum.append(min(0.0, parsed))
                                    # hold_wns/hold_tns 不参与 setup 聚合
                            elif ftype in ('path', 'hold_path'):
                                parsed = parse_int(raw_val)
                                if parsed is not None:
                                    cd[ftype] = parsed
                                    if ftype == 'path' and not excluded:
                                        all_path_for_sum.append(parsed)
                                    # hold_path 不参与 setup 聚合
                    if cd:
                        clock_data[clock_name] = cd
                        if excluded:
                            excluded_clocks.append(clock_name)

                if clock_data:
                    extra_fields['clocks'] = clock_data
                    if excluded_clocks:
                        extra_fields['excluded_clocks'] = excluded_clocks
                    # 从 clocks 派生"汇总"指标 (原始 CSV 通常不含 wns_setup/tns_setup/nvp_setup)
                    # 派生规则:
                    #   wns_setup = min(wns)                 最差 (最负) 时钟的 WNS
                    #   tns_setup = sum(min(0, tns_i))       所有非接口时钟 TNS 之和 (正数按 0, 余量不补偿违例)
                    #   nvp_setup = sum(path)                所有非接口时钟违例路径数之和
                    if all_wns and record.get('wns_setup') is None:
                        record['wns_setup'] = min(all_wns)
                        has_valid_data = True
                    if all_tns_for_sum and record.get('tns_setup') is None:
                        record['tns_setup'] = sum(all_tns_for_sum)
                        has_valid_data = True
                    elif not all_tns_for_sum and record.get('tns_setup') is None:
                        # 所有时钟均为接口, tns_setup 留 None
                        pass
                    if all_path_for_sum and record.get('nvp_setup') is None:
                        record['nvp_setup'] = sum(all_path_for_sum)
                        has_valid_data = True
                    # hold 字段 (wns_hold/tns_hold/nvp_hold) 原始 CSV 不带 hold 数据, 留空:
                    # 若用户 CSV 显式传了 wns_hold/tns_hold/nvp_hold 列, 上面的标准字段提取已写入
                    # 若用户有 *_hold_wns 之类扩展, 可在此添加; 当前先按"无 hold 数据"处理

            # 跳过所有映射字段均为空的行
            if not has_valid_data:
                stats['skipped_no_data'] += 1
                continue

            # 应用默认值
            if not record.get('module_name') and default_module:
                record['module_name'] = default_module
            if not record.get('project_name') and default_project:
                record['project_name'] = default_project
            if not record.get('version'):
                record['version'] = default_version if default_version else 'v1'

            # 额外字段转 JSON
            # 同时保存:
            #   _raw_csv: 原始 CSV 行 (列名 -> 原始字符串), 供详情页"原始 CSV 数据"展示
            #   _col_mapping: 原始列名 -> 标准字段名/extra/clocks.xxx 的映射
            if raw_csv:
                extra_fields['_raw_csv'] = raw_csv
            if col_mapping:
                extra_fields['_col_mapping'] = col_mapping
            record['extra_fields'] = json.dumps(extra_fields, ensure_ascii=False) if extra_fields else None

            records.append(record)
            stats['parsed'] += 1

        except Exception as e:
            logger.warning('第 %d 行解析失败: %s', row_idx, e)
            stats['errors'] += 1
            continue

    return {'records': records, 'stats': stats}


def get_supported_fields():
    """返回所有支持的标准字段及其别名"""
    return FIELD_ALIASES


# =========================================================================
# 违例路径 CSV 解析
# =========================================================================

# 违例路径 CSV 列名别名映射 (标准化名 -> 可能的变体)
VIOLATION_FIELD_ALIASES = {
    'startpoint': ['startpoint', 'start_point', 'start', 'source'],
    'endpoint': ['endpoint', 'end_point', 'end', 'sink', 'destination'],
    'slack': ['slack'],
    'depth': ['depth'],
    'pure_depth': ['pure_depth', 'puredepth', 'pure dep'],
    'cell_delay': ['cell_delay', 'celldelay', 'cell delay'],
    'net_delay': ['net_delay', 'netdelay', 'net delay'],
    'et_slack': ['et_slack', 'etslack', 'et slack'],
    'st_slack': ['st_slack', 'stslack', 'st slack'],
    'st_fanin': ['st_fanin', 'stfanin', 'st fanin'],
    'st_fanout': ['st_fanout', 'stfanout', 'st fanout'],
    'et_fanin': ['et_fanin', 'etfanin', 'et fanin'],
    'et_fanout': ['et_fanout', 'etfanout', 'et fanout'],
}

VIOLATION_FLOAT_FIELDS = {'slack', 'cell_delay', 'net_delay', 'et_slack', 'st_slack'}
VIOLATION_INT_FIELDS = {'depth', 'pure_depth', 'st_fanin', 'st_fanout', 'et_fanin', 'et_fanout'}


def _normalize_col_name(name):
    """标准化列名: 小写 + 去除空格/下划线/连字符"""
    if not name:
        return ''
    return re.sub(r'[\s_\-]+', '', str(name).strip().lower())


def _build_violation_field_map(headers):
    """构建违例 CSV 列名到标准字段的映射

    元数据列 (module_name / version / full_dir) 也尝试识别,
    便于按 (module, version) 关联到已有的 QorRecord
    """
    field_map = {}
    # 元数据列额外识别
    extra_field_aliases = {
        'module_name': ['module', 'module_name', 'module name', 'design'],
        'version': ['version', 'ver', 'commit', 'revision', 'tag'],
        'full_dir': ['full_dir', 'fulldir', 'full dir', 'directory', 'path', 'run_dir'],
    }
    for std_field, aliases in {**VIOLATION_FIELD_ALIASES, **extra_field_aliases}.items():
        norm_aliases = [_normalize_col_name(a) for a in aliases]
        for i, h in enumerate(headers):
            nh = _normalize_col_name(h)
            if nh in norm_aliases and std_field not in field_map:
                field_map[std_field] = i
    return field_map


def _extract_timing_group_from_filename(filename):
    """从文件名提取 timing group 名称

    示例:
      SRAMCLK_violations.csv -> SRAMCLK
      CLK_CPU_setup_violations.csv -> CLK_CPU
      violations_SRAMCLK.csv -> SRAMCLK
      SRAMCLK.csv -> SRAMCLK
    """
    if not filename:
        return 'default'
    # 去除路径和扩展名
    base = os.path.basename(filename)
    base = os.path.splitext(base)[0]
    # 去除常见后缀
    base = re.sub(r'(?i)(violation|violations|setup|hold|paths?|report|reporting)', '', base)
    # 去除分隔符
    base = re.sub(r'[\s_\-]+', '', base)
    return base if base else 'default'


def parse_violation_csv(content, timing_group=None, filename=None):
    """解析违例路径 CSV 文件

    参数:
      content: 文件内容 (bytes 或 str)
      timing_group: 指定的 timing group 名称 (可选，优先于文件名推断)
      filename: 文件名 (用于推断 timing_group)

    返回:
      {
        'records': [{startpoint, endpoint, slack, ...}],
        'stats': {total_rows, skipped_empty, skipped_no_data, errors},
        'timing_group': str
      }
    """
    # 确定 timing group
    if not timing_group:
        timing_group = _extract_timing_group_from_filename(filename)

    stats = {'total_rows': 0, 'skipped_empty': 0, 'skipped_no_data': 0, 'errors': 0}
    records = []

    # 解码
    if isinstance(content, bytes):
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'latin-1'):
            try:
                text = content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            text = content.decode('utf-8', errors='replace')
    else:
        text = content

    # 统一换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    reader = csv.reader(text.splitlines())
    rows = list(reader)
    if len(rows) < 2:
        return {'records': [], 'stats': stats, 'timing_group': timing_group}

    # 解析表头
    headers = [h.strip() if h else '' for h in rows[0]]
    field_map = _build_violation_field_map(headers)

    # 如果没有识别到任何列，尝试按位置映射（假设标准顺序）
    if not field_map:
        # 标准顺序: STARTPOINT, ENDPOINT, SLACK, DEPTH, PURE_DEPTH, CELL_DELAY, NET_DELAY,
        #           ET_SLACK, ST_SLACK, ST_FANIN, ST_FANOUT, ET_FANIN, ET_FANOUT
        std_order = ['startpoint', 'endpoint', 'slack', 'depth', 'pure_depth',
                     'cell_delay', 'net_delay', 'et_slack', 'st_slack',
                     'st_fanin', 'st_fanout', 'et_fanin', 'et_fanout']
        for i, field in enumerate(std_order):
            if i < len(headers):
                field_map[field] = i

    if not field_map:
        stats['errors'] = len(rows) - 1
        return {'records': [], 'stats': stats, 'timing_group': timing_group}

    for row_idx, row in enumerate(rows[1:], start=2):
        stats['total_rows'] += 1

        # 跳过空行
        if not row or all(cell is None or str(cell).strip() == '' for cell in row):
            stats['skipped_empty'] += 1
            continue

        try:
            record = {'timing_group': timing_group}
            has_valid_data = False

            for std_field, col_idx in field_map.items():
                if col_idx >= len(row):
                    record[std_field] = None
                    continue

                raw_val = row[col_idx]
                if raw_val is not None:
                    raw_val = str(raw_val).strip()

                if std_field in VIOLATION_FLOAT_FIELDS:
                    parsed = parse_float(raw_val)
                    record[std_field] = parsed
                    if parsed is not None:
                        has_valid_data = True
                elif std_field in VIOLATION_INT_FIELDS:
                    parsed = parse_int(raw_val)
                    record[std_field] = parsed
                    if parsed is not None:
                        has_valid_data = True
                else:
                    # 文本字段 (startpoint, endpoint)
                    if raw_val and not is_null_value(raw_val):
                        # 处理 "11=-212835712990" 这种异常格式: 提取等号前的数字
                        cleaned = raw_val
                        if '=' in cleaned:
                            # 取等号前的部分
                            cleaned = cleaned.split('=')[0].strip()
                        record[std_field] = cleaned[:500]  # 截断超长字符串
                        has_valid_data = True
                    else:
                        record[std_field] = None

            # 至少要有 startpoint 或 slack 才算有效
            if not has_valid_data or (not record.get('startpoint') and record.get('slack') is None):
                stats['skipped_no_data'] += 1
                continue

            records.append(record)

        except Exception as e:
            logger.warning('违例 CSV 第 %d 行解析失败: %s', row_idx, e)
            stats['errors'] += 1
            continue

    return {'records': records, 'stats': stats, 'timing_group': timing_group}


# =========================================================================
# Run 备注表 CSV 解析 (2 列: item, description)
# =========================================================================

def parse_notes_csv(content, filename=None, default_full_dir=None):
    """解析 Run 备注 CSV 文件

    参数:
      content: 文件内容 (bytes 或 str)
      filename: 文件名 (仅用于日志)
      default_full_dir: 默认 full_dir (当 CSV 不含 full_dir 列时, 所有行都用此值)

    返回:
      {
        'records': [{item, description, full_dir}, ...],
        'stats': {total_rows, skipped_empty, errors}
      }

    CSV 格式 (2~3 列, 列名不区分大小写, 忽略空格/下划线/连字符):
      item,description[,full_dir]
      综合策略,compile_ultra
      目标频率,500
      修改内容,优化了关键路径 retiming

    若 CSV 含 full_dir 列, 则按行取值; 否则统一用 default_full_dir 参数。
    """
    stats = {'total_rows': 0, 'skipped_empty': 0, 'errors': 0}
    records = []

    # 解码
    if isinstance(content, bytes):
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'latin-1'):
            try:
                text = content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            text = content.decode('utf-8', errors='replace')
    else:
        text = content

    text = text.replace('\r\n', '\n').replace('\r', '\n')

    reader = csv.reader(text.splitlines())
    rows = list(reader)
    if len(rows) < 1:
        return {'records': [], 'stats': stats}

    # 解析表头, 识别 item / description / full_dir / module_name / version 列
    headers = [h.strip() if h else '' for h in rows[0]]
    item_col = None
    desc_col = None
    fulldir_col = None
    module_col = None
    version_col = None

    # 标准化别名集, 与 _normalize_col_name 保持一致
    ITEM_NH = frozenset(_normalize_col_name(x) for x in
                        ('item', 'name', 'key', 'parameter', 'param', '参数', '项目', '名称'))
    DESC_NH = frozenset(_normalize_col_name(x) for x in
                         ('description', 'desc', 'value', 'val', 'note', 'notes', 'comment',
                          'detail', 'content', '说明', '描述', '内容', '备注', '值'))
    FULLDIR_NH = frozenset(_normalize_col_name(x) for x in
                           ('full_dir', 'fulldir', 'full_dir_path', 'dir', 'directory', 'path',
                            '目录', '路径', 'run_dir', 'rundir'))
    MODULE_NH = frozenset(_normalize_col_name(x) for x in
                          ('module_name', 'module', 'design', 'design_name', 'top_module'))
    VERSION_NH = frozenset(_normalize_col_name(x) for x in
                           ('version', 'ver', 'commit', 'revision', 'tag'))

    for i, h in enumerate(headers):
        nh = _normalize_col_name(h)
        if nh in ITEM_NH:
            if item_col is None:
                item_col = i
        elif nh in DESC_NH:
            if desc_col is None:
                desc_col = i
        elif nh in FULLDIR_NH:
            if fulldir_col is None:
                fulldir_col = i
        elif nh in MODULE_NH:
            if module_col is None:
                module_col = i
        elif nh in VERSION_NH:
            if version_col is None:
                version_col = i

    # 若未识别到列名, 按位置映射: 第 1 列 item, 第 2 列 description, 第 3 列 full_dir
    if item_col is None:
        item_col = 0
    if desc_col is None:
        desc_col = 1 if len(headers) > 1 else 0
    # fulldir_col 保持 None, 后续用 default_full_dir 兜底

    start_idx = 1 if len(rows) > 1 else 0
    # 若只有数据行无表头 (单行), 从 0 开始
    if len(rows) == 1:
        start_idx = 0

    for row_idx, row in enumerate(rows[start_idx:], start=start_idx + 1):
        stats['total_rows'] += 1

        if not row or all(cell is None or str(cell).strip() == '' for cell in row):
            stats['skipped_empty'] += 1
            continue

        try:
            item = str(row[item_col]).strip() if item_col < len(row) else ''
            desc = str(row[desc_col]).strip() if desc_col < len(row) else ''

            # full_dir: 优先 CSV 列, 其次 default_full_dir
            full_dir = None
            if fulldir_col is not None and fulldir_col < len(row):
                fd_val = str(row[fulldir_col]).strip()
                if fd_val:
                    full_dir = fd_val
            if not full_dir and default_full_dir:
                full_dir = str(default_full_dir).strip() or None

            # module_name / version (可选, 用于按 (module, version) 关联 QorRecord)
            module_name = None
            if module_col is not None and module_col < len(row):
                mn_val = str(row[module_col]).strip()
                if mn_val:
                    module_name = mn_val
            version_val = None
            if version_col is not None and version_col < len(row):
                ver_val = str(row[version_col]).strip()
                if ver_val:
                    version_val = ver_val

            if not item and not desc:
                stats['skipped_empty'] += 1
                continue

            rec = {'item': item, 'description': desc, 'full_dir': full_dir}
            if module_name:
                rec['module_name'] = module_name
            if version_val:
                rec['version'] = version_val
            records.append(rec)
        except Exception as e:
            logger.warning('备注 CSV 第 %d 行解析失败: %s', row_idx, e)
            stats['errors'] += 1
            continue

    return {'records': records, 'stats': stats}
