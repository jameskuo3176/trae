import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import StatCard from '@/components/common/StatCard.vue'

describe('StatCard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders label and value', () => {
    const wrapper = mount(StatCard, {
      props: { label: 'Total', value: '42' }
    })
    expect(wrapper.text()).toContain('Total')
    expect(wrapper.text()).toContain('42')
  })

  it('renders trend indicator', () => {
    const wrapper = mount(StatCard, {
      props: { label: 'Growth', value: '10%', trend: '+5%' }
    })
    expect(wrapper.text()).toContain('+5%')
    expect(wrapper.find('.up').exists()).toBe(true)
  })

  it('applies custom color', () => {
    const wrapper = mount(StatCard, {
      props: { label: 'Custom', value: '100', color: '#ff0000' }
    })
    const valueEl = wrapper.find('.stat-value')
    expect(valueEl.attributes('style')).toContain('color: rgb(255, 0, 0)')
  })
})
