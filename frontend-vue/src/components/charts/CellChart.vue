<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import BaseChart from './BaseChart.vue'

const dashboard = useDashboardStore()

const chartOption = computed(() => {
  const records = dashboard.selectedRecords
  if (records.length === 0) return null

  const cats = records.map(r => {
    let label = r.module_name || ''
    const tag = r.tag || r.version
    if (tag) label += ` (${tag})`
    return label
  })

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['Cell Count', 'Sequential', 'Macro'], textStyle: { color: '#8b9bb4' } },
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 }
    },
    yAxis: { type: 'value', name: 'Count', axisLabel: { color: '#8b9bb4' } },
    series: [
      { name: 'Cell Count', type: 'bar', data: records.map(r => r.cell_count ?? null) },
      { name: 'Sequential', type: 'bar', data: records.map(r => r.sequential_cell_count ?? null) },
      { name: 'Macro', type: 'bar', data: records.map(r => r.macro_cell_count ?? null) }
    ]
  }
})
</script>

<template>
  <div class="card">
    <div class="card-header">Cells 单元</div>
    <div class="card-body">
      <BaseChart
        v-if="dashboard.selectedRecords.length > 0 && chartOption"
        chart-id="chart-cells"
        :option="chartOption"
      />
      <div v-else class="empty-state">请选择数据记录</div>
    </div>
  </div>
</template>
