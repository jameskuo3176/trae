# -*- coding: utf-8 -*-
"""两版 Run 违例路径 CSV 对比工具（PyQt5 桌面版）。

功能：
 1. 图形界面导入两版 run 的违例路径 CSV 文件（支持拖拽、浏览选择）
 2. CSV 解析：列名不区分大小写/空格/下划线，可位置映射兜底，自动识别编码
 3. 路径差异分析：按 (timing_group, startpoint, endpoint) 识别三类状态
      - 新增路径：仅在新版出现
      - 修复路径：仅在旧版出现
      - 持续违例路径：两版均出现（并给出 Δslack 改善/恶化判定）
 4. 可视化：颜色编码表格 + 汇总统计 + 状态筛选 + 关键字搜索
 5. 导出：对比结果 CSV / 汇总报告 TXT

用法：
   python csv_violation_diff_tool.py          # 打开图形界面
   python csv_violation_diff_tool.py --selftest   # 命令行自检（不启动界面）
"""

import csv
import os
import re
import sys

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QBrush, QFont, QPalette
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QFrame, QHeaderView,
    QGroupBox, QAbstractItemView, QSplitter, QSizePolicy, QStyle,
)

APP_TITLE = u'违例路径 CSV 对比工具'
VERSION = u'1.0.0'

# =====================================================================
# 数据模型
# =====================================================================


class Violation(object):
    """一条违例路径（兼容 Python 3.5+，无需 dataclasses）。"""

    def __init__(self, timing_group='default', startpoint='', endpoint='',
                 slack=None, depth=None, pure_depth=None, cell_delay=None,
                 net_delay=None, et_slack=None, st_slack=None,
                 st_fanin=None, st_fanout=None, et_fanin=None,
                 et_fanout=None, type='', source_file=''):
        self.timing_group = timing_group
        self.startpoint = startpoint
        self.endpoint = endpoint
        self.slack = slack
        self.depth = depth
        self.pure_depth = pure_depth
        self.cell_delay = cell_delay
        self.net_delay = net_delay
        self.et_slack = et_slack
        self.st_slack = st_slack
        self.st_fanin = st_fanin
        self.st_fanout = st_fanout
        self.et_fanin = et_fanin
        self.et_fanout = et_fanout
        self.type = type
        self.source_file = source_file


class ParseResult(object):
    """CSV 解析结果。"""

    def __init__(self, path, timing_group, rows=None, skipped=0, columns=None):
        self.path = path
        self.timing_group = timing_group
        self.rows = rows if rows is not None else []
        self.skipped = skipped
        self.columns = columns if columns is not None else []


class DiffRow(object):
    """一行差异结果。"""

    def __init__(self, status, timing_group, startpoint, endpoint,
                 base_slack=None, target_slack=None, delta=None,
                 base_depth=None, target_depth=None):
        self.status = status             # 'new' | 'fixed' | 'persistent'
        self.timing_group = timing_group
        self.startpoint = startpoint
        self.endpoint = endpoint
        self.base_slack = base_slack     # 旧版 slack
        self.target_slack = target_slack # 新版 slack
        self.delta = delta               # target - base（持续违例时有效）
        self.base_depth = base_depth
        self.target_depth = target_depth


class DiffResult(object):
    """两版对比的完整结果。"""

    def __init__(self, old, new, bus_merge, all_rows=None, new_count=0,
                 fixed_count=0, persistent_count=0, improved_count=0,
                 worsened_count=0, same_count=0):
        self.old = old
        self.new = new
        self.bus_merge = bus_merge
        self.all_rows = all_rows if all_rows is not None else []
        self.new_count = new_count
        self.fixed_count = fixed_count
        self.persistent_count = persistent_count
        self.improved_count = improved_count
        self.worsened_count = worsened_count
        self.same_count = same_count


# =====================================================================
# CSV 解析
# =====================================================================

class CsvFormatError(Exception):
    pass


class CsvEmptyError(Exception):
    pass


