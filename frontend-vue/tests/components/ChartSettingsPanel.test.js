import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChartSettingsPanel from '@/components/dashboard/ChartSettingsPanel.vue'

describe('ChartSettingsPanel', () => {
  it('offers version-based label modes and emits the persisted setting value', async () => {
    const wrapper = mount(ChartSettingsPanel, {
      props: { labelMode: 'version' }
    })
    const labels = wrapper.findAll('label').find(label => label.text().includes('Labels'))
    const select = labels.get('select')

    expect(select.findAll('option').map(option => option.attributes('value'))).toEqual(
      expect.arrayContaining(['version', 'version_tag'])
    )
    expect(select.element.value).toBe('version')

    await select.setValue('version_tag')
    expect(wrapper.emitted('update:labelMode')).toEqual([['version_tag']])
  })

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
