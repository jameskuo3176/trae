import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BaseChart from '@/components/charts/BaseChart.vue'

describe('BaseChart', () => {
  it('renders chart container with id', () => {
    const wrapper = mount(BaseChart, {
      props: {
        chartId: 'test-chart',
        option: {}
      }
    })
    const container = wrapper.find('#test-chart')
    expect(container.exists()).toBe(true)
  })

  it('applies custom height', () => {
    const wrapper = mount(BaseChart, {
      props: {
        chartId: 'test-chart',
        option: {},
        height: '500px'
      }
    })
    const container = wrapper.find('#test-chart')
    expect(container.attributes('style')).toContain('height: 500px')
  })
})
