<script setup>
import { computed, ref } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import DataTable from '@/components/common/DataTable.vue'

const dashboard = useDashboardStore()
const showClocks = ref(true)
const enableColor = ref(true)
const colorThreshold = ref(5)
const records = computed(() => dashboard.records)

function getCellValue(record, column) {
  if (!column.startsWith('clock_')) return record[column] ?? null
  const [, clock, ...field] = column.split('_')
  return record.extra_fields?.clocks?.[clock]?.[field.join('_')] ?? null
}

function getChangeColor(record, column) {
  if (!enableColor.value) return ''
  const index = records.value.indexOf(record)
  if (index <= 0) return ''
  const current = Number(getCellValue(record, column))
  const previous = Number(getCellValue(records.value[index - 1], column))
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) return ''
  const change = ((current - previous) / Math.abs(previous)) * 100
  if (Math.abs(change) < colorThreshold.value) return ''
  const higherIsBetter = /wns|tns|slack|utilization|gating|coverage/i.test(column)
  const better = higherIsBetter ? current > previous : current < previous
  return better ? 'cell-better' : 'cell-worse'
}

const columns = computed(() => {
  const keys = new Set()
  records.value.forEach(record => {
    Object.keys(record).forEach(key => {
      if (
        !['id', 'raw_dc_report', 'extra_fields', 'comment', 'created_at', 'updated_at'].includes(
          key
        )
      ) {
        keys.add(key)
      }
    })
    Object.entries(record.extra_fields?.clocks || {}).forEach(([clock, values]) => {
      Object.keys(values || {}).forEach(key => keys.add(`clock_${clock}_${key}`))
    })
  })
  const labels = ['module_name', 'tag', 'version', 'full_dir']
  return [...keys]
    .sort((left, right) => {
      const leftIndex = labels.indexOf(left)
      const rightIndex = labels.indexOf(right)
      if (leftIndex >= 0 || rightIndex >= 0) {
        return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex)
      }
      return left.localeCompare(right)
    })
    .map(key => ({
      key,
      label: key,
      hidden: !showClocks.value && key.startsWith('clock_'),
      value: record => getCellValue(record, key),
      numeric: !labels.includes(key),
      class: record => getChangeColor(record, key)
    }))
})
</script>

<template>
  <section class="combined-table card">
    <header class="card-header">
      <span>全量指标合并表格</span>
      <div class="toolbar">
        <label><input v-model="showClocks" type="checkbox" /> 显示时钟列</label>
        <label><input v-model="enableColor" type="checkbox" /> 启用变化标注</label>
        <label
          >变化阈值
          <input v-model.number="colorThreshold" type="number" min="0" max="100" step="0.5" />
          %
        </label>
        <span class="legend"><i class="worse" /> 恶化 <i class="better" /> 改善</span>
      </div>
    </header>
    <DataTable
      :rows="records"
      :columns="columns"
      filename="qor-combined.csv"
      empty-text="No combined QoR records"
      copy-on-click
      max-height="70vh"
    />
  </section>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 11px;
}
.toolbar label {
  display: flex;
  gap: 4px;
  align-items: center;
}
.toolbar input[type='number'] {
  width: 60px;
}
.legend {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.legend i {
  width: 10px;
  height: 10px;
  border: 1px solid currentColor;
}
.legend .worse {
  background: var(--color-danger);
}
.legend .better {
  background: var(--color-success);
}
:deep(.cell-worse) {
  background: var(--color-danger-background);
  color: var(--color-danger);
}
:deep(.cell-better) {
  background: var(--color-success-background);
  color: var(--color-success);
}
</style>
