"""趋势预警逻辑

在新数据上传后触发告警检查, 对比历史趋势, 若指标恶化则生成 AlertEvent。

WNS (Worst Negative Slack) 恶化判断:
  - WNS 变小 (更负) = 恶化 (时序更差)
  - 变化幅度超过 sensitivity (如20%) 则触发告警
  - 超过绝对阈值 threshold 则触发 critical

其他指标:
  - area_total 增大 = 恶化
  - power_total 增大 = 恶化
  - tns_setup 变小 = 恶化
"""
from models import db, QorRecord, AlertRule, AlertEvent, Module
from datetime import datetime


# 指标恶化方向: True=增大恶化, False=减小恶化
# WNS/TNS: 减小(更负)恶化; 面积/功耗: 增大恶化
METRIC_WORSEN_DIRECTION = {
    'wns_setup': False,   # 减小=恶化
    'wns_hold': False,
    'tns_setup': False,
    'tns_hold': False,
    'area_total': True,   # 增大=恶化
    'area_combinational': True,
    'area_sequential': True,
    'power_total': True,
    'power_internal': True,
    'power_switching': True,
    'power_leakage': True,
    'cell_count': True,
    'instance_count': True,
}


def _is_worsened(metric, old_val, new_val):
    """判断指标是否恶化

    返回: (is_worsened, delta)
    delta > 0 表示恶化幅度
    """
    if old_val is None or new_val is None:
        return False, 0.0

    worsen_when_increase = METRIC_WORSEN_DIRECTION.get(metric, True)
    if worsen_when_increase:
        delta = new_val - old_val
    else:
        delta = old_val - new_val  # 减小=正delta=恶化

    return delta > 0, delta


def _calc_relative_change(old_val, new_val):
    """计算相对变化幅度 (绝对值)"""
    if old_val is None or old_val == 0:
        return abs(new_val) if new_val is not None else 0.0
    return abs((new_val - old_val) / old_val)


def check_alerts_for_new_record(qor_record):
    """检查新记录是否触发告警规则

    在数据上传 commit 后调用。
    """
    if not qor_record or not qor_record.module_id:
        return []

    mod = qor_record.module
    if not mod:
        return []

    project_id = mod.project_id

    # 查找适用于此项目/模块的启用规则
    rules = AlertRule.query.filter_by(
        project_id=project_id, enabled=True
    ).filter(
        (AlertRule.module_id.is_(None)) | (AlertRule.module_id == qor_record.module_id)
    ).all()

    if not rules:
        return []

    triggered_events = []

    for rule in rules:
        metric = rule.metric
        new_value = getattr(qor_record, metric, None)
        if new_value is None:
            continue

        # threshold 模式: 仅比较绝对值
        if rule.direction == 'threshold' and rule.threshold is not None:
            worsen_when_increase = METRIC_WORSEN_DIRECTION.get(metric, True)
            exceeded = (new_value > rule.threshold) if worsen_when_increase else (new_value < rule.threshold)
            if exceeded:
                severity = 'critical' if metric.startswith('wns') and new_value < -0.5 else 'warning'
                event = AlertEvent(
                    rule_id=rule.id,
                    qor_record_id=qor_record.id,
                    module_id=qor_record.module_id,
                    new_value=new_value,
                    delta=None,
                    message=f"{mod.name}/{qor_record.version}: {metric}={new_value} 超过阈值 {rule.threshold}",
                    severity=severity,
                )
                db.session.add(event)
                triggered_events.append(event)
            continue

        # trend 模式: 与历史版本对比
        # 获取该模块历史记录 (按时间正序)
        history = QorRecord.query.filter_by(module_id=qor_record.module_id).order_by(
            QorRecord.recorded_at.desc()
        ).limit(rule.window_size + 1).all()

        # 排除当前记录, 取前 window_size 条
        old_records = [r for r in history if r.id != qor_record.id][:rule.window_size]
        if not old_records:
            continue

        # 取最近的历史值作为对比基准
        old_value = getattr(old_records[0], metric, None)
        if old_value is None:
            continue

        is_worsened, delta = _is_worsened(metric, old_value, new_value)
        rel_change = _calc_relative_change(old_value, new_value)

        should_alert = False
        if rule.direction == 'worsen' and is_worsened:
            # 检查变化幅度是否超过 sensitivity
            if rel_change >= rule.sensitivity or abs(delta) >= 0.001:
                should_alert = True
        elif rule.direction == 'improve' and not is_worsened:
            should_alert = rel_change >= rule.sensitivity

        if should_alert:
            # 严重程度: WNS 恶化超过 0.1ns 为 critical
            if metric.startswith('wns') and delta > 0.1:
                severity = 'critical'
            elif rel_change >= rule.sensitivity * 2:
                severity = 'critical'
            else:
                severity = 'warning'

            event = AlertEvent(
                rule_id=rule.id,
                qor_record_id=qor_record.id,
                module_id=qor_record.module_id,
                old_value=old_value,
                new_value=new_value,
                delta=delta,
                message=(f"{mod.name}/{qor_record.version}: {metric} "
                         f"从 {old_value:.4f} 变为 {new_value:.4f} "
                         f"({'恶化' if is_worsened else '改善'} {rel_change:.1%})"),
                severity=severity,
            )
            db.session.add(event)
            triggered_events.append(event)

    if triggered_events:
        db.session.commit()

    return triggered_events
