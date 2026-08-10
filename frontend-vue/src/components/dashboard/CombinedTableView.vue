<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'

const dashboard = useDashboardStore()
const showClocks = ref(true)
const enableColor = ref(true)
const colorThreshold = ref(5)
const sortColumn = ref(null)
const sortDir = ref('asc')

const records = computed(() => dashboard.records)

const allColumns = computed(() => {
  const cols = new Set()
  records.value.forEach(r => {
    Object.keys(r).forEach(k => {
      if (!['id', 'raw_dc_report', 'extra_fields', 'comment', 'created_at', 'updated_at'].includes(k)) {
        cols.add(k)
      }
    })
    if (r.extra_fields && r.extra_fields.clocks) {
      Object.keys(r.extra_fields.clocks).forEach(ck => {
        const clockData = r.extra_fields.clocks[ck]
        if (clockData && typeof clockData === 'object') {
          Object.keys(clockData).forEach(cdk => cols.add(`clock_${ck}_${cdk}`))
        }
      })
    }
  })
  return Array.from(cols).sort()
})

const labelCols = computed(() => ['module_name', 'tag', 'version', 'full_dir'].filter(c => allColumns.value.includes(c)))
const metricCols = computed(() => allColumns.value.filter(c => !labelCols.value.includes(c)))

const sortedRecords = computed(() => {
  const recs = [...records.value]
  if (!sortColumn.value) return recs
  return recs.sort((a, b) => {
    const va = getCellValue(a, sortColumn.value)
    const vb = getCellValue(b, sortColumn.value)
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    const na = Number(va), nb = Number(vb)
    if (!isNaN(na) && !isNaN(nb)) return sortDir.value === 'asc' ? na - nb : nb - na
    return sortDir.value === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
  })
})

function getCellValue(r, col) {
  if (col.startsWith('clock_')) {
    const parts = col.split('_')
    const clock = parts[1]
    const field = parts.slice(2).join('_')
    return r.extra_fields?.clocks?.[clock]?.[field] ?? null
  }
  return r[col] ?? null
}

function formatCell(val) {
  if (val == null) return '-'
  if (typeof val === 'number') return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(4)
  return String(val)
}

function getChangeColor(r, col) {
  if (!enableColor.value || records.value.length < 2) return ''
  const idx = records.value.indexOf(r)
  if (idx === 0) return ''
  const prev = records.value[idx - 1]
  const cv = getCellValue(r, col)
  const pv = getCellValue(prev, col)
  if (cv == null || pv == null) return ''
  const ncv = Number(cv), npv = Number(pv)
  if (isNaN(ncv) || isNaN(npv) || npv === 0) return ''
  const change = ((ncv - npv) / Math.abs(npv)) * 100
  if (Math.abs(change) < colorThreshold.value) return ''
  return change > 0 ? 'cell-worse' : 'cell-better'
}

function handleSort(col) {
  if (sortColumn.value === col) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortColumn.value = col
    sortDir.value = 'asc'
  }
}

function copyTable(format) {
  const sep = format === 'tsv' ? '\t' : ','
  const headers = [...labelCols.value, ...metricCols.value]
  let text = headers.join(sep) + '\n'
  sortedRecords.value.forEach(r => {
    text += headers.map(h => formatCell(getCellValue(r, h))).join(sep) + '\n'
  })
  navigator.clipboard.writeText(text).then(() => alert('已复制到剪贴板'))
}

function downloadCsv() {
  const headers = [...labelCols.value, ...metricCols.value]
  let text = headers.join(',') + '\n'
  sortedRecords.value.forEach(r => {
    text += headers.map(h => {
      const v = getCellValue(r, h)
      return v == null ? '' : String(v)
    }).join(',') + '\n'
  })
  const blob = new Blob(['\uFEFF' + text], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'qor_combined_table.csv'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="combined-table card">
    <div class="card-header">
      <span>全量指标合并表格</span>
      <div class="toolbar">
        <label>
          <input type="checkbox" v-model="showClocks" /> 显示时钟列
        </label>
        <label>
          <input type="checkbox" v-model="enableColor" /> 启用变化标注
        </label>
        <label>
          变化阈值
          <input type="number" v-model.number="colorThreshold" min="0" max="100" step="0.5" style="width:60px" />
          %
        </label>
        <span class="legend">
          <span class="legend-worse"></span> 恶化
          <span class="legend-better"></span> 改善
        </span>
        <button class="btn btn-sm" @click="copyTable('tsv')">复制 TSV</button>
        <button class="btn btn-sm" @click="copyTable('csv')">复制 CSV</button>
        <button class="btn btn-sm" @click="downloadCsv">下载 CSV</button>
      </div>
    </div>
    <div class="card-body table-wrap">
      <table class="table combined-table-content">
        <thead>
          <tr>
            <th v-for="col in labelCols" :key="col" @click="handleSort(col)" class="sortable">
              {{ col }}
              <span v-if="sortColumn === col">{{ sortDir === 'asc' ? '▲' : '▼' }}</span>
            </th>
            <th
              v-for="col in metricCols"
              :key="col"
              v-show="showClocks || !col.startsWith('clock_')"
              @click="handleSort(col)"
              class="sortable metric-col"
            >
              {{ col }}
              <span v-if="sortColumn === col">{{ sortDir === 'asc' ? '▲' : '▼' }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, ri) in sortedRecords" :key="r.id">
            <td v-for="col in labelCols" :key="col">{{ formatCell(getCellValue(r, col)) }}</td>
            <td
              v-for="col in metricCols"
              :key="col"
              v-show="showClocks || !col.startsWith('clock_')"
              :class="getChangeColor(r, col)"
            >
              {{ formatCell(getCellValue(r, col)) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.combined-table {
  margin-bottom: 16px;
}
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 12px;
}
.toolbar label {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.legend {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: #888;
}
.legend-worse {
  display: inline-block;
  width: 10px; height: 10px;
  background: #fde2e1; border: 1px solid #f5222d;
  margin-right: 4px;
}
.legend-better {
  display: inline-block;
  width: 10px; height: 10px;
  background: #d9f7be; border: 1px solid #52c41a;
  margin-left: 8px; margin-right: 4px;
}
.table-wrap {
  max-height: 70vh;
  overflow: auto;
  padding: 0;
}
.combined-table-content {
  font-size: 11px;
  margin: 0;
}
.combined-table-content th {
  white-space: nowrap;
  padding: 4px 8px;
}
.combined-table-content td {
  padding: 4px 8px;
  white-space: nowrap;
}
.sortable {
  cursor: pointer;
  user-select: none;
}
.sortable:hover {
  background: var(--color-surface-hover);
}
.metric-col {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cell-worse {
  background: #fde2e1 !important;
  color: #f5222d;
}
.cell-better {
  background: #d9f7be !important;
  color: #389e0d;
}
</style>