# 标准列顺序（表头无法识别时按位置映射）
FIELD_ORDER = ['startpoint', 'endpoint', 'slack', 'depth', 'pure_depth',
               'cell_delay', 'net_delay', 'et_slack', 'st_slack',
               'st_fanin', 'st_fanout', 'et_fanin', 'et_fanout',
               'type', 'source_file']

# 列名别名（规范化后匹配，忽略大小写/空格/下划线/连字符/斜杠）
ALIASES = {
    'startpoint': {'startpoint', 'start', 'source', 'beginpoint', 'startpointname'},
    'endpoint': {'endpoint', 'end', 'sink', 'endpointname'},
    'slack': {'slack', 'slackns', 'slackvalue'},
    'timing_group': {'timinggroup', 'group', 'clockgroup', 'clkgroup',
                     'clkdomain', 'tg'},
    'depth': {'depth', 'level', 'levels'},
    'pure_depth': {'puredepth', 'logicdepth'},
    'cell_delay': {'celldelay'},
    'net_delay': {'netdelay'},
    'et_slack': {'etslack'},
    'st_slack': {'stslack'},
    'st_fanin': {'stfanin'},
    'st_fanout': {'stfanout'},
    'et_fanin': {'etfanin'},
    'et_fanout': {'etfanout'},
    'type': {'type', 'checks', 'violationtype'},
    'source_file': {'sourcefile', 'srcfile', 'filename'},
}


def _norm_key(name):
    return re.sub(r'[\s_\-/]+', '', str(name)).lower()


def _to_float(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(value):
    f = _to_float(value)
    if f is None:
        return None
    return int(f)


def resolve_columns(headers):
    """表头 -> 规范字段名映射。优先别名匹配；核心列缺失时按标准顺序位置兜底。"""
    mapping = {}
    used = set()
    for i, h in enumerate(headers):
        key = _norm_key(h)
        if not key:
            continue
        for field_name, aliases in ALIASES.items():
            if key in aliases and field_name not in used:
                mapping[i] = field_name
                used.add(field_name)
                break
    if not {'startpoint', 'endpoint'}.issubset(set(mapping.values())):
        rest = [f for f in FIELD_ORDER if f not in used]
        j = 0
        for i in range(len(headers)):
            if i in mapping:
                continue
            if j < len(rest):
                mapping[i] = rest[j]
                j += 1
    return mapping


def read_csv_rows(path):
    """读取 CSV 全部行（自动尝试多种编码）。"""
    if not os.path.isfile(path):
        raise CsvFormatError(u'文件不存在：%s' % path)
    if not path.lower().endswith('.csv'):
        raise CsvFormatError(u'不是 CSV 文件：%s' % path)
    last_err = None
    for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc, newline='') as f:
                return list(csv.reader(f))
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise CsvFormatError(u'无法解码文件（utf-8/gbk 均失败）：%s' % last_err)


def default_timing_group_from_filename(path):
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r'_violations$', '', base, flags=re.IGNORECASE)
    return base or 'default'


def parse_csv(path, timing_group_hint=None):
    """解析违例路径 CSV，返回 ParseResult。

    timing_group_hint: 为 None 时使用 'default'；传入空串时由文件名推导。
    """
    raw = read_csv_rows(path)
    if not raw:
        raise CsvEmptyError(u'文件为空：%s' % path)

    headers = raw[0]
    mapping = resolve_columns(headers)
    if not {'startpoint', 'endpoint'}.issubset(set(mapping.values())):
        raise CsvFormatError(
            u'%s：未找到 STARTPOINT / ENDPOINT 列（当前列：%s）'
            % (os.path.basename(path), u', '.join(h for h in headers if h)))

    tg_default = (timing_group_hint or default_timing_group_from_filename(path)
                  if timing_group_hint is not None else 'default')

    result = ParseResult(path=path, timing_group=tg_default,
                         columns=[mapping.get(i, h) for i, h in enumerate(headers)])
    skipped = 0
    for lineno, line in enumerate(raw[1:], start=2):
        if not line or all(not c.strip() for c in line):
            skipped += 1
            continue
        row = {}
        for i, field_name in mapping.items():
            row[field_name] = line[i].strip() if i < len(line) else ''

        sp = row.get('startpoint', '')
        ep = row.get('endpoint', '')
        if not sp and not ep:
            skipped += 1
            continue

        v = Violation(
            startpoint=sp,
            endpoint=ep,
            timing_group=row.get('timing_group') or tg_default,
            slack=_to_float(row.get('slack')),
            depth=_to_int(row.get('depth')),
            pure_depth=_to_int(row.get('pure_depth')),
            cell_delay=_to_float(row.get('cell_delay')),
            net_delay=_to_float(row.get('net_delay')),
            et_slack=_to_float(row.get('et_slack')),
            st_slack=_to_float(row.get('st_slack')),
            st_fanin=_to_int(row.get('st_fanin')),
            st_fanout=_to_int(row.get('st_fanout')),
            et_fanin=_to_int(row.get('et_fanin')),
            et_fanout=_to_int(row.get('et_fanout')),
            type=row.get('type', ''),
            source_file=os.path.basename(path),
        )
        result.rows.append(v)

    if not result.rows:
        raise CsvEmptyError(u'%s：未解析到任何违例路径数据' % os.path.basename(path))

    result.skipped = skipped
    return result


