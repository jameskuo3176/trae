<script setup>
import { computed, ref } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import DataTable from '@/components/common/DataTable.vue'

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
const rows = computed(() => metrics.map(metric => ({ ...metric, id: metric.key })))

function formatValue(value) {
  if (value == null) return '-'
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(3) : String(value)
}

function colorClass(record, metricKey, previousRecord) {
  if (!showColors.value || !previousRecord) return ''
  const current = Number(record[metricKey])
  const previous = Number(previousRecord[metricKey])
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return ''
  const change = (Math.abs(current - previous) / Math.max(Math.abs(previous), 1)) * 100
  if (change < colorThreshold.value) return ''
  const higherIsBetter = ['wns', 'tns'].includes(metricKey)
  const better = higherIsBetter ? current > previous : current < previous
  return better ? 'color-good' : 'color-bad'
}

const columns = computed(() => [
  { key: 'label', label: '指标', width: '160px' },
  ...dashboard.selectedRecords.map((record, index) => ({
    key: String(record.id),
    label: `${record.module_name} (${record.tag || record.version})`,
    value: row => record[row.key],
    format: value => formatValue(value),
    numeric: true,
    class: row => colorClass(record, row.key, dashboard.selectedRecords[index - 1])
  }))
])
</script>

<template>
  <section class="card">
    <header class="card-header">
      <span>转置对比表格</span>
      <div class="toolbar">
        <label><input v-model="showColors" type="checkbox" /> 启用变化标注</label>
        <label
          >阈值:
          <input v-model.number="colorThreshold" type="number" min="0" max="100" step="0.5" /> %
        </label>
      </div>
    </header>
    <DataTable
      :rows="rows"
      :columns="columns"
      filename="qor-transposed.csv"
      empty-text="Select runs for transposed comparison"
      copy-on-click
    />
  </section>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
}
.toolbar label {
  display: flex;
  gap: 4px;
  align-items: center;
}
.toolbar input {
  width: 60px;
}
:deep(.color-bad) {
  background: color-mix(in srgb, #d84a4a 25%, var(--color-surface));
}
:deep(.color-good) {
  background: color-mix(in srgb, #2ca66f 24%, var(--color-surface));
}
</style>
