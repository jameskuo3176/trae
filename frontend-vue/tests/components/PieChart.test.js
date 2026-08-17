import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import PieChart from '@/components/charts/PieChart.vue'
import { useDashboardStore } from '@/stores/dashboard'

describe('PieChart', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders one four-component pie per selected run', () => {
    const dashboard = useDashboardStore()
    dashboard.setRecords([
      {
        id: 1,
        project_id: 10,
        version: 'run-a',
        area_combinational: 10,
        area_sequential: 20,
        area_black_box: 3,
        area_macro: 4,
        area_total: 999
      },
      {
        id: 2,
        project_id: 10,
        version: 'run-b',
        area_combinational: 5,
        area_sequential: 6,
        area_black_box: 0,
        area_macro: 1,
        area_total: 888
      }
    ])
    dashboard.selectAll()
    const wrapper = mount(PieChart, {
      global: {
        stubs: {
          BaseChart: {
            ...defineComponent({ name: 'BaseChart', props: ['option', 'records'] }),
            props: ['option', 'records'],
            template: '<div class="base-chart-stub" />'
          }
        }
      }
    })

    const charts = wrapper.findAllComponents({ name: 'BaseChart' })
    expect(charts).toHaveLength(2)
    expect(charts[0].props('records')).toHaveLength(1)
    expect(charts[0].props('option').series[0].data).toEqual([
      { name: 'Combinational', value: 10 },
      { name: 'Sequential', value: 20 },
      { name: 'Black box', value: 3 },
      { name: 'Macro', value: 4 }
    ])
  })

  it('shows an empty state when no runs are selected', () => {
    const wrapper = mount(PieChart, {
      global: { stubs: { BaseChart: true } }
    })
    expect(wrapper.get('.empty-state').text()).toContain('请选择数据记录')
  })
})
