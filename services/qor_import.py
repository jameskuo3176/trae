"""QoR 数据导入服务

封装数据保存/合并/校验等业务逻辑, 供多个路由复用。
"""
import json
from datetime import datetime

from flask_login import current_user

from models import db, Module, QorRecord, ViolationPath


def _coerce_extra_fields(value):
    """规范化 extra_fields: 接受 dict / JSON 字符串 / None.

    QorRecord.extra_fields 是 Text 列, SQLAlchemy 直接绑定 dict 会触发
    InterfaceError (SQLite 不支持 dict 类型). 统一在写入前序列化为 JSON 字符串.
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
                        mark_released=False, owner_id=None, default_release_dir=None):
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
                     'net_count', 'sequential_cell_count'):
            return int(v)
        return v

    def sanitize_str(val):
        if val is None:
            return None
        s = str(val).strip()
        if len(s) > MAX_STR_LEN:
            return s[:MAX_STR_LEN]
        return s if s else None

    for record in records:
        try:
            mod_name = sanitize_str(record.get('module_name'))
            if not mod_name:
                if module_id:
                    mod = Module.query.get(module_id)
                    if not mod:
                        skipped_count += 1
                        continue
                else:
                    skipped_count += 1
                    continue
            else:
                if module_id:
                    mod = Module.query.get(module_id)
                else:
                    if mod_name in module_cache:
                        mod = module_cache[mod_name]
                    else:
                        mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                        if not mod:
                            mod = Module(project_id=project.id, name=mod_name)
                            db.session.add(mod)
                            db.session.flush()
                        module_cache[mod_name] = mod

            rec_version = sanitize_str(record.get('version')) or sanitize_str(version) or 'v1'

            # 去重
            existing = QorRecord.query.filter_by(
                module_id=mod.id, version=rec_version,
            ).first()

            if existing:
                for f in FLOAT_FIELDS_SET:
                    if f in record:
                        cleaned = sanitize_value(f, record[f])
                        if cleaned is not None:
                            setattr(existing, f, cleaned)
                _sync_congestion(existing)
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
                    # 序列化为 JSON 字符串 (extra_fields 列是 Text, 不接受 dict)
                    try:
                        existing.extra_fields = json.dumps(cur, ensure_ascii=False)
                    except (TypeError, ValueError):
                        existing.extra_fields = json.dumps(str(cur), ensure_ascii=False)
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
                    if not existing.released_by and current_user.is_authenticated:
                        existing.released_by = current_user.id
                updated_count += 1
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
                _rd = record.get('release_dir')
                # 整批 default_release_dir 优先于 CSV 自带值
                if default_release_dir is not None:
                    _rd_final = str(sanitize_str(default_release_dir))[:500] if str(default_release_dir).strip() else None
                elif _rd:
                    _rd_final = str(sanitize_str(_rd))[:500]
                else:
                    _rd_final = None
                qor = QorRecord(
                    module_id=mod.id,
                    version=rec_version,
                    full_dir=str(_fd)[:500] if _fd else None,
                    source_file=sanitize_str(source_filename),
                    owner_id=owner_id,
                    release_dir=_rd_final,
                )
                for f in FLOAT_FIELDS_SET:
                    if f in record:
                        cleaned = sanitize_value(f, record[f])
                        if cleaned is not None:
                            setattr(qor, f, cleaned)
                _sync_congestion(qor)
                qor.extra_fields = _coerce_extra_fields(record.get('extra_fields'))
                if mark_released:
                    qor.is_released = True
                    qor.released_at = datetime.utcnow()
                    if current_user.is_authenticated:
                        qor.released_by = current_user.id
                db.session.add(qor)
                saved_count += 1
        except Exception:
            skipped_count += 1
            continue

    return saved_count, skipped_count, updated_count


def merge_power_to_db(records, project, module_id, version, source_filename,
                       mark_released=False, owner_id=None):
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
            mod = Module.query.get(module_id)
        elif mod_name:
            if mod_name in module_cache:
                mod = module_cache[mod_name]
            else:
                mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                if not mod:
                    continue
                module_cache[mod_name] = mod
        else:
            continue

        if not mod:
            continue

        rec_version = record.get('version') or version or 'v1'

        existing = QorRecord.query.filter_by(module_id=mod.id, version=rec_version).first()

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
                    if not existing.released_by and current_user.is_authenticated:
                        existing.released_by = current_user.id
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
                full_dir=str(_fd)[:500] if _fd else None,
                source_file=source_filename,
                owner_id=owner_id,
            )
            for f in power_fields:
                if f in record and record[f] is not None:
                    setattr(qor, f, record[f])
            qor.extra_fields = _coerce_extra_fields(record.get('extra_fields'))
            if mark_released:
                qor.is_released = True
                qor.released_at = datetime.utcnow()
                if current_user.is_authenticated:
                    qor.released_by = current_user.id
            db.session.add(qor)
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
                mod = Module.query.get(module_id)
            elif mod_name:
                if mod_name in module_cache:
                    mod = module_cache[mod_name]
                else:
                    mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                    module_cache[mod_name] = mod
            else:
                mod = None

            if not mod:
                skipped_count += 1
                continue

            rec_version = sanitize_str(record.get('version')) or sanitize_str(version) or 'v1'

            qor_rec = QorRecord.query.filter_by(module_id=mod.id, version=rec_version).first()
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
            db.session.add(vp)
            saved_count += 1
        except Exception:
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
    from models import RunNote
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
                mod = Module.query.get(module_id)
            elif mod_name:
                if mod_name in module_cache:
                    mod = module_cache[mod_name]
                else:
                    mod = Module.query.filter_by(project_id=project.id, name=mod_name).first()
                    module_cache[mod_name] = mod
            else:
                mod = None

            if not mod:
                skipped_count += 1
                continue

            rec_version = sanitize_str(record.get('version')) or sanitize_str(version) or 'v1'
            row_full_dir = sanitize_str(record.get('full_dir'), MAX_STR_LEN) or full_dir

            # 查找关联的 QorRecord
            qor_rec = QorRecord.query.filter_by(module_id=mod.id, version=rec_version).first()
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
                        candidates = QorRecord.query.filter_by(
                            module_id=mod.id, version=rec_version,
                        ).all()
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
                        RunNote.query.filter_by(
                            qor_record_id=qor_rec.id, full_dir=row_full_dir,
                        ).delete()
                    else:
                        RunNote.query.filter_by(
                            qor_record_id=qor_rec.id,
                        ).filter(
                            (RunNote.full_dir.is_(None)) | (RunNote.full_dir == ''),
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
            db.session.add(note)
            saved_count += 1
        except Exception:
            skipped_count += 1
            continue

    return saved_count, skipped_count