# =====================================================================
# 差异分析算法
# =====================================================================

BUS_RE = re.compile(r'\[\d+\]')


def path_key(v, bus_merge):
    sp = BUS_RE.sub('[*]', v.startpoint) if bus_merge else v.startpoint
    ep = BUS_RE.sub('[*]', v.endpoint) if bus_merge else v.endpoint
    return (v.timing_group or 'default', sp, ep)


def _sort_key(row):
    # 排序：先按状态（新增>修复>持续恶化>持续改善），再按 slack 由差到好
    order = {'new': 0, 'fixed': 1, 'persistent': 2}
    slack = row.delta if (row.status == 'persistent' and row.delta is not None) else None
    return (order.get(row.status, 3), row.timing_group,
            slack if slack is not None else 0.0, row.startpoint)


def compute_diff(old_res, new_res, bus_merge):
    old_map = {path_key(v, bus_merge): v for v in old_res.rows}
    new_map = {path_key(v, bus_merge): v for v in new_res.rows}

    old_keys, new_keys = set(old_map), set(new_map)

    def make(status, base_v, target_v):
        base_slack = base_v.slack if base_v else None
        target_slack = target_v.slack if target_v else None
        delta = None
        if status == 'persistent' and base_slack is not None and target_slack is not None:
            delta = target_slack - base_slack
        return DiffRow(
            status=status,
            timing_group=(target_v or base_v).timing_group,
            startpoint=(target_v or base_v).startpoint,
            endpoint=(target_v or base_v).endpoint,
            base_slack=base_slack,
            target_slack=target_slack,
            delta=delta,
            base_depth=base_v.depth if base_v else None,
            target_depth=target_v.depth if target_v else None,
        )

    rows = []
    for k in sorted(new_keys - old_keys, key=lambda k: k):
        rows.append(make('new', None, new_map[k]))
    for k in sorted(old_keys - new_keys, key=lambda k: k):
        rows.append(make('fixed', old_map[k], None))
    for k in sorted(old_keys & new_keys, key=lambda k: k):
        rows.append(make('persistent', old_map[k], new_map[k]))

    improved = sum(1 for r in rows if r.status == 'persistent'
                   and r.delta is not None and r.delta > 0)
    worsened = sum(1 for r in rows if r.status == 'persistent'
                   and r.delta is not None and r.delta < 0)
    same = sum(1 for r in rows if r.status == 'persistent'
               and (r.delta is None or r.delta == 0))

    rows.sort(key=_sort_key)

    return DiffResult(
        old=old_res, new=new_res, bus_merge=bus_merge, all_rows=rows,
        new_count=len(new_keys - old_keys),
        fixed_count=len(old_keys - new_keys),
        persistent_count=len(old_keys & new_keys),
        improved_count=improved, worsened_count=worsened, same_count=same,
    )


# =====================================================================
# 后台对比线程（保持界面响应）
# =====================================================================

class CompareWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, old_path, new_path, old_group, new_group, bus_merge,
                 parent=None):
        super().__init__(parent)
        self.old_path = old_path
        self.new_path = new_path
        self.old_group = old_group
        self.new_group = new_group
        self.bus_merge = bus_merge

    def run(self):
        try:
            old = parse_csv(self.old_path, self.old_group)
            new = parse_csv(self.new_path, self.new_group)
            result = compute_diff(old, new, self.bus_merge)
            self.done.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# =====================================================================
# 界面
# =====================================================================

# 颜色编码
COLOR_NEW_BG = '#ffe0b2'       # 新增：浅橙
COLOR_FIXED_BG = '#c8e6c9'     # 修复：浅绿
COLOR_IMPROVED_BG = '#dcedc8'  # 持续-改善：浅黄绿
COLOR_WORSENED_BG = '#ffcdd2'  # 持续-恶化：浅红
COLOR_ROW_BG = '#ffffff'
COLOR_NEW_FG = '#e65100'
COLOR_FIXED_FG = '#2e7d32'
COLOR_PERSISTENT_FG = '#1565c0'

STATUS_LABEL = {'new': u'新增', 'fixed': u'修复', 'persistent': u'持续违例'}

HEADERS = [u'状态', u'Timing Group', u'Startpoint', u'Endpoint',
           u'旧版 Slack', u'新版 Slack', u'Δ Slack', u'旧版 Depth', u'新版 Depth']


