import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

describe('LoadingSpinner', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders default text', () => {
    const wrapper = mount(LoadingSpinner)
    expect(wrapper.text()).toContain('加载中...')
  })

  it('renders custom text', () => {
    const wrapper = mount(LoadingSpinner, {
      props: { text: '正在处理...' }
    })
    expect(wrapper.text()).toContain('正在处理...')
  })

  it('renders spinner element', () => {
    const wrapper = mount(LoadingSpinner)
    expect(wrapper.find('.spinner').exists()).toBe(true)
  })
})
