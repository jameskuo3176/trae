<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useDcComparisonStore } from '@/stores/dcComparison'
import { useRunLabelContext } from '@/composables/useChartPresentation'
import { useTimingAnalysis } from '@/composables/useTimingAnalysis'
import BaseChart from './BaseChart.vue'

const dashboard = useDashboardStore()
const dc = useDcComparisonStore()
const { runLabel } = useRunLabelContext()

const aggregateMode = ref(false)
const selectedMetric = ref('wns_setup')
const selectedMetrics = ref(['wns_setup', 'tns_setup'])
const selectedClocks = ref([])
const scenarioSelection = computed({
  get: () => dc.preferences.scenarioIds,
  set: value => {
    dc.preferences.scenarioIds = value
  }
})
const pathGroupSelection = computed({
  get: () => dc.preferences.pathGroupIds,
  set: value => {
    dc.preferences.pathGroupIds = value
  }
})

const metrics = [
  { value: 'wns_setup', label: 'WNS Setup' },
  { value: 'tns_setup', label: 'TNS Setup' },
  { value: 'nvp_setup', label: 'NVP Setup' },
  { value: 'wns_hold', label: 'WNS Hold' },
  { value: 'tns_hold', label: 'TNS Hold' },
  { value: 'nvp_hold', label: 'NVP Hold' },
  { value: 'wns_computed', label: 'WNS (最差)' },
  { value: 'tns_computed', label: 'TNS (总负)' }
]

const {
  selectedScenarios,
  selectedPathGroups,
  availableScenarios,
  availablePathGroups,
  computedMetrics,
  hasTimingSections,
  selectAllScenarios,
  clearScenarios,
  selectAllPathGroups,
  clearPathGroups
} = useTimingAnalysis(
  () =>
    dashboard.selectedRecords.map(record => ({
      ...record,
      raw_dc_report: dashboard.rawReports[dashboard.selectionKey(record)]
    })),
  {
    selectedScenarios: scenarioSelection,
    selectedPathGroups: pathGroupSelection
  }
)

/** 计算指标名 → 记录 ID → 值的映射 */
const computedValueMap = computed(() => {
  const map = {}
  computedMetrics.value.forEach(item => {
    const key = dashboard.selectionKey(item.record)
    map[key] = { wns_computed: item.wns, tns_computed: item.tns }
  })
  return map
})

const availableClocks = computed(() => {
  const clockSet = new Set()
  dashboard.selectedRecords.forEach(r => {
    const clocks = (r.extra_fields && r.extra_fields.clocks) || {}
    Object.keys(clocks).forEach(k => clockSet.add(k))
  })
  return Array.from(clockSet).sort()
})

const selectedLabels = computed(() => {
  return dashboard.selectedRecords.map(r => runLabel(r))
})

const hasClockData = computed(() => {
  return availableClocks.value.length > 0
})

/** 获取单条记录在指定指标下的值，优先使用 computed 指标 */
function getMetricValue(record, metricKey) {
  if (metricKey === 'wns_computed' || metricKey === 'tns_computed') {
    const key = dashboard.selectionKey(record)
    return computedValueMap.value[key]?.[metricKey] ?? null
  }
  return record[metricKey] ?? null
}

/** 获取 clock 模式下的指标字段名 */
function clockField(metricKey) {
  const short = metricKey.replace('_setup', '').replace('_hold', '')
  const fieldMap = {
    wns: 'wns', tns: 'tns', nvp: 'nvp',
    wns_setup: 'wns', tns_setup: 'tns', nvp_setup: 'nvp',
    wns_hold: 'wns', tns_hold: 'tns', nvp_hold: 'nvp'
  }
  return fieldMap[short] || fieldMap[metricKey] || metricKey
}

