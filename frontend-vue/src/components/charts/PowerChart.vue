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
    legend: { data: ['Total', 'Internal', 'Switching', 'Leakage'], textStyle: { color: '#8b9bb4' } },
    xAxis: { type: 'category', data: cats, axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 } },
    yAxis: { type: 'value', name: 'mW', axisLabel: { color: '#8b9bb4' } },
    series: [
      { name: 'Total', type: 'bar', data: records.map(r => r.power_total ?? null) },
      { name: 'Internal', type: 'bar', data: records.map(r => r.power_internal ?? null) },
      { name: 'Switching', type: 'bar', data: records.map(r => r.power_switching ?? null) },
      { name: 'Leakage', type: 'bar', data: records.map(r => r.power_leakage ?? null) }
    ]
  }
})
</script>

<template>
  <div class="card">
    <div class="card-header">Power 功耗</div>
    <div class="card-body">
      <BaseChart
        v-if="dashboard.selectedRecords.length > 0 && chartOption"
        chart-id="chart-power"
        :option="chartOption"
      />
      <div v-else class="empty-state">请选择数据记录</div>
    </div>
  </div>
</template>