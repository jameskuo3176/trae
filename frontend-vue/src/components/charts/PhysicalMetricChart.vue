<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import BaseChart from './BaseChart.vue'

const props = defineProps({
  metric: { type: String, required: true },
  title: { type: String, required: true },
  unit: { type: String, default: '' },
  colorIdx: { type: Number, default: 0 },
  scaleToPercent: { type: Boolean, default: false },
  multiMetrics: { type: Array, default: () => null }
})

const COLORS = [
  '#1a237e',
  '#e91e63',
  '#00838f',
  '#ff8f00',
  '#43a047',
  '#5e35b1',
  '#6d4c41',
  '#00897b'
]
const dashboard = useDashboardStore()

function getUnifiedValue(r, metric) {
  if (r.raw_dc_report) {
    let raw = r.raw_dc_report
    if (typeof raw === 'string') {
      try {
        raw = JSON.parse(raw)
      } catch {
        return null
      }
    }
    const parts = metric.split('.')
    let val = raw
    for (const p of parts) {
      if (val == null) return null
      val = val[p]
    }
    return val
  }
  return r[metric] ?? null
}

function parseValue(raw) {
  if (raw == null) return null
  const v = parseFloat(raw)
  if (isNaN(v)) return null
  return props.scaleToPercent ? Math.round(v * 1000) / 10 : Math.round(v * 1000) / 1000
}

const chartOption = computed(() => {
  const records = dashboard.selectedRecords
  if (records.length === 0) return null

  const cats = records.map(r => {
    let label = r.module_name || ''
    const tag = r.tag || r.version
    if (tag) label += ` (${tag})`
    return label
  })

  if (props.multiMetrics) {
    const series = props.multiMetrics.map((m, i) => ({
      name: m.label || m.key,
      type: 'bar',
      data: records.map(r => parseValue(getUnifiedValue(r, m.key))),
      itemStyle: { color: COLORS[(props.colorIdx + i) % COLORS.length] }
    }))
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: {
        data: props.multiMetrics.map(m => m.label || m.key),
        textStyle: { color: '#8b9bb4' }
      },
      xAxis: {
        type: 'category',
        data: cats,
        axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 }
      },
      yAxis: { type: 'value', name: props.unit, axisLabel: { color: '#8b9bb4' } },
      series
    }
  }

  const vals = records.map(r => parseValue(getUnifiedValue(r, props.metric)))

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: [props.title], textStyle: { color: '#8b9bb4' } },
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 }
    },
    yAxis: { type: 'value', name: props.unit, axisLabel: { color: '#8b9bb4' } },
    series: [
      {
        name: props.title,
        type: 'bar',
        data: vals,
        itemStyle: { color: COLORS[props.colorIdx % COLORS.length] }
      }
    ]
  }
})
</script>

<template>
  <div class="card">
    <div class="card-header">{{ title }}</div>
    <div class="card-body">
      <BaseChart
        v-if="dashboard.selectedRecords.length > 0 && chartOption"
        :chart-id="`chart-${metric.replace(/\./g, '-')}`"
        :option="chartOption"
        :height="'400px'"
      />
      <div v-else class="empty-state">请选择数据记录</div>
    </div>
  </div>
</template>
