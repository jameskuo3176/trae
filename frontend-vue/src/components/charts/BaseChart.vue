<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useCharts } from '@/composables/useCharts'
import { useChartPresentation } from '@/composables/useChartPresentation'

const props = defineProps({
  chartId: { type: String, required: true },
  option: { type: Object, default: () => ({}) },
  height: { type: [String, Number], default: '400px' },
  records: { type: Array, default: () => [] }
})

const { initChart, setOption, resize, dispose } = useCharts()
const { chartType, height, option, table, tableWidth, tableFontSize } =
  useChartPresentation(props)
const isTable = computed(() => chartType.value === 'table')
const chartHost = ref(null)
let chartInitialized = false
let themeObserver

function handleResize() {
  resize(props.chartId)
}

function renderChart() {
  if (isTable.value) return
  if (!chartInitialized) {
    chartInitialized = initChart(props.chartId, null, chartHost.value) !== null
    if (!chartInitialized) return
  }
  const styles = getComputedStyle(document.documentElement)
  const secondaryText = styles.getPropertyValue('--color-text-secondary').trim()
  const border = styles.getPropertyValue('--color-border').trim()
  const replaceThemeColors = value => {
    if (Array.isArray(value)) return value.map(replaceThemeColors)
    if (value && typeof value === 'object') {
      return Object.fromEntries(
        Object.entries(value).map(([key, nestedValue]) => [key, replaceThemeColors(nestedValue)])
      )
    }
    if (value === '#8b9bb4') return secondaryText
    return value
  }
  const themedOption = replaceThemeColors(option.value)
  themedOption.textStyle = { color: secondaryText, ...(themedOption.textStyle || {}) }
  themedOption.tooltip = {
    backgroundColor: styles.getPropertyValue('--color-surface-elevated').trim(),
    borderColor: border,
    textStyle: { color: styles.getPropertyValue('--color-text').trim() },
    ...(themedOption.tooltip || {})
  }
  setOption(props.chartId, themedOption)
}

onMounted(() => {
  renderChart()
  themeObserver = new MutationObserver(renderChart)
  themeObserver.observe(document.body, { attributes: true, attributeFilter: ['data-theme'] })
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  themeObserver?.disconnect()
  dispose(props.chartId)
  window.removeEventListener('resize', handleResize)
})

watch(
  [option, height, isTable],
  async ([, , tableMode], [, previousHeight, previousTableMode]) => {
    if (tableMode) {
      if (chartInitialized) dispose(props.chartId)
      chartInitialized = false
      return
    }
    await nextTick()
    renderChart()
    if (previousTableMode || previousHeight !== height.value) resize(props.chartId)
  },
  { deep: true, flush: 'post' }
)
</script>

<template>
  <div
    v-if="isTable"
    class="chart-table-scroll"
    :style="{
      maxHeight: height,
      width: tableWidth ? `${tableWidth}px` : undefined
    }"
  >
    <table class="chart-table" :style="{ fontSize: `${tableFontSize}px` }">
      <thead>
        <tr>
          <th v-for="column in table.columns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, rowIndex) in table.rows" :key="`${row.category}-${rowIndex}`">
          <th scope="row">{{ row.category }}</th>
          <td v-for="(value, index) in row.values" :key="index">
            {{ value == null || value === '' ? '—' : value }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div
    v-else
    :id="chartId"
    ref="chartHost"
    class="chart-container"
    data-chart-host
    :style="{ height }"
  />
</template>

<style scoped>
.chart-container {
  width: 100%;
}
.chart-table-scroll {
  max-width: 100%;
  overflow: auto;
  border: 1px solid var(--color-border);
}
.chart-table {
  width: 100%;
  border-collapse: collapse;
  color: var(--color-text);
  font-size: var(--table-font-size, 12px);
  font-variant-numeric: tabular-nums;
}
.chart-table th,
.chart-table td {
  padding: 7px 10px;
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  text-align: right;
  white-space: nowrap;
}
.chart-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--color-surface-hover);
  color: var(--color-text);
  font-weight: 700;
}
.chart-table th:first-child {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--color-surface);
  text-align: left;
}
.chart-table thead th:first-child {
  z-index: 3;
  background: var(--color-surface-hover);
}
.chart-table tbody tr:hover th,
.chart-table tbody tr:hover td {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
</style>
