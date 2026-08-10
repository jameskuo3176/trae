<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDashboardStore } from '@/stores/dashboard'

const router = useRouter()
const dashboard = useDashboardStore()

const onlyWithRaw = ref(false)
const showChange = ref(true)
const compactTiming = ref(false)
const navWidth = ref(220)
const isDragging = ref(false)
let startX = 0
let startWidth = 0

function startDrag(e) {
  isDragging.value = true
  startX = e.clientX
  startWidth = navWidth.value
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
  document.body.style.userSelect = 'none'
}

function onDrag(e) {
  if (!isDragging.value) return
  const delta = e.clientX - startX
  const newWidth = Math.max(160, Math.min(400, startWidth + delta))
  navWidth.value = newWidth
}

function stopDrag() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
  document.body.style.userSelect = ''
}

onMounted(() => {
  // 加载保存的宽度
  const saved = localStorage.getItem('dcNavWidth')
  if (saved) navWidth.value = Math.max(160, Math.min(400, Number(saved)))
})

onUnmounted(() => {
  localStorage.setItem('dcNavWidth', String(navWidth.value))
  stopDrag()
})

const displayRecords = computed(() => {
  if (onlyWithRaw.value) {
    return dashboard.records.filter(r => r.raw_dc_report)
  }
  return dashboard.records
})

const dcCount = computed(() => {
  return dashboard.records.filter(r => r.raw_dc_report).length
})

const countText = computed(() => {
  return `CSV ${dashboard.records.length} / DC ${dcCount.value}`
})

function toggleSelect(id) {
  dashboard.toggleSelect(id)
}

function selectAll() {
  dashboard.selectAll()
}

function clearSelection() {
  dashboard.clearSelection()
}

function goToCompare() {
  if (dashboard.selectedIds.size === 0) {
    alert('请先选择要对比的 Run')
    return
  }
  const ids = Array.from(dashboard.selectedIds).join(',')
  router.push({ name: 'Compare', query: { record_ids: ids } })
}

function getRecordLabel(r) {
  const parts = [r.module_name]
  if (r.tag) parts.push(r.tag)
  if (r.version) parts.push(r.version)
  return parts.join(' / ')
}

function getDcRawReport(record) {
  if (!record || !record.raw_dc_report) return null
  if (typeof record.raw_dc_report === 'object') return record.raw_dc_report
  try { return JSON.parse(record.raw_dc_report) } catch { return null }
}

function getDcSections(record) {
  const raw = getDcRawReport(record)
  if (!raw) return []
  return Object.keys(raw).filter(k => k !== 'metadata' && raw[k] && typeof raw[k] === 'object')
}

function getDcSectionData(record, section) {
  const raw = getDcRawReport(record)
  return raw ? raw[section] : null
}

const selectedDcRecords = computed(() => {
  return dashboard.selectedRecords.filter(r => r.raw_dc_report)
})

const dcSections = computed(() => {
  const sections = new Set()
  for (const r of selectedDcRecords.value) {
    getDcSections(r).forEach(s => sections.add(s))
  }
  return Array.from(sections)
})

function formatDcValue(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'number') {
    return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(4)
  }
  return String(val)
}

function getDcChangeColor(records, idx, section, key) {
  if (!showChange.value || idx === 0) return ''
  const prevData = getDcSectionData(records[idx - 1], section)
  const currData = getDcSectionData(records[idx], section)
  const cv = currData ? currData[key] : null
  const pv = prevData ? prevData[key] : null
  if (cv == null || pv == null) return ''
  const ncv = Number(cv), npv = Number(pv)
  if (isNaN(ncv) || isNaN(npv) || npv === 0) return ''
  return ncv > npv ? 'dc-change-up' : 'dc-change-down'
}

function getDcTableData(section) {
  const rows = []
  const allKeys = new Set()
  const records = selectedDcRecords.value

  for (const r of records) {
    const data = getDcSectionData(r, section)
    if (data) {
      let keys = Object.keys(data)
      // 紧凑时序模式：只显示 WNS/TNS/NVP
      if (compactTiming.value && section === 'timing') {
        keys = keys.filter(k => {
          const kl = k.toLowerCase()
          return kl.includes('wns') || kl.includes('tns') || kl.includes('nvp')
        })
      }
      keys.forEach(k => allKeys.add(k))
    }
  }

  for (const key of allKeys) {
    const row = { key }
    for (const r of records) {
      const data = getDcSectionData(r, section)
      row[r.id] = data ? data[key] : null
    }
    rows.push(row)
  }
  return rows
}

