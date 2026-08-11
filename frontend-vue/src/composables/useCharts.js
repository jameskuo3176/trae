import * as echarts from 'echarts'

export function useCharts() {
  const chartInstances = new Map()

  function initChart(domId, theme = null) {
    const dom = document.getElementById(domId)
    if (!dom) return null
    const existing = echarts.getInstanceByDom(dom)
    if (existing) existing.dispose()
    const instance = echarts.init(dom, theme, { renderer: 'svg' })
    chartInstances.set(domId, instance)
    return instance
  }

  function getChart(domId) {
    return chartInstances.get(domId) || null
  }

  function setOption(domId, option, notMerge = true) {
    const chart = chartInstances.get(domId)
    if (chart) {
      chart.setOption(option, notMerge)
    }
  }

  function resize(domId) {
    const chart = chartInstances.get(domId)
    if (chart) chart.resize()
  }

  function resizeAll() {
    chartInstances.forEach(chart => chart.resize())
  }

  function dispose(domId) {
    const chart = chartInstances.get(domId)
    if (chart) {
      chart.dispose()
      chartInstances.delete(domId)
    }
  }

  function disposeAll() {
    chartInstances.forEach(chart => chart.dispose())
    chartInstances.clear()
  }

  return {
    initChart,
    getChart,
    setOption,
    resize,
    resizeAll,
    dispose,
    disposeAll
  }
}
