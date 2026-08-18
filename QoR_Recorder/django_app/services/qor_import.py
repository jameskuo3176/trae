"""QoR 数据导入服务

封装数据保存/合并/校验等业务逻辑, 供多个路由复用（Django 版本）。
"""
import json
import os
import re
import logging
from datetime import datetime
from typing import Optional
from django.conf import settings

from django.db import transaction
from django.db.models import Q

from django_app.core.models import (
    GlobalModule, LegacyModuleMapping, Module, ProjectModule, QorRecord,
    ViolationPath, RunNote, normalize_module_name,
)
from django_app.services.path_derivation import derive_version, normalize_full_dir

_log = logging.getLogger(__name__)


def associate_global_module(project, legacy_module):
    """Idempotently bridge a legacy local module to canonical metadata."""
    key = normalize_module_name(legacy_module.name)
    with transaction.atomic(using='default'):
        canonical, _ = GlobalModule.objects.get_or_create(
            normalized_name=key,
            defaults={
                'name': legacy_module.name,
                'description': legacy_module.description,
            },
        )
        ProjectModule.objects.get_or_create(
            project_id=project.id,
            module=canonical,
            defaults={
                'owner_id': legacy_module.owner_id,
                'collaborators': legacy_module.collaborators,
            },
        )
        LegacyModuleMapping.objects.update_or_create(
            project_id=project.id,
            legacy_module_id=legacy_module.id,
            defaults={'module': canonical, 'legacy_name': legacy_module.name},
        )
    return canonical


def mirror_heavy_document(project_id, instance):
    """Mirror heavy ORM rows into Mongo after the relational save succeeds.

    - orm: no-op
    - mongo: Mongo is required for API v2; failures propagate
    - hybrid: best-effort mirror so ORM remains readable during Mongo outages
    """
    mode = getattr(settings, 'PERSISTENCE_MODE', 'orm')
    if mode == 'orm':
        return
    try:
        from django_app.repositories import get_record_repository
        repository = get_record_repository()
        if isinstance(instance, QorRecord):
            value = instance.to_dict()
            value.update({
                'id': str(instance.id), 'legacy_id': str(instance.id),
                'project_id': project_id, 'legacy_module_id': instance.module_id,
            })
            mapping = LegacyModuleMapping.objects.filter(
                project_id=project_id, legacy_module_id=instance.module_id
            ).values_list('module_id', flat=True).first()
            value['module_id'] = mapping
            repository.upsert_record(value)
        elif isinstance(instance, ViolationPath):
            value = instance.to_dict()
            value.update({
                'id': str(instance.id), 'project_id': project_id,
                'record_id': str(instance.qor_record_id),
            })
            value.pop('qor_record_id', None)
            repository.upsert_violation(value)
        elif isinstance(instance, RunNote):
            value = instance.to_dict()
            value.update({
                'id': str(instance.id), 'project_id': project_id,
                'record_id': str(instance.qor_record_id),
            })
            value.pop('qor_record_id', None)
            repository.upsert_note(value)
    except Exception as exc:
        _log.exception('Mongo mirror failed for %s id=%s', type(instance).__name__, instance.pk)
        if mode == 'mongo':
            from django_app.repositories import RepositoryError
            raise RepositoryError(
                f'Mongo write required under PERSISTENCE_MODE=mongo '
                f'({type(instance).__name__} id={instance.pk})'
            ) from exc
        # hybrid: keep the relational write available during Mongo outages.

# ---------------------------------------------------------------------------
# 路径规范化: 校验 full_dir / release_dir 是否为绝对路径
# ---------------------------------------------------------------------------

# 相对路径特征: 不以 / 或盘符开头 (Windows: C:\, D:\, 等)
_PATH_RELATIVE_RE = re.compile(r'^[a-zA-Z]:')


def is_absolute_path(path: str) -> bool:
    """判断路径是否为绝对路径

    支持 Unix (/path/to/dir) 和 Windows (C:\\path\\to\\dir)
    """
    if not path:
        return False
    path = path.strip()
    if os.path.isabs(path):
        return True
    # 某些 Linux 路径可能不以 / 开头 (如 ~/path), 但实际是绝对路径
    if path.startswith('~'):
        return True
    if _PATH_RELATIVE_RE.match(path):
        return True
    return False


