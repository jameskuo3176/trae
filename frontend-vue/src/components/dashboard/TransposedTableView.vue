<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'

const dashboard = useDashboardStore()
const showColors = ref(true)
const colorThreshold = ref(5)

const metrics = [
  { key: 'area_total', label: '总面积' },
  { key: 'power_total', label: '总功耗' },
  { key: 'wns', label: 'WNS' },
  { key: 'tns', label: 'TNS' },
  { key: 'cell_count', label: '单元数' }
]

function formatValue(v) {
  if (v == null) return '-'
  const num = parseFloat(v)
  return isNaN(num) ? v : num.toFixed(3)
}

function getColorClass(record, metricKey, prevRecord) {
  if (!showColors.value || !prevRecord) return ''
  const v = parseFloat(record[metricKey])
  const pv = parseFloat(prevRecord[metricKey])
  if (isNaN(v) || isNaN(pv)) return ''
  const diff = Math.abs(v - pv) / Math.max(Math.abs(pv), 1) * 100
  if (diff < colorThreshold.value) return ''
  if (['wns', 'tns'].includes(metricKey)) {
    return v < pv ? 'color-good' : 'color-bad'
  }
  return v > pv ? 'color-bad' : 'color-good'
}
</script>

<template>
  <div class="card">
    <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
      <span>转置对比表格</span>
      <div style="display:flex; gap:8px; align-items:center;">
        <label style="display:flex; gap:4px; align-items:center;">
          <input type="checkbox" v-model="showColors"> 启用变化标注
        </label>
        <label style="display:flex; gap:4px; align-items:center;">
          阈值:
          <input type="number" v-model.number="colorThreshold" min="0" max="100" step="0.5" style="width:60px;">
          %
        </label>
        <span style="color:#888; font-size:11px; display:flex; gap:8px; align-items:center;">
          <span style="display:inline-block; width:10px; height:10px; background:#fde2e1; border:1px solid #f5222d;"></span> 恶化
          <span style="display:inline-block; width:10px; height:10px; background:#d9f7be; border:1px solid #52c41a;"></span> 改善
        </span>
      </div>
    </div>
    <div class="card-body" style="padding:0;">
      <div style="max-height: 60vh; overflow:auto;">
        <table style="width:100%; border-collapse: collapse; font-size:12px;">
          <thead>
            <tr style="background:var(--color-bg-secondary);">
              <th style="position:sticky; left:0; background:var(--color-bg-secondary); z-index:10; padding:8px; border:1px solid var(--color-border);">指标</th>
              <th
                v-for="r in dashboard.selectedRecords"
                :key="r.id"
                style="padding:8px; border:1px solid var(--color-border);"
              >
                {{ r.module_name }} ({{ r.tag || r.version }})
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in metrics" :key="m.key">
              <td style="position:sticky; left:0; background:var(--color-bg); z-index:10; padding:8px; border:1px solid var(--color-border); font-weight:500;">
                {{ m.label }}
              </td>
              <td
                v-for="(r, idx) in dashboard.selectedRecords"
                :key="r.id"
                :class="getColorClass(r, m.key, dashboard.selectedRecords[idx - 1])"
                style="padding:8px; border:1px solid var(--color-border); text-align:right;"
              >
                {{ formatValue(r[m.key]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.color-bad {
  background-color: #fde2e1;
}
.color-good {
  background-color: #d9f7be;
}
</style>
