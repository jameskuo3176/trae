import { nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import BaseChart from '@/components/charts/BaseChart.vue'

const chartMocks = vi.hoisted(() => ({
  initChart: vi.fn(),
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn()
}))

vi.mock('@/composables/useCharts', () => ({
  useCharts: () => chartMocks
}))

const cartesianOption = {
  xAxis: { type: 'category', data: ['old a', 'old b'] },
  yAxis: { type: 'value', name: 'Area' },
  series: [{ name: 'Total', type: 'bar', data: [10, 20] }]
}
const records = [
  { id: 'a', module_name: 'cpu', version: 'v1', full_dir: '/work/a' },
  { id: 'b', module_name: 'gpu', tag: 'v2', full_dir: '/work/b' }
]

function mountChart(settings = {}) {
  const provided = {
    orientation: ref(settings.orientation || 'vertical'),
    height: ref(settings.height || 500),
    labelMode: ref(settings.labelMode || 'both'),
    chartType: ref(settings.chartType || 'bar'),
    tableWidth: ref(0),
    tableFontSize: ref(settings.tableFontSize || 12)
  }
  const wrapper = mount(BaseChart, {
    props: { chartId: 'test-chart', option: cartesianOption, records },
    global: {
      plugins: [createPinia()],
      provide: { chartSettings: provided }
    }
  })
  return { wrapper, provided }
}

describe('BaseChart', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders chart container with id', () => {
    const { wrapper } = mountChart()
    const container = wrapper.find('#test-chart')
    expect(container.exists()).toBe(true)
  })

  it('reacts to height and resizes ECharts', async () => {
    const { wrapper, provided } = mountChart({ height: 360 })
    const container = wrapper.find('#test-chart')
    expect(container.attributes('style')).toContain('height: 360px')
    provided.height.value = 640
    await nextTick()
    await nextTick()
    expect(wrapper.find('#test-chart').attributes('style')).toContain('height: 640px')
    expect(chartMocks.resize).toHaveBeenCalledWith('test-chart')
  })

  it('applies orientation, labels, and line rendering to the chart option', async () => {
    const { provided } = mountChart()
    provided.orientation.value = 'horizontal'
    provided.labelMode.value = 'module_tag_dir'
    provided.chartType.value = 'line'
    await nextTick()
    await nextTick()
    const rendered = chartMocks.setOption.mock.calls.at(-1)[1]
    expect(rendered.xAxis.type).toBe('value')
    expect(rendered.yAxis.type).toBe('category')
    expect(rendered.yAxis.data[0]).toBe('cpu · v1 · /work/a')
    expect(rendered.grid).toMatchObject({ containLabel: true, left: 18 })
    expect(rendered.yAxis.axisLabel).toMatchObject({ overflow: 'truncate', width: 220 })
    expect(rendered.series[0]).toMatchObject({ type: 'line', showSymbol: true })
  })

  it('replaces the canvas with an equivalent table in table mode', async () => {
    const { wrapper, provided } = mountChart({ tableFontSize: 16 })
    provided.chartType.value = 'table'
    await nextTick()
    expect(wrapper.find('#test-chart').exists()).toBe(false)
    expect(wrapper.find('.chart-table').exists()).toBe(true)
    expect(wrapper.get('.chart-table').attributes('style')).toContain('font-size: 16px')
    expect(wrapper.text()).toContain('cpu · v1')
    expect(wrapper.text()).toContain('20')
    expect(chartMocks.dispose).toHaveBeenCalledWith('test-chart')
  })
})