def normalize_path(path: str, base_dir: str | None = None) -> str | None:
    """将路径规范化为绝对路径

    - 如果是绝对路径, 直接返回规范化后的形态
    - 如果是相对路径, 且提供了 base_dir, 则拼接为绝对路径
    - 如果无法规范化, 记录警告并返回原值

    Returns:
        规范化后的绝对路径, 或 None (输入为空)
    """
    if not path:
        return None
    path = path.strip()
    if not path:
        return None
    if is_absolute_path(path):
        return os.path.normpath(path)
    if base_dir:
        normalized = os.path.normpath(os.path.join(base_dir, path))
        _log.warning("相对路径已拼接为绝对路径: %s + %s -> %s", base_dir, path, normalized)
        return normalized
    _log.warning("检测到相对路径, 无法拼接 (缺少 base_dir): %s", path)
    return path


def validate_full_dir(path: str, field_name: str = 'full_dir') -> str | None:
    """校验 full_dir / release_dir 路径

    返回:
      - absolute path string: 路径合法
      - None: 输入为空

    若路径为相对路径, 记录警告, 但仍返回原值 (由调用方决定是否接受)
    """
    if not path:
        return None
    path = path.strip()
    if not path:
        return None
    if not is_absolute_path(path):
        _log.warning(
            "%s 使用了相对路径, 可能导致数据冲突: %s",
            field_name, path,
        )
    return path


# ---------------------------------------------------------------------------
# 路径解析: 从 source 路径自动提取 full_dir / tag / version
# ---------------------------------------------------------------------------

# 默认版本号正则: 匹配形如 syn_run_0804 / impl_run_0423 / pr_run_2024 的段
_DEFAULT_VERSION_RE = re.compile(r'^[a-zA-Z]+_run_\d+$')

# 默认 rpts 标记: 以此作为 full_dir 的截断点
_DEFAULT_RPTS_MARKER = '/rpts/'


def parse_source_path(source_path, *,
                      top_module=None,
                      version_pattern=None,
                      rpts_marker=None):
    """从 source 路径自动提取 full_dir、tag 和 version。

    示例路径:
      /project_dir/Syn/week2_run/syn_run_0804/main/modulea_t_cfg1_rundir/rpts/Synthesis/file

    提取结果:
      full_dir: /project_dir/Syn/week2_run/syn_run_0804/main/modulea_t_cfg1_rundir
      tag:      cfg1_rundir  (去除模块名前缀 modulea_t_ 后)
      version:  syn_run_0804

    解析规则:
      1. full_dir = rpts_marker 之前的完整路径
      2. version = full_dir 各段中匹配 version_pattern 的第一个段
      3. tag = full_dir 最后一个路径段; 若提供 top_module, 自动去除模块名前缀

    Args:
        source_path: 源文件完整路径 (str)
        top_module: 模块名, 用于从 tag 中去除模块名前缀 (可选)
        version_pattern: 版本号正则 (str 或 compiled re), 默认匹配 *_run_数字 格式
        rpts_marker: rpts 目录标记, 默认 '/rpts/'

    Returns:
        dict: {'full_dir': str, 'tag': str, 'version': str | None}

    Raises:
        ValueError: 路径格式不符合预期 (缺少 rpts_marker 等)
    """
    if not source_path or not isinstance(source_path, str):
        raise ValueError(f'source_path 必须为非空字符串, 实际: {source_path!r}')

    marker = rpts_marker or _DEFAULT_RPTS_MARKER

    # 规范化 version_pattern: 支持 str 或 compiled re
    if version_pattern is None:
        ver_re = _DEFAULT_VERSION_RE
    elif isinstance(version_pattern, str):
        ver_re = re.compile(version_pattern)
    else:
        ver_re = version_pattern

    # 1. 提取 full_dir: rpts_marker 之前的部分
    idx = source_path.find(marker)
    if idx == -1:
        raise ValueError(
            f'路径中未找到 "{marker}" 标记, 无法确定 full_dir 截断点: {source_path}'
        )
    full_dir = source_path[:idx]

    if not full_dir:
        raise ValueError(f'full_dir 为空, 路径格式异常: {source_path}')

    # 2. 提取 tag: full_dir 的最后一个路径段
    #    兼容 Unix (/) 和 Windows (\) 路径分隔符
    segments = [s for s in re.split(r'[/\\]', full_dir) if s]
    if not segments:
        raise ValueError(f'full_dir 路径段为空: {full_dir}')

    raw_tag = segments[-1]

    # 去除模块名前缀 (如 modulea_t_ → 保留 cfg1_rundir)
    if top_module:
        # 精确匹配 top_module 本身
        if raw_tag == top_module:
            tag = raw_tag
        elif raw_tag.startswith(top_module + '_'):
            tag = raw_tag[len(top_module) + 1:]
        else:
            # top_module 可能只是部分匹配, 回退到通用逻辑
            parts = raw_tag.split('_', 1)
            if len(parts) >= 2 and len(parts[0]) >= 3:
                tag = parts[1]
            else:
                tag = raw_tag
    else:
        # 无 top_module 时, 尝试按通用模式去除前缀 (第一个 _ 之前的部分)
        # 仅当 tag 包含至少两个 _ 分隔的部分时才尝试
        parts = raw_tag.split('_', 1)
        if len(parts) >= 2 and len(parts[0]) >= 3:
            # 前缀长度 >= 3 且 tag 包含多个部分 → 可能是模块名
            tag = parts[1]
        else:
            tag = raw_tag

    # 3. 提取 version: 遍历 full_dir 各段, 匹配版本号正则
    version = None
    for seg in segments:
        if ver_re.match(seg):
            version = seg
            break

    return {
        'full_dir': full_dir,
        'tag': tag,
        'version': version,
    }


