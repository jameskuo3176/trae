import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from '@/components/common/DataTable.vue'

Object.defineProperty(navigator, 'clipboard', {
  configurable: true,
  value: { writeText: vi.fn().mockResolvedValue() }
})

const props = {
  rows: [
    { id: '1', name: 'beta', value: 2 },
    { id: '2', name: 'alpha', value: 1 }
  ],
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'value', label: 'Value', numeric: true }
  ]
}

describe('DataTable', () => {
  it('sorts columns through all three states', async () => {
    const wrapper = mount(DataTable, { props })
    const sort = wrapper.find('.sort-button')
    await sort.trigger('click')
    expect(wrapper.find('tbody tr td').text()).toBe('alpha')
    await sort.trigger('click')
    expect(wrapper.find('tbody tr td').text()).toBe('beta')
    await sort.trigger('click')
    expect(wrapper.find('tbody tr td').text()).toBe('beta')
  })

  it('copies Markdown export', async () => {
    const wrapper = mount(DataTable, { props })
    await wrapper
      .findAll('button')
      .find(button => button.text() === 'Copy Markdown')
      .trigger('click')
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('| Name | Value |')
    )
  })

  it('uses custom sort values and dynamic cell classes', async () => {
    const wrapper = mount(DataTable, {
      props: {
        rows: [
          { id: 'a', metric: 'first', composite: '1 / 20 / 3' },
          { id: 'b', metric: 'second', composite: '2 / 10 / 4' }
        ],
        columns: [
          { key: 'metric', label: 'Metric' },
          {
            key: 'composite',
            label: 'Timing',
            sortValue: row => Number(row.composite.split('/')[1]),
            class: row => (row.id === 'a' ? 'baseline-change' : '')
          }
        ]
      }
    })
    await wrapper.findAll('.sort-button')[1].trigger('click')
    expect(wrapper.find('tbody tr td').text()).toBe('second')
    expect(wrapper.find('td.baseline-change').exists()).toBe(true)
  })
})
