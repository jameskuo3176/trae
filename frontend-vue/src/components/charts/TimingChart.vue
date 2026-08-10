<script setup>
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import BaseChart from './BaseChart.vue'

const dashboard = useDashboardStore()

const aggregateMode = ref(false)
const selectedMetric = ref('wns_setup')
const selectedMetrics = ref(['wns_setup', 'tns_setup'])
const selectedClocks = ref([])

const metrics = [
  { value: 'wns_setup', label: 'WNS Setup' },
  { value: 'tns_setup', label: 'TNS Setup' },
  { value: 'nvp_setup', label: 'NVP Setup' },
  { value: 'wns_hold', label: 'WNS Hold' },
  { value: 'tns_hold', label: 'TNS Hold' },
  { value: 'nvp_hold', label: 'NVP Hold' }
]

const availableClocks = computed(() => {
  const clockSet = new Set()
  dashboard.selectedRecords.forEach(r => {
    const clocks = (r.extra_fields && r.extra_fields.clocks) || {}
    Object.keys(clocks).forEach(k => clockSet.add(k))
  })
  return Array.from(clockSet).sort()
})

const selectedLabels = computed(() => {
  return dashboard.selectedRecords.map(r => {
    let label = r.module_name || ''
    const tag = r.tag || r.version
    if (tag) label += ` (${tag})`
    return label
  })
})

const hasClockData = computed(() => {
  return availableClocks.value.length > 0
})

const chartOption = computed(() => {
  const records = dashboard.selectedRecords
  if (records.length === 0) return null

  const cats = selectedLabels.value

  if (!hasClockData.value) {
    const metric = selectedMetric.value
    const m = metrics.find(m => m.value === metric)
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: [m?.label || metric], textStyle: { color: '#8b9bb4' } },
      xAxis: { type: 'category', data: cats, axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 } },
      yAxis: { type: 'value', name: 'ns', axisLabel: { color: '#8b9bb4' } },
      series: [{
        name: m?.label || metric,
        type: 'bar',
        data: records.map(r => r[metric] ?? null)
      }]
    }
  }

  const clocks = selectedClocks.value.length > 0 ? selectedClocks.value : availableClocks.value

  if (aggregateMode.value) {
    const series = []
    selectedMetrics.value.forEach(metric => {
      clocks.forEach(clock => {
        series.push({
          name: `${clock} · ${metrics.find(m => m.value === metric)?.label || metric}`,
          type: 'bar',
          data: records.map(r => {
            const cd = (r.extra_fields && r.extra_fields.clocks && r.extra_fields.clocks[clock]) || {}
            const shortMetric = metric.replace('_setup', '').replace('_hold', '')
            const fieldMap = {
              wns: 'wns', tns: 'tns', nvp: 'nvp',
              wns_setup: 'wns', tns_setup: 'tns', nvp_setup: 'nvp',
              wns_hold: 'wns', tns_hold: 'tns', nvp_hold: 'nvp'
            }
            const field = fieldMap[shortMetric] || fieldMap[metric] || metric
            return cd[field] ?? null
          })
        })
      })
    })
    return {
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', textStyle: { color: '#8b9bb4' } },
      xAxis: { type: 'category', data: cats, axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 } },
      yAxis: { type: 'value', name: 'ns', axisLabel: { color: '#8b9bb4' } },
      series
    }
  }

  const metric = selectedMetric.value
  const shortMetric = metric.replace('_setup', '').replace('_hold', '')
  const fieldMap = {
    wns: 'wns', tns: 'tns', nvp: 'nvp',
    wns_setup: 'wns', tns_setup: 'tns', nvp_setup: 'nvp',
    wns_hold: 'wns', tns_hold: 'tns', nvp_hold: 'nvp'
  }
  const field = fieldMap[shortMetric] || fieldMap[metric] || metric

  const series = clocks.map(clock => ({
    name: clock,
    type: 'bar',
    data: records.map(r => {
      const cd = (r.extra_fields && r.extra_fields.clocks && r.extra_fields.clocks[clock]) || {}
      return cd[field] ?? null
    })
  }))

  return {
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', textStyle: { color: '#8b9bb4' } },
    xAxis: { type: 'category', data: cats, axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 } },
    yAxis: { type: 'value', name: 'ns', axisLabel: { color: '#8b9bb4' } },
    series
  }
})

function selectAllClocks() {
  selectedClocks.value = [...availableClocks.value]
}

function clearClocks() {
  selectedClocks.value = []
}
</script>

<template>
  <div class="card">
    <div class="card-header">
      <span>时序分析</span>
      <div class="timing-controls">
        <label class="control-label">
          <input type="checkbox" v-model="aggregateMode" />
          按指标聚合
        </label>
        <select v-if="!aggregateMode" v-model="selectedMetric" class="btn-sm">
          <option v-for="m in metrics" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
        <select v-else v-model="selectedMetrics" multiple class="btn-sm" style="min-width: 120px; height: 56px;">
          <option v-for="m in metrics" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
        <select v-if="hasClockData" v-model="selectedClocks" multiple class="btn-sm" style="min-width: 100px; max-height: 80px;">
          <option v-for="c in availableClocks" :key="c" :value="c">{{ c }}</option>
        </select>
        <div v-if="hasClockData" class="clock-actions">
          <button class="btn btn-sm btn-default" @click="selectAllClocks">全选</button>
          <button class="btn btn-sm btn-default" @click="clearClocks">清空</button>
        </div>
      </div>
    </div>
    <div class="card-body">
      <BaseChart
        v-if="dashboard.selectedRecords.length > 0 && chartOption"
        chart-id="chart-timing"
        :option="chartOption"
        :height="'400px'"
      />
      <div v-else-if="dashboard.selectedRecords.length === 0" class="empty-state">
        请选择数据记录
      </div>
      <div v-else class="empty-state">
        暂无时序数据
      </div>
    </div>
  </div>
</template>

<style scoped>
.timing-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.control-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.clock-actions {
  display: flex;
  gap: 4px;
}
</style>