const chartOption = computed(() => {
  const records = dashboard.selectedRecords
  if (records.length === 0) return null

  const cats = selectedLabels.value

  // 无 clock 数据：直接使用 record 字段或 computed 指标
  if (!hasClockData.value) {
    const metric = selectedMetric.value
    const m = metrics.find(m => m.value === metric)
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: [m?.label || metric], textStyle: { color: '#8b9bb4' } },
      xAxis: {
        type: 'category',
        data: cats,
        axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 }
      },
      yAxis: { type: 'value', name: 'ns', axisLabel: { color: '#8b9bb4' } },
      series: [
        {
          name: m?.label || metric,
          type: 'bar',
          data: records.map(r => getMetricValue(r, metric))
        }
      ]
    }
  }

  const clocks = selectedClocks.value.length > 0 ? selectedClocks.value : availableClocks.value

  // 聚合模式：指标 × 时钟 交叉
  if (aggregateMode.value) {
    const series = []
    selectedMetrics.value.forEach(metric => {
      clocks.forEach(clock => {
        series.push({
          name: `${clock} · ${metrics.find(m => m.value === metric)?.label || metric}`,
          type: 'bar',
          data: records.map(r => {
            const cd =
              (r.extra_fields && r.extra_fields.clocks && r.extra_fields.clocks[clock]) || {}
            return cd[clockField(metric)] ?? null
          })
        })
      })
    })
    return {
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', textStyle: { color: '#8b9bb4' } },
      xAxis: {
        type: 'category',
        data: cats,
        axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 }
      },
      yAxis: { type: 'value', name: 'ns', axisLabel: { color: '#8b9bb4' } },
      series
    }
  }

  // 单指标 × 多时钟
  const metric = selectedMetric.value
  const field = clockField(metric)
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
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: '#8b9bb4', rotate: cats.length > 6 ? 30 : 0 }
    },
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
          <input v-model="aggregateMode" type="checkbox" />
          按指标聚合
        </label>
        <select v-if="!aggregateMode" v-model="selectedMetric" class="btn-sm">
          <option v-for="m in metrics" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
        <select
          v-else
          v-model="selectedMetrics"
          multiple
          class="btn-sm"
          style="min-width: 120px; height: 56px"
        >
          <option v-for="m in metrics" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
        <select
          v-if="hasClockData"
          v-model="selectedClocks"
          multiple
          class="btn-sm"
          style="min-width: 100px; max-height: 80px"
        >
          <option v-for="c in availableClocks" :key="c" :value="c">{{ c }}</option>
        </select>
        <div v-if="hasClockData" class="clock-actions">
          <button class="btn btn-sm btn-default" @click="selectAllClocks">全选</button>
          <button class="btn btn-sm btn-default" @click="clearClocks">清空</button>
        </div>
      </div>
    </div>

    <!-- scenario / path_group 筛选 -->
    <div v-if="hasTimingSections" class="filter-bar">
      <span class="filter-label">Scenario</span>
      <select
        v-model="selectedScenarios"
        multiple
        class="btn-sm"
        style="min-width: 100px; max-height: 72px"
      >
        <option v-for="s in availableScenarios" :key="s" :value="s">{{ s }}</option>
      </select>
      <button class="btn btn-sm btn-default" @click="selectAllScenarios">全选</button>
      <button class="btn btn-sm btn-default" @click="clearScenarios">不限</button>

      <span class="filter-label">Path Group</span>
      <select
        v-model="selectedPathGroups"
        multiple
        class="btn-sm"
        style="min-width: 120px; max-height: 72px"
      >
        <option
          v-for="pg in availablePathGroups"
          :key="pg"
          :value="pg"
        >{{ pg }}</option>
      </select>
      <button class="btn btn-sm btn-default" @click="selectAllPathGroups">全选</button>
      <button class="btn btn-sm btn-default" @click="clearPathGroups">不限</button>
      <small class="analysis-rule-note">
        WNS = 所选范围内最小 WNS；TNS = 所有负值 *_tns 之和，非负值不参与抵消。
      </small>
    </div>

    <!-- WNS / TNS 摘要 -->
    <div v-if="hasTimingSections" class="wns-tns-summary">
      <table class="summary-table">
        <thead>
          <tr>
            <th>记录</th>
            <th>WNS (最差) ns</th>
            <th>TNS (总负) ns</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in computedMetrics" :key="dashboard.selectionKey(item.record)">
            <td class="summary-label">{{ runLabel(item.record) }}</td>
            <td :class="{ 'violation': item.wns != null && item.wns < 0 }">
              {{ item.wns != null ? item.wns.toFixed(3) : '—' }}
            </td>
            <td :class="{ 'violation': item.tns != null && item.tns < 0 }">
              {{ item.tns != null ? item.tns.toFixed(3) : '—' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card-body">
      <BaseChart
        v-if="dashboard.selectedRecords.length > 0 && chartOption"
        chart-id="chart-timing"
        :option="chartOption"
        :records="dashboard.selectedRecords"
      />
      <div v-else-if="dashboard.selectedRecords.length === 0" class="empty-state">
        请选择数据记录
      </div>
      <div v-else class="empty-state">暂无时序数据</div>
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

.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--color-border);
  flex-wrap: wrap;
}
.filter-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.analysis-rule-note {
  flex-basis: 100%;
  color: var(--color-text-secondary);
  font-size: 11px;
}

.wns-tns-summary {
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border);
  overflow-x: auto;
}
.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.summary-table th,
.summary-table td {
  padding: 4px 10px;
  text-align: left;
  white-space: nowrap;
}
.summary-table th {
  color: var(--color-text-secondary);
  font-weight: 500;
  border-bottom: 1px solid var(--color-border);
}
.summary-table td {
  color: var(--color-text);
}
.summary-table .summary-label {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.summary-table .violation {
  color: #e74c3c;
  font-weight: 600;
}
</style>