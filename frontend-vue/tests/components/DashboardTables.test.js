import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { useDashboardStore } from '@/stores/dashboard'
import CombinedTableView from '@/components/dashboard/CombinedTableView.vue'
import TransposedTableView from '@/components/dashboard/TransposedTableView.vue'
import DirAggregateView from '@/components/dashboard/DirAggregateView.vue'
import DirModulesView from '@/components/dashboard/DirModulesView.vue'
import RiskOverviewPanel from '@/components/dashboard/RiskOverviewPanel.vue'
import { dashboardApi } from '@/api/dashboard'

vi.mock('@/api/dashboard', () => ({
  dashboardApi: {
    setRisk: vi.fn(),
    clearRisk: vi.fn()
  }
}))

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
      cell_count: 200,
      risk: {
        rating: 'medium',
        auto_rating: 'medium',
        manual_rating: null,
        source: 'automatic',
        can_edit: true,
        summary: { worst_wns: -60, worst_tns: -1000 }
      }
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
      cell_count: 180,
      risk: {
        rating: 'low',
        auto_rating: 'low',
        manual_rating: null,
        source: 'automatic',
        can_edit: true,
        summary: { worst_wns: -30, worst_tns: -500 }
      }
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

  it('shows dashboard risk and persists a manual rating', async () => {
    dashboardApi.setRisk.mockResolvedValue({
      rating: 'high',
      auto_rating: 'medium',
      manual_rating: 'high',
      source: 'manual',
      can_edit: true,
      summary: { worst_wns: -60, worst_tns: -1000 }
    })
    const wrapper = mount(RiskOverviewPanel, { global: { plugins: [createDashboard()] } })
    expect(wrapper.text()).toContain('版本风险评估')
    await wrapper.get('select').setValue('high')
    expect(dashboardApi.setRisk).toHaveBeenCalledWith(1, '1', 'high')
  })

  it('renders each run risk assessment as its own row', () => {
    const wrapper = mount(RiskOverviewPanel, { global: { plugins: [createDashboard()] } })
    const rows = wrapper.findAll('.risk-grid article')

    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Run #1')
    expect(rows[0].text()).not.toContain('Run #2')
    expect(rows[1].text()).toContain('Run #2')
    expect(rows[1].text()).not.toContain('Run #1')
    expect(rows.every(row => row.findAll('select').length === 1)).toBe(true)
  })
})
