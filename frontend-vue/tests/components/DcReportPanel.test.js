import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { useDashboardStore } from '@/stores/dashboard'
import { useDcComparisonStore } from '@/stores/dcComparison'
import DcReportPanel from '@/components/dashboard/DcReportPanel.vue'

vi.mock('@/api/dashboard', () => ({
  dashboardApi: { rawReport: vi.fn().mockResolvedValue({}) }
}))

function setupPanel() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const dashboard = useDashboardStore()
  dashboard.setRecords([
    { id: 'base', project_id: 1, module_name: 'cpu', version: 'regr_base' },
    { id: 'target', project_id: 1, module_name: 'cpu', version: 'regr_target' }
  ])
  dashboard.selectedIds = new Set(['base', 'target'])
  dashboard.setBaseline('base')
  dashboard.setRawReport('base', {
    timing: { WNS: -1, composite: '-1 / -20 / 3', alternate: '-2 / -10 / 5' }
  })
  dashboard.setRawReport('target', {
    timing: { WNS: -0.5, composite: '-0.5 / -15 / 2', alternate: '-3 / -5 / 8' }
  })
  const dc = useDcComparisonStore()
  const wrapper = mount(DcReportPanel, {
    global: { plugins: [pinia], stubs: { DcComparisonPicker: true } }
  })
  return { wrapper, dashboard, dc }
}

describe('DcReportPanel picker effects', () => {
  beforeEach(() => localStorage.clear())

  it('applies baseline change classes only when showChange is enabled', () => {
    const { wrapper, dc } = setupPanel()
    const section = { id: 'timing', metrics: ['WNS'] }
    dc.preferences.showChange = true
    expect(wrapper.vm.sectionRows(section)[0].__classes.target).toBe('change-better')
    dc.preferences.showChange = false
    expect(wrapper.vm.sectionRows(section)[0].__classes.target).toBe('')
  })

  it('uses the selected WNS/TNS/NVP component for timing sorting', () => {
    const { wrapper, dc } = setupPanel()
    const section = { id: 'timing', metrics: ['composite', 'alternate'] }
    const rows = wrapper.vm.sectionRows(section)
    const targetColumn = wrapper.vm.sectionColumns().find(column => column.key === 'target')
    dc.preferences.sortMetric = 'TNS'
    expect(targetColumn.sortValue(rows[0])).toBe(-15)
    dc.preferences.sortMetric = 'NVP'
    expect(targetColumn.sortValue(rows[0])).toBe(2)
  })

  it('keeps VS checklist changes draft until Apply VS', async () => {
    const { wrapper, dashboard, dc } = setupPanel()
    dashboard.selectedIds = new Set(['base'])
    dc.preferences.vsMode = true
    await wrapper.vm.$nextTick()
    await wrapper.findAll('.run-item input')[1].trigger('change')
    expect(dashboard.selectedIds.has('target')).toBe(false)
    expect(wrapper.vm.vsDraftIds.has('target')).toBe(true)
    await wrapper
      .findAll('button')
      .find(button => button.text() === 'Apply VS')
      .trigger('click')
    expect(dashboard.selectedIds.has('target')).toBe(true)
    expect(dc.preferences.vsMode).toBe(false)
  })
})
