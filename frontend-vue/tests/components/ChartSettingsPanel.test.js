import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChartSettingsPanel from '@/components/dashboard/ChartSettingsPanel.vue'

describe('ChartSettingsPanel', () => {
  it('configures a shared table font size', async () => {
    const wrapper = mount(ChartSettingsPanel, {
      props: { tableFontSize: 12 }
    })

    const input = wrapper.get('input[aria-label="Table font size"]')
    expect(input.attributes('min')).toBe('10')
    expect(input.attributes('max')).toBe('18')

    await input.setValue('16')

    expect(wrapper.emitted('update:tableFontSize')).toEqual([[16]])
  })
})
