import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TimingChart from '@/components/charts/TimingChart.vue'
import { useDashboardStore } from '@/stores/dashboard'

describe('TimingChart timing units', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('labels unchanged timing values as picoseconds', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const dashboard = useDashboardStore()
    dashboard.setRecords([
      {
        id: 1,
        module_name: 'core',
        version: 'v1',
        wns_setup: 16858,
        tns_setup: 0,
        extra_fields: {
          timing_sections: {
            default: {
              slow: {
                CORE: { wns: 16858, tns: 0 }
              }
            }
          }
        }
      }
    ])
    dashboard.toggleSelect(1)

    const wrapper = mount(TimingChart, {
      global: {
        plugins: [pinia],
        stubs: { BaseChart: true }
      }
    })

    expect(wrapper.text()).toContain('WNS (最差) ps')
    expect(wrapper.text()).toContain('TNS (总负) ps')
    expect(wrapper.getComponent({ name: 'BaseChart' }).props('option').yAxis.name).toBe('ps')
    expect(wrapper.text()).toContain('16858.000')
    expect(wrapper.text()).not.toContain('16.858')
  })
})
