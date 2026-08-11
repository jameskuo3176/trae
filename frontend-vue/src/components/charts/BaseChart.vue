<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useCharts } from '@/composables/useCharts'

const props = defineProps({
  chartId: { type: String, required: true },
  option: { type: Object, default: () => ({}) },
  height: { type: String, default: '400px' }
})

const { initChart, setOption, resize, dispose } = useCharts()
let chartInitialized = false

function handleResize() {
  resize(props.chartId)
}

function renderChart() {
  if (!chartInitialized) {
    initChart(props.chartId)
    chartInitialized = true
  }
  setOption(props.chartId, { ...props.option })
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  dispose(props.chartId)
  window.removeEventListener('resize', handleResize)
})

watch(
  () => props.option,
  () => {
    renderChart()
  },
  { deep: true }
)
</script>

<template>
  <div :id="chartId" class="chart-container" :style="{ height: height }" />
</template>

<style scoped>
.chart-container {
  width: 100%;
}
</style>
