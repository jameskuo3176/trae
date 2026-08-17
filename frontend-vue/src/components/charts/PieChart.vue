<script setup>
import { computed, inject } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useRunLabelContext } from '@/composables/useChartPresentation'
import BaseChart from './BaseChart.vue'

const dashboard = useDashboardStore()
const chartSettings = inject('chartSettings', { labelMode: computed(() => 'both') })
const { runLabel } = useRunLabelContext()

const slices = [
  ['area_combinational', 'Combinational'],
  ['area_sequential', 'Sequential'],
  ['area_black_box', 'Black box'],
  ['area_macro', 'Macro']
]

const charts = computed(() =>
  dashboard.selectedRecords.map(record => ({
    id: dashboard.selectionKey(record),
    record,
    title: runLabel(record, chartSettings.labelMode?.value),
    option: {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: {
        type: 'scroll',
        bottom: 0,
        textStyle: { color: '#8b9bb4', fontSize: 10 }
      },
      series: [
        {
          type: 'pie',
          radius: ['34%', '66%'],
          center: ['50%', '43%'],
          avoidLabelOverlap: true,
          data: slices.map(([key, name]) => ({
            name,
            value: Number(record[key]) || 0
          }))
        }
      ]
    }
  }))
)
</script>

<template>
  <div class="card">
    <div class="card-header">面积分布</div>
    <div class="card-body">
      <div v-if="charts.length" class="pie-grid">
        <article v-for="chart in charts" :key="chart.id" class="pie-item">
          <h3>{{ chart.title }}</h3>
          <BaseChart
            :chart-id="`chart-pie-${chart.id}`"
            :option="chart.option"
            :records="[chart.record]"
          />
        </article>
      </div>
      <div v-else class="empty-state">请选择数据记录</div>
    </div>
  </div>
</template>

<style scoped>
.pie-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.pie-item {
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
}
.pie-item h3 {
  margin: 0;
  padding: 10px 12px 0;
  color: var(--color-text);
  font-size: 13px;
  text-align: center;
  overflow-wrap: anywhere;
}
</style>
