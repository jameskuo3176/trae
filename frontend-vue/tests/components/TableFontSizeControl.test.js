import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TableFontSizeControl from '@/components/common/TableFontSizeControl.vue'
import { useTheme } from '@/composables/useTheme'

describe('TableFontSizeControl', () => {
  beforeEach(() => {
    localStorage.clear()
    useTheme().setTableFontSize(12)
  })

  it('updates every page through the global table font variable', async () => {
    const wrapper = mount(TableFontSizeControl)

    await wrapper.get('input[aria-label="表格字号"]').setValue('17')

    expect(useTheme().tableFontSize.value).toBe(17)
    expect(document.documentElement.style.getPropertyValue('--table-font-size')).toBe('17px')
    expect(wrapper.get('output').text()).toBe('17px')
  })
})
