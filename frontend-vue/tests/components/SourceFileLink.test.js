import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import SourceFileLink from '@/components/common/SourceFileLink.vue'

describe('SourceFileLink', () => {
  it('renders a client gvim link with an optional line', () => {
    const wrapper = mount(SourceFileLink, {
      props: { path: '/workspace/rtl/top.sv', line: 17 }
    })

    expect(wrapper.get('a').attributes('href')).toBe(
      'gvim://open?path=%2Fworkspace%2Frtl%2Ftop.sv&line=17'
    )
    expect(wrapper.text()).toContain('/workspace/rtl/top.sv')
  })

  it('offers a copy fallback', async () => {
    const writeText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText }
    })
    const wrapper = mount(SourceFileLink, {
      props: { path: 'D:\\runs\\report.rpt' }
    })

    await wrapper.get('button').trigger('click')
    expect(writeText).toHaveBeenCalledWith('D:\\runs\\report.rpt')
    expect(wrapper.text()).toContain('已复制')
  })
})
