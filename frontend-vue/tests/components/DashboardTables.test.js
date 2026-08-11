import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { useDashboardStore } from '@/stores/dashboard'
import CombinedTableView from '@/components/dashboard/CombinedTableView.vue'
import TransposedTableView from '@/components/dashboard/TransposedTableView.vue'
import DirAggregateView from '@/components/dashboard/DirAggregateView.vue'
import DirModulesView from '@/components/dashboard/DirModulesView.vue'

function createDashboard() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const dashboard = useDashboardStore()
  dashboard.setRecords([
    {
      id: '1',
      project_id: 1,
      project_name: 'Chip',
      module_id: '10',
      module_name: 'cpu',
      version: 'regr_a',
      full_dir: '/work/regr_a/main',
      area_total: 100,
      power_total: 5,
      wns: -1,
      tns: -10,
      cell_count: 200
    },
    {
      id: '2',
      project_id: 1,
      project_name: 'Chip',
      module_id: '10',
      module_name: 'cpu',
      version: 'regr_b',
      full_dir: '/work/regr_b/main',
      area_total: 90,
      power_total: 4,
      wns: -0.5,
      tns: -5,
      cell_count: 180
    }
  ])
  dashboard.selectAll()
  return pinia
}

describe('dashboard analytical tables', () => {
  beforeEach(() => localStorage.clear())

  for (const [name, Component] of [
    ['combined', CombinedTableView],
    ['transposed', TransposedTableView],
    ['directory aggregate', DirAggregateView]
  ]) {
    it(`${name} uses shared sorting, resize, copy, and export controls`, () => {
      const wrapper = mount(Component, { global: { plugins: [createDashboard()] } })
      expect(wrapper.find('.data-table').exists()).toBe(true)
      expect(wrapper.find('.resize-handle').exists()).toBe(true)
      expect(wrapper.text()).toContain('Copy Markdown')
      expect(wrapper.text()).toContain('Export CSV')
    })
  }

  it('directory modules preserves prefix filtering through DataTable', async () => {
    const wrapper = mount(DirModulesView, { global: { plugins: [createDashboard()] } })
    await wrapper.find('input[type=text]').setValue('/work/regr_a')
    expect(wrapper.find('.data-table').exists()).toBe(true)
    expect(wrapper.text()).toContain('regr_a')
    expect(wrapper.text()).not.toContain('regr_b')
  })
})