class DropLineEdit(QLineEdit):
    """支持拖拽文件的输入框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText(u'点击"浏览..."或将 CSV 文件拖拽到此处')
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.setText(path)
                break


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.result = None
        self.worker = None
        self._search_timer = None
        self._build_ui()

    # ---------- UI 构建 ----------
    def _build_ui(self):
        self.setWindowTitle(u'%s  v%s' % (APP_TITLE, VERSION))
        self.resize(1080, 680)
        self.setMinimumSize(900, 560)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # 1. 文件选择
        self.edit_old = DropLineEdit()
        self.edit_new = DropLineEdit()
        btn_old = QPushButton(u'浏览…')
        btn_new = QPushButton(u'浏览…')
        btn_old.clicked.connect(lambda: self._browse(self.edit_old))
        btn_new.clicked.connect(lambda: self._browse(self.edit_new))
        self.edit_old.textChanged.connect(self._on_path_changed)
        self.edit_new.textChanged.connect(self._on_path_changed)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(QLabel(u'旧版 CSV：'), 0, 0)
        grid.addWidget(self.edit_old, 0, 1)
        grid.addWidget(btn_old, 0, 2)
        grid.addWidget(QLabel(u'新版 CSV：'), 1, 0)
        grid.addWidget(self.edit_new, 1, 1)
        grid.addWidget(btn_new, 1, 2)
        root.addLayout(grid)

        # 2. 操作按钮
        ops = QHBoxLayout()
        ops.setSpacing(8)
        self.chk_bus = QCheckBox(u'Bus 合并（总线位索引 [0]..[N] → [*]）')
        self.chk_bus.setToolTip(u'勾选后，仅总线位索引不同的路径视为同一条（如 data_out_0_/D ~ data_out_63_/D）')
        self.chk_group = QCheckBox(u'按文件名区分 Timing Group')
        self.chk_group.setToolTip(u'勾选后，用 CSV 文件名（去 _violations 后缀）作为时序分组键；\n'
                                  u'未勾选时所有路径按同一分组对比（适合同模块两 run 对比）')
        btn_swap = QPushButton(u'⇅ 交换 A/B')
        btn_swap.clicked.connect(self._swap)
        self.btn_compare = QPushButton(u'▶ 开始对比')
        self.btn_compare.setMinimumHeight(30)
        self.btn_compare.clicked.connect(self._start_compare)
        self.btn_export_csv = QPushButton(u'导出 CSV…')
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_report = QPushButton(u'导出报告…')
        self.btn_export_report.clicked.connect(self._export_report)
        for b in (self.btn_export_csv, self.btn_export_report):
            b.setEnabled(False)
        ops.addWidget(self.chk_bus)
        ops.addWidget(self.chk_group)
        ops.addWidget(btn_swap)
        ops.addStretch(1)
        ops.addWidget(self.btn_compare)
        ops.addWidget(self.btn_export_csv)
        ops.addWidget(self.btn_export_report)
        root.addLayout(ops)

        # 3. 汇总卡片
        self.summary = QLabel(u'请选择两版 CSV 文件后点击"开始对比"。')
        self.summary.setStyleSheet(
            'background:#f5f5f5;border:1px solid #d0d0d0;border-radius:4px;'
            'padding:8px;font-size:13px;')
        root.addWidget(self.summary)

        # 4. 筛选
        flt = QHBoxLayout()
        flt.addWidget(QLabel(u'筛选状态：'))
        self.cmb_status = QComboBox()
        self.cmb_status.addItems([u'全部', u'新增', u'修复', u'持续违例',
                                  u'持续（改善）', u'持续（恶化）'])
        self.cmb_status.currentIndexChanged.connect(self._refresh_table)
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText(u'搜索 startpoint / endpoint / group…')
        self.edit_search.textChanged.connect(self._schedule_search)
        self.lbl_count = QLabel('')
        flt.addWidget(self.cmb_status)
        flt.addWidget(self.edit_search, 1)
        flt.addWidget(self.lbl_count)
        root.addLayout(flt)

        # 5. 结果表格
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 84)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 260)
        self.table.setColumnWidth(3, 260)
        for c in (4, 5, 6, 7, 8):
            self.table.setColumnWidth(c, 96)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        # 图例
        legend = QHBoxLayout()
        legend.setSpacing(10)
        legend.addWidget(self._legend_chip(u'新增', COLOR_NEW_BG, COLOR_NEW_FG))
        legend.addWidget(self._legend_chip(u'修复', COLOR_FIXED_BG, COLOR_FIXED_FG))
        legend.addWidget(self._legend_chip(u'持续（改善）', COLOR_IMPROVED_BG, '#33691e'))
        legend.addWidget(self._legend_chip(u'持续（恶化）', COLOR_WORSENED_BG, '#b71c1c'))
        legend.addWidget(self._legend_chip(u'持续（持平）', COLOR_ROW_BG, '#757575'))
        legend.addStretch(1)
        root.addLayout(legend)

        self.statusBar().showMessage(u'就绪。请选择旧版与新版 CSV 文件。')

    def _legend_chip(self, text, bg, fg):
        lab = QLabel(u'  %s  ' % text)
        lab.setStyleSheet('background:%s;color:%s;border:1px solid #c0c0c0;'
                          'border-radius:3px;padding:2px 6px;font-size:12px;'
                          'font-weight:bold;' % (bg, fg))
        return lab

    # ---------- 文件选择 ----------
    def _browse(self, edit):
        path, _ = QFileDialog.getOpenFileName(
            self, u'选择 CSV 文件', '', u'CSV 文件 (*.csv);;所有文件 (*.*)')
        if path:
            edit.setText(path)

    def _on_path_changed(self, _text):
        ok = bool(self.edit_old.text().strip()) and bool(self.edit_new.text().strip())
        self.btn_compare.setEnabled(ok)

    def _swap(self):
        o, n = self.edit_old.text(), self.edit_new.text()
        self.edit_old.setText(n)
        self.edit_new.setText(o)

    # ---------- 对比 ----------
    def _start_compare(self):
        old_path = self.edit_old.text().strip()
        new_path = self.edit_new.text().strip()
        if not old_path or not new_path:
            return
        if os.path.abspath(old_path) == os.path.abspath(new_path):
            QMessageBox.warning(self, u'提示', u'旧版与新版选择了同一个文件。')
        if self.worker and self.worker.isRunning():
            return

        if self.chk_group.isChecked():
            old_group = default_timing_group_from_filename(old_path)
            new_group = default_timing_group_from_filename(new_path)
        else:
            old_group = None
            new_group = None

        self.btn_compare.setEnabled(False)
        self.btn_export_csv.setEnabled(False)
        self.btn_export_report.setEnabled(False)
        self.statusBar().showMessage(u'正在解析与对比…')
        QApplication.setOverrideCursor(Qt.WaitCursor)

        self.worker = CompareWorker(old_path, new_path, old_group, new_group,
                                    self.chk_bus.isChecked(), self)
        self.worker.done.connect(self._on_compare_done)
        self.worker.failed.connect(self._on_compare_failed)
        self.worker.start()

    def _on_compare_done(self, result):
        QApplication.restoreOverrideCursor()
        self.btn_compare.setEnabled(True)
        self.btn_export_csv.setEnabled(True)
        self.btn_export_report.setEnabled(True)
        self.result = result
        self._update_summary(result)
        self._refresh_table()

        note = []
        if result.old.skipped:
            note.append(u'旧版跳过 %d 空行' % result.old.skipped)
        if result.new.skipped:
            note.append(u'新版跳过 %d 空行' % result.new.skipped)
        if result.bus_merge:
            note.append(u'Bus 合并已启用')
        self.statusBar().showMessage(u'对比完成：新增 %d / 修复 %d / 持续 %d 条。%s'
                                     % (result.new_count, result.fixed_count,
                                        result.persistent_count,
                                        u'；'.join(note)))

    def _on_compare_failed(self, message):
        QApplication.restoreOverrideCursor()
        self.btn_compare.setEnabled(True)
        self.statusBar().showMessage(u'对比失败')
        QMessageBox.critical(self, u'解析错误', message)

    # ---------- 汇总 ----------
    def _update_summary(self, r):
        s = u'旧版 <b>%d</b> 条 · 新版 <b>%d</b> 条　|　' % (len(r.old.rows), len(r.new.rows))
        s += u'<span style="color:%s">新增 <b>%d</b></span>　|　' % (COLOR_NEW_FG, r.new_count)
        s += u'<span style="color:%s">修复 <b>%d</b></span>　|　' % (COLOR_FIXED_FG, r.fixed_count)
        s += u'持续违例 <b>%d</b>（改善 <span style="color:#33691e">%d</span>'
        s = s % (r.persistent_count, r.improved_count)
        s += u' / 恶化 <span style="color:#b71c1c">%d</span>'
        s = s % r.worsened_count
        s += u' / 持平 %d）' % r.same_count
        if r.bus_merge:
            s += u'　<span style="color:#757575">（Bus 合并）</span>'
        self.summary.setText(s)

    # ---------- 表格 ----------
    def _filtered_rows(self):
        if not self.result:
            return []
        rows = self.result.all_rows
        idx = self.cmb_status.currentIndex()
        if idx == 1:
            rows = [r for r in rows if r.status == 'new']
        elif idx == 2:
            rows = [r for r in rows if r.status == 'fixed']
        elif idx == 3:
            rows = [r for r in rows if r.status == 'persistent']
        elif idx == 4:
            rows = [r for r in rows if r.status == 'persistent'
                    and r.delta is not None and r.delta > 0]
        elif idx == 5:
            rows = [r for r in rows if r.status == 'persistent'
                    and r.delta is not None and r.delta < 0]

        kw = self.edit_search.text().strip().lower()
        if kw:
            rows = [r for r in rows
                    if kw in r.startpoint.lower() or kw in r.endpoint.lower()
                    or kw in r.timing_group.lower()]
        return rows

    def _schedule_search(self, _text):
        if self._search_timer is None:
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(self._refresh_table)
        self._search_timer.start(200)

    def _refresh_table(self):
        if not self.result:
            return
        rows = self._filtered_rows()
        self.lbl_count.setText(u'共 %d 条' % len(rows))

        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._fill_row(i, r)
        self.table.setUpdatesEnabled(True)
        self.table.setSortingEnabled(True)

    def _fill_row(self, row_idx, r):
        bg = self._row_bg(r)
        fg = self._row_fg(r)
        values = [
            STATUS_LABEL[r.status],
            r.timing_group,
            r.startpoint,
            r.endpoint,
            self._fmt(r.base_slack, 4),
            self._fmt(r.target_slack, 4),
            self._fmt(r.delta, 4, signed=True),
            self._fmt(r.base_depth, 0),
            self._fmt(r.target_depth, 0),
        ]
        for col, val in enumerate(values):
            it = QTableWidgetItem(val)
            it.setBackground(QColor(bg))
            if col == 0:
                it.setForeground(QColor(fg))
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setTextAlignment(Qt.AlignCenter)
            elif col in (4, 5, 6, 7, 8):
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 6 and r.delta is not None:
                    if r.delta > 0:
                        it.setForeground(QColor('#2e7d32'))
                    elif r.delta < 0:
                        it.setForeground(QColor('#c62828'))
                if r.delta is not None:
                    it.setData(Qt.EditRole, r.delta)
            elif col == 1:
                it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, col, it)

    @staticmethod
    def _row_bg(r):
        if r.status == 'new':
            return COLOR_NEW_BG
        if r.status == 'fixed':
            return COLOR_FIXED_BG
        if r.delta is not None and r.delta > 0:
            return COLOR_IMPROVED_BG
        if r.delta is not None and r.delta < 0:
            return COLOR_WORSENED_BG
        return COLOR_ROW_BG

    @staticmethod
    def _row_fg(r):
        if r.status == 'new':
            return COLOR_NEW_FG
        if r.status == 'fixed':
            return COLOR_FIXED_FG
        return COLOR_PERSISTENT_FG

    @staticmethod
    def _fmt(value, ndigits, signed=False):
        if value is None:
            return '-'
        if isinstance(value, float):
            text = ('%+.*f' if signed else '%.*f') % (ndigits, value)
        else:
            text = str(value)
        return text

    # ---------- 导出 ----------
    def _require_result(self):
        if not self.result:
            QMessageBox.information(self, u'提示', u'请先执行对比。')
            return False
        return True

    def _export_csv(self):
        if not self._require_result():
            return
        default = u'violation_diff.csv'
        path, _ = QFileDialog.getSaveFileName(self, u'导出对比结果 CSV',
                                              default, u'CSV 文件 (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f)
                w.writerow([u'状态', u'Timing Group', u'Startpoint', u'Endpoint',
                            u'Base Slack', u'Target Slack', u'Delta Slack',
                            u'Base Depth', u'Target Depth'])
                for r in self.result.all_rows:
                    w.writerow([
                        STATUS_LABEL[r.status], r.timing_group, r.startpoint,
                        r.endpoint, self._fmt(r.base_slack, 4),
                        self._fmt(r.target_slack, 4),
                        self._fmt(r.delta, 4, signed=True),
                        self._fmt(r.base_depth, 0), self._fmt(r.target_depth, 0),
                    ])
            self.statusBar().showMessage(u'已导出：%s' % path)
        except OSError as e:
            QMessageBox.critical(self, u'导出失败', str(e))

    def _export_report(self):
        if not self._require_result():
            return
        default = u'violation_diff_report.txt'
        path, _ = QFileDialog.getSaveFileName(self, u'导出汇总报告',
                                              default, u'文本文件 (*.txt)')
        if not path:
            return
        if not path.lower().endswith('.txt'):
            path += '.txt'
        r = self.result
        lines = []
        lines.append(u'=' * 64)
        lines.append(u'违例路径两版对比报告')
        lines.append(u'=' * 64)
        lines.append(u'旧版文件：%s（%d 条）' % (r.old.path, len(r.old.rows)))
        lines.append(u'新版文件：%s（%d 条）' % (r.new.path, len(r.new.rows)))
        lines.append(u'Bus 合并：%s' % (u'是' if r.bus_merge else u'否'))
        lines.append('-' * 64)
        lines.append(u'新增路径：%d 条' % r.new_count)
        lines.append(u'修复路径：%d 条' % r.fixed_count)
        lines.append(u'持续违例：%d 条（改善 %d / 恶化 %d / 持平 %d）'
                     % (r.persistent_count, r.improved_count,
                        r.worsened_count, r.same_count))
        lines.append('=' * 64)
        for status in ('new', 'fixed', 'persistent'):
            group = [x for x in r.all_rows if x.status == status]
            if not group:
                continue
            lines.append(u'\n【%s】%d 条' % (STATUS_LABEL[status], len(group)))
            for x in group:
                slack = (self._fmt(x.delta, 4, signed=True)
                         if x.status == 'persistent' and x.delta is not None
                         else (u'旧 %s → 新 %s' % (self._fmt(x.base_slack, 4),
                                                   self._fmt(x.target_slack, 4))))
                lines.append(u'  [%s] %s → %s   slack: %s'
                             % (x.timing_group, x.startpoint, x.endpoint, slack))
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.statusBar().showMessage(u'已导出报告：%s' % path)
        except OSError as e:
            QMessageBox.critical(self, u'导出失败', str(e))


# =====================================================================
# 命令行自检
# =====================================================================

def selftest():
    """不启动界面，用内置样例数据验证解析与差异算法。"""
    import tempfile

    old_csv = u'''STARTPOINT,ENDPOINT,SLACK,DEPTH,PURE_DEPTH,CELL_DELAY,NET_DELAY
a_reg/CK,b_refg_0_/D,-0.020,27,23,500,77
clk_div/U1/Z,foo_reg/D,-0.045,15,12,320,55
data_out[0]/CK,data_out[0]/D,-0.012,9,7,210,33
data_out[1]/CK,data_out[1]/D,-0.010,9,7,208,32
data_out[2]/CK,data_out[2]/D,-0.013,9,7,215,35
ctrl_sync/U2/Q,idle_reg/D,-0.030,18,15,380,60
fix_me/U5/Z,hold_reg/D,-0.018,12,10,300,48
'''
    new_csv = u'''STARTPOINT,ENDPOINT,SLACK,DEPTH,PURE_DEPTH,CELL_DELAY,NET_DELAY
a_reg/CK,b_refg_0_/D,-0.015,27,23,490,72
clk_div/U1/Z,foo_reg/D,-0.040,15,12,318,54
data_out[0]/CK,data_out[0]/D,-0.011,9,7,209,33
data_out[1]/CK,data_out[1]/D,-0.008,9,7,205,31
data_out[2]/CK,data_out[2]/D,-0.014,9,7,217,36
new_alu/U7/Q,alu_reg/D,-0.025,20,16,360,58
new_mem/U9/Z,mem_reg/D,-0.009,8,6,190,29
'''
    tmp = tempfile.mkdtemp(prefix='vio_diff_')
    p_old = os.path.join(tmp, 'run_old_violations.csv')
    p_new = os.path.join(tmp, 'run_new_violations.csv')
    with open(p_old, 'w', encoding='utf-8') as f:
        f.write(old_csv)
    with open(p_new, 'w', encoding='utf-8') as f:
        f.write(new_csv)

    old = parse_csv(p_old)
    new = parse_csv(p_new)
    result = compute_diff(old, new, bus_merge=False)

    print(u'旧版条数: %d  新版条数: %d' % (len(old.rows), len(new.rows)))
    print(u'新增: %d  修复: %d  持续: %d (改善 %d / 恶化 %d / 持平 %d)'
          % (result.new_count, result.fixed_count, result.persistent_count,
             result.improved_count, result.worsened_count, result.same_count))

    assert len(old.rows) == 7 and len(new.rows) == 7, u'解析条数不符'
    assert result.new_count == 2, u'新增应为 2'
    assert result.fixed_count == 2, u'修复应为 2'
    assert result.persistent_count == 5, u'持续应为 5'
    assert result.improved_count == 4, u'改善应为 4'
    assert result.worsened_count == 1, u'恶化应为 1'

    # Bus 合并自检：data_out_[0..2] 应合并为 1 条持续
    b = compute_diff(old, new, bus_merge=True)
    print(u'[Bus 合并] 持续: %d 条（期望 3：data_out[*], a_reg, clk_div）'
          % b.persistent_count)
    assert b.persistent_count == 3, u'Bus 合并后持续应为 3'

    print(u'自检通过 [OK]')
    return 0


def smoke():
    """构造主窗口并在 1.5s 后自动关闭，验证界面无构造错误。"""
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    QTimer.singleShot(1500, app.quit)
    return app.exec_()


def main():
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    if '--smoke' in sys.argv:
        sys.exit(smoke())
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