function exportDcCsv() {
  const records = selectedDcRecords.value
  if (records.length === 0) {
    alert('请先选择含 DC 报告的 Run')
    return
  }
  let csv = 'section,key'
  records.forEach(r => {
    csv += ',' + getRecordLabel(r)
  })
  csv += '\n'

  for (const section of dcSections.value) {
    const tableData = getDcTableData(section)
    for (const row of tableData) {
      csv += `${section},${row.key}`
      for (const r of records) {
        const val = row[r.id]
        csv += ',' + (val != null ? String(val) : '')
      }
      csv += '\n'
    }
  }

  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'dc_report_comparison.csv'
  a.click()
  URL.revokeObjectURL(url)
}

const sectionLabels = {
  timing: '时序',
  area: '面积',
  power: '功耗',
  cells: 'Cells',
  congestion: '拥塞',
  ratios: '比率',
  clocks: '时钟',
  frequency: '频率',
  misc: '其他'
}
</script>

<template>
  <div class="dc-report-layout">
    <!-- 左侧导航栏 -->
    <nav class="dc-nav" :style="{ width: navWidth + 'px', minWidth: '160px', maxWidth: '400px' }">
      <div class="dc-nav-header">数据对比导航</div>
      <div class="dc-nav-count" style="margin-bottom: 8px;">
        <span class="tag" style="font-size: 11px;">{{ countText }}</span>
      </div>
      <div class="dc-nav-actions">
        <button class="btn-sm" @click="selectAll" style="font-size:10px; padding:2px 6px;">全选</button>
        <button class="btn-sm" @click="clearSelection" style="font-size:10px; padding:2px 6px;">清空</button>
      </div>
      <div class="dc-run-checklist">
        <label
          v-for="r in displayRecords"
          :key="r.id"
          class="dc-run-item"
          :class="{ selected: dashboard.selectedIds.has(r.id) }"
        >
          <input
            type="checkbox"
            :checked="dashboard.selectedIds.has(r.id)"
            @change="toggleSelect(r.id)"
          />
          <span class="dc-run-label">
            <span class="dc-run-name">{{ getRecordLabel(r) }}</span>
            <span v-if="r.raw_dc_report" class="dc-has-dc" title="含 DC 报告">DC</span>
          </span>
          <a
            class="dc-run-detail"
            :href="`/record/${r.id}`"
            target="_blank"
            @click.stop
            title="查看记录详情"
          >详情</a>
        </label>
      </div>
    </nav>

    <!-- 拖拽调整手柄 -->
    <div class="dc-nav-resize-handle" @mousedown="startDrag" :class="{ dragging: isDragging }" />

    <!-- 右侧内容区 -->
    <div class="dc-content">
      <div class="dc-toolbar">
        <span>
          <strong>数据对比视图</strong>
          <span class="dc-subtitle">CSV / DC 报告数据统一管理, 勾选数据集进行对比分析</span>
        </span>
        <div class="dc-toolbar-actions">
          <label class="dc-checkbox-label">
            <input type="checkbox" v-model="onlyWithRaw" /> 仅含 DC 报告
          </label>
          <label class="dc-checkbox-label">
            <input type="checkbox" v-model="showChange" /> 标注变化
          </label>
          <label class="dc-checkbox-label">
            <input type="checkbox" v-model="compactTiming" /> 紧凑时序
          </label>
          <button class="btn-sm" @click="exportDcCsv" style="font-size:11px; padding:2px 8px;">下载 CSV</button>
          <button class="btn-sm" @click="goToCompare" style="background: var(--color-primary); color: #fff;">
            对比选中 ({{ dashboard.selectedIds.size }})
          </button>
        </div>
      </div>

      <div v-if="selectedDcRecords.length === 0" class="dc-empty">
        <p>请选择要对比的 Run</p>
        <p class="dc-hint">在左侧导航栏的 "数据集" 区域勾选 Run，可同时选择多个 Run 进行横向对比分析。</p>
      </div>

      <div v-else v-for="section in dcSections" :key="section" class="dc-section-card">
        <div class="dc-section-header">
          {{ sectionLabels[section] || section }}
        </div>
        <div class="dc-section-body">
          <table class="table dc-table">
            <thead>
              <tr>
                <th>指标</th>
                <th v-for="r in selectedDcRecords" :key="r.id" class="dc-record-header">
                  {{ getRecordLabel(r) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in getDcTableData(section)" :key="row.key">
                <td class="dc-key">{{ row.key }}</td>
                <td
                  v-for="(r, idx) in selectedDcRecords"
                  :key="r.id"
                  class="dc-value"
                  :class="getDcChangeColor(selectedDcRecords, idx, section, row.key)"
                >
                  {{ formatDcValue(row[r.id]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dc-report-layout {
  display: flex;
  gap: 0;
  min-height: 300px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  margin-bottom: 16px;
}

.dc-nav {
  width: 220px;
  min-width: 140px;
  flex-shrink: 0;
  border-right: 1px solid var(--color-border);
  padding: 12px 0;
  overflow-y: auto;
  max-height: 75vh;
  background: var(--color-surface);
}

.dc-nav-header {
  padding: 0 12px 8px;
  font-weight: 600;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 4px;
  white-space: nowrap;
}

.dc-nav-count {
  padding: 4px 12px;
}

.dc-nav-actions {
  padding: 4px 12px;
  display: flex;
  gap: 4px;
}

.dc-run-checklist {
  margin-top: 6px;
  max-height: 400px;
  overflow-y: auto;
}

.dc-run-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s;
}

.dc-run-item:hover {
  background: var(--color-surface-hover);
}

.dc-run-item.selected {
  background: var(--color-primary-light, rgba(0, 123, 255, 0.08));
}

.dc-run-item input {
  margin-top: 2px;
  flex-shrink: 0;
}

.dc-run-label {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.dc-run-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dc-has-dc {
  font-size: 9px;
  padding: 0 3px;
  background: #2196f3;
  color: #fff;
  border-radius: 2px;
  flex-shrink: 0;
}

.dc-run-detail {
  font-size: 10px;
  color: var(--color-primary);
  text-decoration: none;
  padding: 1px 5px;
  border: 1px solid var(--color-primary);
  border-radius: 3px;
  flex-shrink: 0;
  margin-left: auto;
  opacity: 0;
  transition: opacity 0.15s;
  white-space: nowrap;
}

.dc-run-item:hover .dc-run-detail {
  opacity: 1;
}

.dc-nav-resize-handle {
  width: 4px;
  background: transparent;
  cursor: col-resize;
  flex-shrink: 0;
}

.dc-nav-resize-handle:hover {
  background: var(--color-primary);
}

.dc-content {
  flex: 1;
  padding: 12px 16px;
  overflow-y: auto;
  max-height: 75vh;
}

.dc-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 12px;
  flex-wrap: wrap;
  gap: 6px;
}

.dc-subtitle {
  color: var(--color-text-secondary);
  margin-left: 8px;
  font-size: 11px;
}

.dc-toolbar-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.dc-checkbox-label {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  cursor: pointer;
}

.dc-empty {
  text-align: center;
  padding: 40px;
  color: var(--color-text-secondary);
}

.dc-hint {
  font-size: 12px;
  margin-top: 8px;
  opacity: 0.7;
}

.dc-section-card {
  margin-bottom: 12px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  overflow: hidden;
}

.dc-section-header {
  padding: 6px 12px;
  font-weight: 600;
  font-size: 13px;
  background: var(--color-surface-hover);
  border-bottom: 1px solid var(--color-border);
}

.dc-section-body {
  overflow-x: auto;
  padding: 0;
}

.dc-table {
  margin: 0;
  font-size: 11px;
}

.dc-table th,
.dc-table td {
  padding: 4px 8px;
  white-space: nowrap;
}

.dc-record-header {
  font-size: 10px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dc-key {
  font-weight: 500;
  color: var(--color-text-secondary);
}

.dc-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.dc-change-up {
  background: #fde2e1;
  color: #f5222d;
}
.dc-change-down {
  background: #d9f7be;
  color: #389e0d;
}
</style>