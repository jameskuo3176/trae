import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

describe('ConfirmDialog', () => {
  it('does not render when show is false', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: false }
    })
    expect(wrapper.find('.modal-overlay').exists()).toBe(false)
  })

  it('renders when show is true', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: 'Delete?', message: 'Are you sure?' }
    })
    expect(wrapper.text()).toContain('Delete?')
    expect(wrapper.text()).toContain('Are you sure?')
  })

  it('emits confirm event', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true }
    })
    await wrapper.find('.btn-danger').trigger('click')
    expect(wrapper.emitted('confirm')).toBeTruthy()
  })

  it('emits cancel event', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true }
    })
    await wrapper.find('.btn-default').trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
  })
})