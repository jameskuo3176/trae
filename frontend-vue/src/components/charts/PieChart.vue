<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import BaseChart from './BaseChart.vue'

const dashboard = useDashboardStore()

const chartOption = computed(() => {
  const records = dashboard.selectedRecords
  if (records.length === 0) return null

  return {
    tooltip: { trigger: 'item' },
    legend: { textStyle: { color: '#8b9bb4' } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: records.map(r => ({
        name: `${r.module_name || ''} (${r.tag || r.version || r.id})`,
        value: r.area_total ?? 0
      }))
    }]
  }
})
</script>

<template>
  <div class="card">
    <div class="card-header">面积分布</div>
    <div class="card-body">
      <BaseChart
        v-if="dashboard.selectedRecords.length > 0 && chartOption"
        chart-id="chart-pie"
        :option="chartOption"
        :height="'300px'"
      />
      <div v-else class="empty-state">请选择数据记录</div>
    </div>
  </div>
</template>