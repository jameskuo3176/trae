<script setup>
import { computed, ref } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import DataTable from '@/components/common/DataTable.vue'

const dashboard = useDashboardStore()
const groupBy = ref('run')
const statMethod = ref('avg')
const showBestWorst = ref(true)
const metricKeys = ['area_total', 'power_total', 'wns', 'tns', 'cell_count']

const aggregated = computed(() => {
  const groups = new Map()
  dashboard.records.forEach(record => {
    const directory = record.full_dir || ''
    const key =
      groupBy.value === 'base_dir'
        ? directory.slice(0, Math.max(directory.lastIndexOf('/'), 0))
        : groupBy.value === 'module'
          ? `${record.project_name || ''}|${record.module_name || ''}`
          : `${directory}|${record.id}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(record)
  })
  return [...groups].map(([key, items]) => {
    const row = { key, count: items.length }
    metricKeys.forEach(metric => {
      const values = items.map(item => Number(item[metric])).filter(Number.isFinite)
      if (!values.length) return
      if (statMethod.value === 'min') row[metric] = Math.min(...values)
      else if (statMethod.value === 'max') row[metric] = Math.max(...values)
      else if (statMethod.value === 'median') {
        values.sort((left, right) => left - right)
        const middle = Math.floor(values.length / 2)
        row[metric] = values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2
      } else row[metric] = values.reduce((sum, value) => sum + value, 0) / values.length
    })
    return row
  })
})

const extrema = computed(() => {
  const result = {}
  metricKeys.forEach(metric => {
    const values = aggregated.value.filter(row => row[metric] != null)
    if (!values.length) return
    const sorted = [...values].sort((left, right) => left[metric] - right[metric])
    const higherIsBetter = ['wns', 'tns'].includes(metric)
    result[metric] = {
      best: higherIsBetter ? sorted.at(-1).key : sorted[0].key,
      worst: higherIsBetter ? sorted[0].key : sorted.at(-1).key
    }
  })
  return result
})

const columns = computed(() => [
  { key: 'key', label: `分组 (${aggregated.value.length})`, width: '280px' },
  { key: 'count', label: '数量', numeric: true },
  ...[
    ['area_total', '总面积'],
    ['power_total', '总功耗'],
    ['wns', 'WNS'],
    ['tns', 'TNS'],
    ['cell_count', '单元数']
  ].map(([key, label]) => ({
    key,
    label,
    numeric: true,
    format: value => (value == null ? '-' : Number(value).toFixed(3)),
    class: row =>
      !showBestWorst.value
        ? ''
        : row.key === extrema.value[key]?.best
          ? 'color-good'
          : row.key === extrema.value[key]?.worst
            ? 'color-bad'
            : ''
  }))
])
</script>

<template>
  <section class="card">
    <header class="card-header">
      <span>目录聚合视图</span>
      <div class="toolbar">
        <label
          >聚合维度:
          <select v-model="groupBy">
            <option value="run">按 Run</option>
            <option value="base_dir">按 Base Dir</option>
            <option value="module">按 Module</option>
          </select>
        </label>
        <label
          >聚合方法:
          <select v-model="statMethod">
            <option value="avg">平均</option>
            <option value="min">最小</option>
            <option value="max">最大</option>
            <option value="median">中位数</option>
          </select>
        </label>
        <label><input v-model="showBestWorst" type="checkbox" /> 标注最佳/最差</label>
      </div>
    </header>
    <DataTable
      :rows="aggregated"
      :columns="columns"
      row-key="key"
      filename="qor-directory-aggregate.csv"
      empty-text="无数据"
      copy-on-click
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
  align-items: center;
  gap: 4px;
}
:deep(.color-bad) {
  background: color-mix(in srgb, #d84a4a 25%, var(--color-surface));
}
:deep(.color-good) {
  background: color-mix(in srgb, #2ca66f 24%, var(--color-surface));
}
</style>
