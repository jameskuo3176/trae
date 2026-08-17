import { nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import AreaChart from '@/components/charts/AreaChart.vue'
import { useDashboardStore } from '@/stores/dashboard'

let pinia
const chartMocks = vi.hoisted(() => ({
  initChart: vi.fn(),
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn()
}))

vi.mock('@/composables/useCharts', () => ({
  useCharts: () => chartMocks
}))

function mountAreaChart() {
  const chartType = ref('bar')
  const wrapper = mount(AreaChart, {
    global: {
      plugins: [pinia],
      provide: {
        chartSettings: {
          orientation: ref('vertical'),
          height: ref(360),
          labelMode: ref('both'),
          chartType,
          tableWidth: ref(0),
          tableFontSize: ref(12)
        }
      }
    }
  })
  return { wrapper, chartType }
}

describe('AreaChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pinia = createPinia()
    setActivePinia(pinia)
  })

  it('renders Total, Combinational, and Sequential in one intended chart host', () => {
    const dashboard = useDashboardStore()
    dashboard.setRecords([
      {
        id: 1,
        module_name: 'cpu',
        version: 'run-a',
        area_total: 100,
        area_combinational: 60,
        area_sequential: 40
      },
      {
        id: 2,
        module_name: 'cpu',
        version: 'run-b',
        area_total: 120,
        area_combinational: 70,
        area_sequential: 50
      }
    ])
    dashboard.selectAll()

    const { wrapper } = mountAreaChart()
    const hosts = wrapper.findAll('[data-chart-host]')

    expect(hosts).toHaveLength(1)
    expect(wrapper.findAll('.card')).toHaveLength(1)
    expect(chartMocks.initChart).toHaveBeenCalledTimes(1)
    expect(chartMocks.initChart.mock.calls[0][2]).toBe(hosts[0].element)

    const option = chartMocks.setOption.mock.calls.at(-1)[1]
    expect(option.legend.data).toEqual(['Total', 'Combinational', 'Sequential'])
    expect(option.series.map(series => series.data)).toEqual([
      [100, 120],
      [60, 70],
      [40, 50]
    ])
  })

  it('only lays out the active chart or table representation', async () => {
    const dashboard = useDashboardStore()
    dashboard.setRecords([
      {
        id: 1,
        module_name: 'cpu',
        version: 'run-a',
        area_total: 100,
        area_combinational: 60,
        area_sequential: 40
      }
    ])
    dashboard.selectAll()

    const { wrapper, chartType } = mountAreaChart()
    expect(wrapper.findAll('[data-chart-host]')).toHaveLength(1)
    expect(wrapper.find('.chart-table').exists()).toBe(false)

    chartType.value = 'table'
    await nextTick()
    await nextTick()

    expect(wrapper.find('[data-chart-host]').exists()).toBe(false)
    expect(wrapper.findAll('.chart-table')).toHaveLength(1)
    expect(wrapper.text()).toContain('Total')
    expect(wrapper.text()).toContain('100')
    expect(chartMocks.dispose).toHaveBeenCalledWith('chart-area')

    chartType.value = 'bar'
    await nextTick()
    await nextTick()

    expect(wrapper.findAll('[data-chart-host]')).toHaveLength(1)
    expect(wrapper.find('.chart-table').exists()).toBe(false)
    expect(chartMocks.initChart).toHaveBeenCalledTimes(2)
  })
})
