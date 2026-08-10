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
    legend: { data: ['Total', 'Combinational', 'Sequential'], textStyle: { color: '#8b9bb4' } },
    xAxis: { type: 'category', data: cats, axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 } },
    yAxis: { type: 'value', name: 'Area', axisLabel: { color: '#8b9bb4' } },
    series: [
      { name: 'Total', type: 'bar', data: records.map(r => r.area_total ?? null) },
      { name: 'Combinational', type: 'bar', data: records.map(r => r.area_combinational ?? null) },
      { name: 'Sequential', type: 'bar', data: records.map(r => r.area_sequential ?? null) }
    ]
  }
})
</script>

<template>
  <div class="card">
    <div class="card-header">Area 面积</div>
    <div class="card-body">
      <BaseChart
        v-if="dashboard.selectedRecords.length > 0 && chartOption"
        chart-id="chart-area"
        :option="chartOption"
      />
      <div v-else class="empty-state">请选择数据记录</div>
    </div>
  </div>
</template>