def _coerce_extra_fields(value):
    """规范化 extra_fields: 接受 dict / JSON 字符串 / None.

    QorRecord.extra_fields 是 Text 列, 统一在写入前序列化为 JSON 字符串.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s or None
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return json.dumps(str(value), ensure_ascii=False)
    return None


def _validate_extra_fields_scenario_rules(extra: dict, record_id: str = '') -> None:
    """校验 extra_fields 中的 scenarios 数据规则.

    规则:
      1. 除时序标签外, 所有非时序字段不得包含 'scenarios' 字样.
         允许的例外: extra.scenarios (场景审计数据), timing_final.scenarios (时序数据).
      2. 禁止在非时序字段中出现 scenario 键名 (如 default_scenario, dc_metadata_scenarios).
      3. 记录警告日志但不阻止导入 (兼容历史数据).

    返回: 无 (通过日志记录违规, 不阻断导入流程).
    """
    _SCENARIO_LOWER = 'scenario'
    # 允许的时序路径 (这些键名下允许包含 scenarios)
    _ALLOWED_KEYS = {'scenarios', 'timing_final'}

    violations = []

    def _scan(obj, path='extra'):
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f'{path}.{key}'
                if _SCENARIO_LOWER in key.lower():
                    # 检查父路径是否在允许列表中
                    parent_key = path.split('.')[-1] if '.' in path else path
                    is_root_scenarios = path == 'extra' and key == 'scenarios'
                    if not is_root_scenarios and parent_key not in _ALLOWED_KEYS:
                        violations.append(
                            f'{current_path}: 非时序字段包含 "scenarios" 字样'
                        )
                _scan(value, current_path)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                _scan(item, f'{path}[{idx}]')

    _scan(extra)
    if violations:
        rid = f' [{record_id}]' if record_id else ''
        _log.warning(
            'scenarios 规则校验发现 %d 处违规%s: %s',
            len(violations), rid, '; '.join(violations[:5])
        )


def _sync_congestion(rec):
    """同步拥塞指数字段, 保持向后兼容

    规则:
      - 若 congestion_b 有值但 congestion 为空, 则 congestion = congestion_b
      - 若 congestion 有值但 congestion_b 为空, 则 congestion_b = congestion
      - 二者都为空时不动
    """
    if rec.congestion_b is not None and rec.congestion is None:
        rec.congestion = rec.congestion_b
    elif rec.congestion is not None and rec.congestion_b is None:
        rec.congestion_b = rec.congestion


def save_records_to_db(records, project, module_id, version, source_filename,
                        mark_released=False, owner_id=None, default_release_dir=None,
                        current_user=None):
    """将解析后的记录保存到数据库

    保护措施:
      - 数值范围校验: 过滤异常大值、负数
      - 字符串截断: 防止超长字符串污染 DB
      - 去重 upsert: 同 (module_id, version) 已存在则更新
      - 单行异常不影响整体

    mark_released=True 时, 新建/更新的记录会被标记为已发布

    default_release_dir: 整批统一指定的 release_dir (如通过上传表单指定),
      - 优先于记录自带的 release_dir (覆盖)
      - 缺省/None 时不修改记录自带的 release_dir

    current_user: Django 请求用户对象 (用于 released_by 和评论)

    Returns:
        (saved_count, skipped_count, updated_count)
    """
    saved_count = 0
    skipped_count = 0
    updated_count = 0
    module_cache = {}

    MAX_STR_LEN = 500

    NUMERIC_RANGES = {
        'area_total': (0, 1e9), 'area_combinational': (0, 1e9),
        'area_sequential': (0, 1e9), 'area_black_box': (0, 1e9), 'area_macro': (0, 1e9),
        'wns_setup': (-1e6, 1e6), 'tns_setup': (-1e9, 1e9),
        'wns_hold': (-1e6, 1e6), 'tns_hold': (-1e9, 1e9),
        'power_internal': (0, 1e6), 'power_switching': (0, 1e6),
        'power_leakage': (0, 1e6), 'power_total': (0, 1e6),
        'target_frequency': (0, 1e6), 'achieved_frequency': (0, 1e6),
        'nvp_setup': (0, 1e9), 'nvp_hold': (0, 1e9),
        'cell_count': (0, 1e9), 'instance_count': (0, 1e9),
        'net_count': (0, 1e9), 'sequential_cell_count': (0, 1e9),
        'ram_cell_count': (0, 1e9), 'macro_cell_count': (0, 1e9),
        'register_count': (0, 1e9),  # DC 报告的 total_flops (寄存器数)
        'mbb_ratio': (0, 100), 'clock_gating_ratio': (0, 100),
        'utilization': (0, 100),
        'congestion': (0, 100), 'congestion_h': (0, 100),
        'congestion_v': (0, 100), 'congestion_b': (0, 100),
    }

    FLOAT_FIELDS_SET = set(NUMERIC_RANGES.keys())

    def sanitize_value(field, val):
        if val is None:
            return None
        try:
            v = float(val)
        except (ValueError, TypeError, OverflowError):
            return None
        if v != v or v in (float('inf'), float('-inf')):
            return None
        if field in NUMERIC_RANGES:
            lo, hi = NUMERIC_RANGES[field]
            if v < lo or v > hi:
                return None
        if field in ('nvp_setup', 'nvp_hold', 'cell_count', 'instance_count',
                     'net_count', 'sequential_cell_count', 'ram_cell_count',
                     'macro_cell_count', 'register_count'):
            return int(v)
        return v

    def sanitize_str(val):
        if val is None:
            return None
        s = str(val).strip()
        if len(s) > MAX_STR_LEN:
            return s[:MAX_STR_LEN]
        return s if s else None

    _log.info("save_records_to_db: 开始处理 %d 条记录, project_id=%s, module_id=%s, version=%s",
              len(records), project.id if project else None, module_id, version)

    for record in records:
        try:
            mod_name = sanitize_str(record.get('module_name'))
            if not mod_name:
                if module_id:
                    mod = Module.objects.filter(id=module_id).first()
                    if not mod:
                        _log.warning("save_records_to_db: 跳过记录 - module_id=%s 对应的模块不存在, record keys: %s",
                                     module_id, list(record.keys())[:10])
                        skipped_count += 1
                        continue
                else:
                    _log.warning("save_records_to_db: 跳过记录 - 未提供 module_id 且 CSV 中无 module_name 列, record keys: %s",
                                 list(record.keys())[:10])
                    skipped_count += 1
                    continue
            else:
                if module_id:
                    mod = Module.objects.filter(id=module_id).first()
                else:
                    if mod_name in module_cache:
                        mod = module_cache[mod_name]
                    else:
                        mod = Module.objects.filter(project_id=project.id, name=mod_name).first()
                        if not mod:
                            mod = Module(project_id=project.id, name=mod_name)
                            mod.save()
                        module_cache[mod_name] = mod
            associate_global_module(project, mod)

            # 提取本条 record 的 full_dir (用于精确去重)
            _rec_full_dir = sanitize_str(record.get('full_dir'))
            if not _rec_full_dir:
                _ne = record.get('extra_fields')
                if isinstance(_ne, dict):
                    _rec_full_dir = sanitize_str(_ne.get('full_dir'))
                elif isinstance(_ne, str) and _ne.strip():
                    try:
                        _ne2 = json.loads(_ne)
                        if isinstance(_ne2, dict):
                            _rec_full_dir = sanitize_str(_ne2.get('full_dir'))
                    except (ValueError, TypeError):
                        pass
            _rec_full_dir = str(_rec_full_dir)[:500] if _rec_full_dir else None
            _rec_full_dir = validate_full_dir(_rec_full_dir, 'full_dir')  # 校验绝对路径
            # New imports have one canonical source of truth. Caller-supplied
            # version is intentionally ignored and there is no v1 fallback.
            rec_version = derive_version(_rec_full_dir)
            _rec_full_dir = normalize_full_dir(_rec_full_dir)

            # 去重: QorRecord 唯一键是 (module_id, version, full_dir)
            q = QorRecord.objects.filter(module_id=mod.id, version=rec_version)
            if _rec_full_dir:
                existing = q.filter(full_dir=_rec_full_dir).first()
            else:
                existing = q.first()

            if existing:
                for f in FLOAT_FIELDS_SET:
                    if f in record:
                        cleaned = sanitize_value(f, record[f])
                        if cleaned is not None:
                            setattr(existing, f, cleaned)
                _sync_congestion(existing)
                # version_description: 优先用 record 自带值, 否则保留已有
                if record.get('version_description'):
                    existing.version_description = sanitize_str(record['version_description'])
                # comment: 存入 extra_fields (to_dict 从 extra_fields.comment 读取)
                new_extra = record.get('extra_fields')
                if new_extra:
                    cur = existing.extra_fields
                    if isinstance(cur, str):
                        try:
                            cur = json.loads(cur)
                            if isinstance(cur, str):
                                cur = json.loads(cur)
                        except (ValueError, TypeError):
                            cur = {}
                    elif cur is None:
                        cur = {}
                    if isinstance(new_extra, str):
                        try:
                            new_extra = json.loads(new_extra)
                        except (ValueError, TypeError):
                            new_extra = {}
                    if isinstance(new_extra, dict):
                        cur.update(new_extra)
                else:
                    cur = existing.extra_fields
                    if isinstance(cur, str):
                        try:
                            cur = json.loads(cur) if cur else {}
                        except (ValueError, TypeError):
                            cur = {}
                    elif cur is None:
                        cur = {}
                # comment 存入 extra_fields (与 to_dict 读取路径一致)
                if record.get('comment'):
                    cur['comment'] = sanitize_str(record['comment'])
                # full_dir 同步到 extra_fields (确保 CSV/JSON 数据融合后统一)
                if record.get('full_dir') and not cur.get('full_dir'):
                    cur['full_dir'] = sanitize_str(record['full_dir'])
                # 序列化为 JSON 字符串 (extra_fields 列是 Text, 不接受 dict)
                try:
                    existing.extra_fields = json.dumps(cur, ensure_ascii=False)
                except (TypeError, ValueError):
                    existing.extra_fields = json.dumps(str(cur), ensure_ascii=False)
                # 校验更新后的 scenarios 数据规则
                if isinstance(cur, dict):
                    _validate_extra_fields_scenario_rules(cur, f'update:{mod.name}/{rec_version}')
                existing.source_file = sanitize_str(source_filename) or existing.source_file
                _ef = existing.extra_fields
                if isinstance(_ef, str):
                    try:
                        _ef = json.loads(_ef) if _ef else {}
                    except (ValueError, TypeError):
                        _ef = {}
                if isinstance(_ef, dict) and _ef.get('full_dir') and not existing.full_dir:
                    existing.full_dir = str(_ef['full_dir'])[:500]
                # release_dir: 优先 default_release_dir (整批统一), 其次 CSV 提供的值
                _rd_csv = record.get('release_dir')
                if default_release_dir is not None:
                    _rd_final = str(sanitize_str(default_release_dir))[:500] if str(default_release_dir).strip() else None
                elif _rd_csv:
                    _rd_final = str(sanitize_str(_rd_csv))[:500]
                else:
                    _rd_final = None
                if _rd_final is not None or (default_release_dir is not None):
                    existing.release_dir = _rd_final
                if mark_released:
                    existing.is_released = True
                    if not existing.released_at:
                        existing.released_at = datetime.utcnow()
                    if not existing.released_by and current_user and current_user.is_authenticated:
                        existing.released_by = current_user.id
                existing.save()
                mirror_heavy_document(project.id, existing)
                updated_count += 1
            else:
                # 新建 record 路径: 优先从 record.full_dir 读, 退化到 extra_fields.full_dir
                _fd = sanitize_str(record.get('full_dir')) or ''
                if not _fd:
                    _ne = record.get('extra_fields')
                    if isinstance(_ne, dict):
                        _fd = _ne.get('full_dir', '') or ''
                    elif isinstance(_ne, str):
                        try:
                            _ne2 = json.loads(_ne)
                            if isinstance(_ne2, dict):
                                _fd = _ne2.get('full_dir', '') or ''
                        except (ValueError, TypeError):
                            _fd = ''
                _rd = record.get('release_dir')
                # 整批 default_release_dir 优先于 CSV 自带值
                if default_release_dir is not None:
                    _rd_final = str(sanitize_str(default_release_dir))[:500] if str(default_release_dir).strip() else ''
                elif _rd:
                    _rd_final = str(sanitize_str(_rd))[:500]
                else:
                    _rd_final = ''
                qor = QorRecord(
                    module_id=mod.id,
                    version=rec_version,
                    full_dir=str(_fd)[:500] if _fd else '',
                    source_file=sanitize_str(source_filename) or '',
                    owner_id=owner_id,
                    release_dir=_rd_final,
                    version_description=sanitize_str(record.get('version_description')) or '',
                )
                for f in FLOAT_FIELDS_SET:
                    if f in record:
                        cleaned = sanitize_value(f, record[f])
                        if cleaned is not None:
                            setattr(qor, f, cleaned)
                _sync_congestion(qor)
                qor.extra_fields = _coerce_extra_fields(record.get('extra_fields'))
                # comment 存入 extra_fields (与 to_dict 读取路径一致)
                _comment = sanitize_str(record.get('comment'))
                _ef = None  # 初始化, 避免 UnboundLocalError
                if _comment:
                    _ef = qor.extra_fields
                    if isinstance(_ef, str) and _ef.strip():
                        try:
                            _ef = json.loads(_ef)
                        except (ValueError, TypeError):
                            _ef = {}
                    elif not isinstance(_ef, dict):
                        _ef = {}
                    _ef['comment'] = _comment
                    qor.extra_fields = _coerce_extra_fields(_ef)
                # full_dir 同步到 extra_fields (确保 CSV/JSON 数据融合后统一)
                if _fd and not (isinstance(_ef, dict) and _ef.get('full_dir')):
                    _ef2 = qor.extra_fields
                    if isinstance(_ef2, str) and _ef2.strip():
                        try:
                            _ef2 = json.loads(_ef2)
                        except (ValueError, TypeError):
                            _ef2 = {}
                    elif not isinstance(_ef2, dict):
                        _ef2 = {}
                    _ef2['full_dir'] = _fd
                    qor.extra_fields = _coerce_extra_fields(_ef2)
                # 校验 scenarios 数据规则 (记录警告, 不阻断导入)
                _ef_dict = record.get('extra_fields')
                if isinstance(_ef_dict, dict):
                    _validate_extra_fields_scenario_rules(_ef_dict, f'new:{mod.name}/{rec_version}')
                if mark_released:
                    qor.is_released = True
                    qor.released_at = datetime.utcnow()
                    if current_user and current_user.is_authenticated:
                        qor.released_by = current_user.id
                qor.save()
                mirror_heavy_document(project.id, qor)
                saved_count += 1
        except Exception as e:
            from django_app.repositories import RepositoryError
            if isinstance(e, RepositoryError):
                raise
            import traceback
            _log.error("save_records_to_db: 处理记录时出错 - record keys: %s, error: %s, traceback: %s",
                       list(record.keys())[:10] if record else 'N/A', str(e), traceback.format_exc())
            skipped_count += 1
            continue

    _log.info("save_records_to_db: 处理完成 - saved=%d, updated=%d, skipped=%d",
              saved_count, updated_count, skipped_count)
    return saved_count, skipped_count, updated_count


def merge_power_to_db(records, project, module_id, version, source_filename,
                       mark_released=False, owner_id=None, current_user=None):
    """将功耗数据合并到已有 QorRecord

    匹配策略: (module_id, version) 组合, 若指定 module_id 则全用该模块。
    若匹配到已有记录, 仅更新功耗字段; 若无匹配, 则新建带功耗数据的记录。

    Returns:
        (merged_count, created_count)
    """
    merged_count = 0
    created_count = 0
    module_cache = {}

    power_fields = [
        'power_internal', 'power_switching', 'power_leakage', 'power_total',
        'target_frequency', 'achieved_frequency',
    ]

    for record in records:
        mod_name = record.get('module_name')
        if module_id:
            mod = Module.objects.filter(id=module_id).first()
        elif mod_name:
            if mod_name in module_cache:
                mod = module_cache[mod_name]
            else:
                mod = Module.objects.filter(project_id=project.id, name=mod_name).first()
                if not mod:
                    continue
                module_cache[mod_name] = mod
        else:
            continue

        if not mod:
            continue

        full_dir = record.get('full_dir')
        if not full_dir and isinstance(record.get('extra_fields'), dict):
            full_dir = record['extra_fields'].get('full_dir')
        rec_version = derive_version(full_dir)

        existing = QorRecord.objects.filter(module_id=mod.id, version=rec_version).first()

        if existing:
            updated_any = False
            for f in power_fields:
                if f in record and record[f] is not None:
                    setattr(existing, f, record[f])
                    updated_any = True

            if record.get('extra_fields'):
                cur_extra = existing.extra_fields or {}
                if isinstance(cur_extra, str):
                    try:
                        cur_extra = json.loads(cur_extra)
                    except Exception:
                        cur_extra = {}
                new_extra = record['extra_fields']
                if isinstance(new_extra, str):
                    try:
                        new_extra = json.loads(new_extra)
                    except Exception:
                        new_extra = {}
                if isinstance(new_extra, dict):
                    cur_extra.update(new_extra)
                # 序列化为 JSON 字符串 (extra_fields 列是 Text, 不接受 dict)
                try:
                    existing.extra_fields = json.dumps(cur_extra, ensure_ascii=False)
                except (TypeError, ValueError):
                    existing.extra_fields = json.dumps(str(cur_extra), ensure_ascii=False)
                updated_any = True

            if updated_any:
                if mark_released:
                    existing.is_released = True
                    if not existing.released_at:
                        existing.released_at = datetime.utcnow()
                    if not existing.released_by and current_user and current_user.is_authenticated:
                        existing.released_by = current_user.id
                existing.save()
                mirror_heavy_document(project.id, existing)
                merged_count += 1
        else:
            _fd = ''
            _ne = record.get('extra_fields')
            if isinstance(_ne, dict):
                _fd = _ne.get('full_dir', '') or ''
            elif isinstance(_ne, str):
                try:
                    _ne2 = json.loads(_ne)
                    if isinstance(_ne2, dict):
                        _fd = _ne2.get('full_dir', '') or ''
                except (ValueError, TypeError):
                    _fd = ''
            qor = QorRecord(
                module_id=mod.id,
                version=rec_version,
                full_dir=str(_fd)[:500] if _fd else '',
                source_file=source_filename or '',
                owner_id=owner_id,
            )
            for f in power_fields:
                if f in record and record[f] is not None:
                    setattr(qor, f, record[f])
            qor.extra_fields = _coerce_extra_fields(record.get('extra_fields'))
            if mark_released:
                qor.is_released = True
                qor.released_at = datetime.utcnow()
                if current_user and current_user.is_authenticated:
                    qor.released_by = current_user.id
            qor.save()
            mirror_heavy_document(project.id, qor)
            created_count += 1

    return merged_count, created_count


def save_violations_to_db(records, project, module_id, version, source_filename, timing_group=None):
    """将违例路径数据保存到数据库

    匹配策略: 按 (module_id, version) 查找已有 QorRecord, 将违例路径关联到该记录。
    若 QorRecord 不存在, 则跳过。

    Returns:
        (saved_count, skipped_count)
    """
    saved_count = 0
    skipped_count = 0
    module_cache = {}

    MAX_STR_LEN = 500

    def sanitize_str(val):
        if val is None:
            return None
        s = str(val).strip()
        return s[:MAX_STR_LEN] if len(s) > MAX_STR_LEN else (s if s else None)

    for record in records:
        try:
            mod_name = sanitize_str(record.get('module_name'))
            if module_id:
                mod = Module.objects.filter(id=module_id).first()
            elif mod_name:
                if mod_name in module_cache:
                    mod = module_cache[mod_name]
                else:
                    mod = Module.objects.filter(project_id=project.id, name=mod_name).first()
                    module_cache[mod_name] = mod
            else:
                mod = None

            if not mod:
                skipped_count += 1
                continue

            full_dir = record.get('full_dir')
            if not full_dir and isinstance(record.get('extra_fields'), dict):
                full_dir = record['extra_fields'].get('full_dir')
            rec_version = derive_version(full_dir)

            qor_rec = QorRecord.objects.filter(module_id=mod.id, version=rec_version).first()
            if not qor_rec:
                skipped_count += 1
                continue

            tg = sanitize_str(record.get('timing_group')) or sanitize_str(timing_group) or 'default'

            vp = ViolationPath(
                qor_record_id=qor_rec.id,
                timing_group=tg,
                startpoint=sanitize_str(record.get('startpoint')),
                endpoint=sanitize_str(record.get('endpoint')),
                slack=record.get('slack'),
                depth=record.get('depth'),
                pure_depth=record.get('pure_depth'),
                cell_delay=record.get('cell_delay'),
                net_delay=record.get('net_delay'),
                et_slack=record.get('et_slack'),
                st_slack=record.get('st_slack'),
                st_fanin=record.get('st_fanin'),
                st_fanout=record.get('st_fanout'),
                et_fanin=record.get('et_fanin'),
                et_fanout=record.get('et_fanout'),
                source_file=sanitize_str(source_filename),
            )
            vp.save()
            mirror_heavy_document(project.id, vp)
            saved_count += 1
        except Exception as e:
            from django_app.repositories import RepositoryError
            if isinstance(e, RepositoryError):
                raise
            skipped_count += 1
            continue

    return saved_count, skipped_count


def save_notes_to_db(records, project, module_id, version, source_filename, full_dir=None):
    """将 Run 备注保存到数据库

    匹配策略:
      按 (module_id, version) 查找已有 QorRecord, 若 full_dir 不为空则进一步按
      QorRecord.extra_fields.full_dir 匹配, 找不到则回退到该 module+version 的
      第一条 QorRecord。

    覆盖策略 (再次上传时覆盖旧数据):
      按 (qor_record_id, full_dir) 删除旧备注后写入新备注。

    Returns:
        (saved_count, skipped_count)
    """
    saved_count = 0
    skipped_count = 0
    module_cache = {}
    cleared_keys = set()

    MAX_STR_LEN = 2000

    def sanitize_str(val, max_len=500):
        if val is None:
            return None
        s = str(val).strip()
        return s[:max_len] if len(s) > max_len else (s if s else None)

    for record in records:
        try:
            mod_name = sanitize_str(record.get('module_name'))
            if module_id:
                mod = Module.objects.filter(id=module_id).first()
            elif mod_name:
                if mod_name in module_cache:
                    mod = module_cache[mod_name]
                else:
                    mod = Module.objects.filter(project_id=project.id, name=mod_name).first()
                    module_cache[mod_name] = mod
            else:
                mod = None

            if not mod:
                skipped_count += 1
                continue

            row_full_dir = sanitize_str(record.get('full_dir'), MAX_STR_LEN) or full_dir
            rec_version = derive_version(row_full_dir)
            row_full_dir = normalize_full_dir(row_full_dir)

            # 查找关联的 QorRecord
            qor_rec = QorRecord.objects.filter(module_id=mod.id, version=rec_version).first()
            if not qor_rec:
                skipped_count += 1
                continue

            # 若指定 full_dir, 进一步按 extra_fields.full_dir 匹配
            if row_full_dir:
                try:
                    extra = qor_rec.extra_fields
                    if isinstance(extra, str):
                        extra = json.loads(extra) if extra else {}
                    if isinstance(extra, dict) and extra.get('full_dir') == row_full_dir:
                        pass  # 找到精确匹配
                    else:
                        # 尝试在该 module+version 下找其他匹配
                        candidates = QorRecord.objects.filter(
                            module_id=mod.id, version=rec_version,
                        )
                        matched = None
                        for c in candidates:
                            try:
                                e = c.extra_fields
                                if isinstance(e, str):
                                    e = json.loads(e) if e else {}
                                if isinstance(e, dict) and e.get('full_dir') == row_full_dir:
                                    matched = c
                                    break
                            except Exception:
                                continue
                        if matched:
                            qor_rec = matched
                except Exception:
                    pass

            # 覆盖旧备注
            key = (qor_rec.id, row_full_dir or '')
            if key not in cleared_keys:
                try:
                    if row_full_dir:
                        RunNote.objects.filter(
                            qor_record_id=qor_rec.id, full_dir=row_full_dir,
                        ).delete()
                    else:
                        RunNote.objects.filter(
                            qor_record_id=qor_rec.id,
                        ).filter(
                            Q(full_dir__isnull=True) | Q(full_dir=''),
                        ).delete()
                    cleared_keys.add(key)
                except Exception:
                    pass

            note = RunNote(
                qor_record_id=qor_rec.id,
                item=sanitize_str(record.get('item'), MAX_STR_LEN) or '',
                description=sanitize_str(record.get('description'), MAX_STR_LEN) or '',
                full_dir=sanitize_str(row_full_dir, MAX_STR_LEN),
            )
            note.save()
            mirror_heavy_document(project.id, note)
            saved_count += 1
        except Exception as e:
            from django_app.repositories import RepositoryError
            if isinstance(e, RepositoryError):
                raise
            skipped_count += 1
            continue

    return saved_count, skipped_count