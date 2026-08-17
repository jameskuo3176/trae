import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { useDashboardStore } from '@/stores/dashboard'
import { useDcComparisonStore } from '@/stores/dcComparison'
import DcReportPanel from '@/components/dashboard/DcReportPanel.vue'
import { dashboardApi } from '@/api/dashboard'

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

function setupCanonicalPanel({ stubPicker = true } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const dashboard = useDashboardStore()
  dashboard.setRecords([
    {
      id: 'base',
      project_id: 1,
      module_name: 'cpu',
      version: 'base',
      wns_setup: -1,
      area_total: 100,
      power_total: 5,
      utilization: 0.7
    },
    {
      id: 'target',
      project_id: 1,
      module_name: 'cpu',
      version: 'target',
      wns_setup: -0.5,
      area_total: 90,
      power_total: 4,
      utilization: 0.75
    }
  ])
  dashboard.selectedIds = new Set(['base', 'target'])
  dashboard.setBaseline('base')
  const dc = useDcComparisonStore()
  const wrapper = mount(DcReportPanel, {
    global: { plugins: [pinia], stubs: { DcComparisonPicker: stubPicker } }
  })
  return { wrapper, dashboard, dc }
}

describe('DcReportPanel picker effects', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

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

  it('renders the canonical QoR matrix without raw reports', () => {
    const { wrapper } = setupCanonicalPanel()
    expect(wrapper.text()).toContain('Run × metric instrument')
    expect(wrapper.text()).toContain('Setup WNS')
    expect(wrapper.text()).toContain('cpu · base')
    expect(wrapper.text()).toContain('-1.00')
    expect(wrapper.text()).toContain('Total area')
  })

  it('loads lazy raw timing data for initially selected runs', async () => {
    setupCanonicalPanel()
    await flushPromises()

    expect(dashboardApi.rawReport).toHaveBeenCalledTimes(2)
    expect(dashboardApi.rawReport).toHaveBeenCalledWith(
      1,
      'base',
      expect.any(AbortSignal)
    )
    expect(dashboardApi.rawReport).toHaveBeenCalledWith(
      1,
      'target',
      expect.any(AbortSignal)
    )
  })

  it('only changes visible canonical metrics after picker Apply', async () => {
    const { wrapper, dc } = setupCanonicalPanel()
    await wrapper.find('.picker-button').trigger('click')
    dc.draft.sectionIds = ['qor_timing']
    dc.draft.metricIds = ['qor_timing.wns_setup']
    dc.cancel()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Total area')

    await wrapper.find('.picker-button').trigger('click')
    dc.draft.sectionIds = ['qor_timing']
    dc.draft.metricIds = ['qor_timing.wns_setup']
    dc.apply()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Setup WNS')
    expect(wrapper.text()).not.toContain('Total area')
    expect(wrapper.text()).not.toContain('Hold WNS')
  })

  it('shows canonical catalog labels in picker groups', async () => {
    const { wrapper } = setupCanonicalPanel({ stubPicker: false })
    await wrapper.find('.picker-button').trigger('click')
    const picker = wrapper.find('[role="dialog"]')
    expect(picker.text()).toContain('Timing')
    expect(picker.text()).toContain('Setup WNS')
    expect(picker.text()).toContain('Total area')
    expect(picker.text()).not.toContain('wns setup')
  })

  it('offers scenario and path-group timing scopes in the picker', async () => {
    const { wrapper, dashboard } = setupCanonicalPanel({ stubPicker: false })
    await flushPromises()
    dashboard.setRawReport('base', {
      timing: {
        final: {
          scenarios: {
            slow: {
              path_groups: {
                FUNCclk: { FUNCclk_WNS: -20, FUNCclk_TNS: -40 }
              }
            }
          }
        }
      }
    })
    await wrapper.vm.$nextTick()
    await wrapper.find('.picker-button').trigger('click')

    const picker = wrapper.find('[role="dialog"]')
    expect(picker.text()).toContain('Timing scope')
    expect(picker.text()).toContain('slow')
    expect(picker.text()).toContain('FUNCclk')
  })

  it('shows scoped scenario and path-group contributions with explicit missing values', async () => {
    const { wrapper, dashboard, dc } = setupCanonicalPanel()
    await flushPromises()
    dashboard.setRawReport('base', {
      timing: {
        default: {
          scenarios: {
            slow: {
              path_groups: {
                CORECLK: { WNS: -10, TNS: -30, NVP: 3 },
                BUSCLK: { WNS: -4, TNS: -7, NVP: 1 }
              }
            }
          }
        }
      }
    })
    dashboard.setRawReport('target', {
      timing: {
        default: {
          scenarios: {
            slow: {
              group_path: {
                CORECLK: { WNS: -8, TNS: -20, NVP: 2 }
              }
            }
          }
        }
      }
    })
    await wrapper.vm.$nextTick()

    const timing = wrapper.find('.canonical-section')
    expect(timing.text()).toContain('Scenario → path-group contributions')
    expect(timing.text()).toContain('slow')
    expect(timing.text()).toContain('CORECLK')
    expect(timing.text()).toContain('BUSCLK')
    expect(
      timing
        .findAll('.timing-group-table tbody tr')
        .find(row => row.text().includes('BUSCLK'))
        .text()
    ).toContain('—')
    expect(wrapper.vm.canonicalRows({
      id: 'qor_timing',
      metrics: [
        { id: 'wns_setup', label: 'Setup WNS' },
        { id: 'tns_setup', label: 'Setup TNS' }
      ]
    })).toEqual([
      expect.objectContaining({ base: -10, target: -8 }),
      expect.objectContaining({ base: -37, target: -20 })
    ])

    dc.preferences.pathGroupIds = ['CORECLK']
    await wrapper.vm.$nextTick()
    expect(timing.text()).not.toContain('BUSCLK')
    expect(wrapper.vm.canonicalRows({
      id: 'qor_timing',
      metrics: [{ id: 'tns_setup', label: 'Setup TNS' }]
    })[0]).toEqual(expect.objectContaining({ base: -30, target: -20 }))
  })

  it('selects only the clicked run when backend ids collide across projects', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const dashboard = useDashboardStore()
    dashboard.setRecords([
      {
        id: '7',
        project_id: 'alpha',
        module_name: 'cpu',
        version: 'alpha_run',
        area_total: 100
      },
      {
        id: '7',
        project_id: 'beta',
        module_name: 'gpu',
        version: 'beta_run',
        area_total: 80
      }
    ])
    const wrapper = mount(DcReportPanel, {
      global: { plugins: [pinia], stubs: { DcComparisonPicker: true } }
    })

    await wrapper.findAll('.run-item input')[0].trigger('change')
    expect(wrapper.findAll('.run-item.selected')).toHaveLength(1)
    expect(dashboard.selectedRecords).toHaveLength(1)
    expect(dashboard.selectedRecords[0].version).toBe('alpha_run')
    const matrix = wrapper.find('.canonical-section').text()
    expect(matrix).toContain('cpu · alpha_run')
    expect(matrix).not.toContain('gpu · beta_run')
  })

  it('preserves sticky metric and delta contrast on row hover', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/dashboard/DcReportPanel.vue'),
      'utf8'
    )
    expect(source).toContain('.data-table tbody tr:hover td:first-child')
    expect(source).toContain('.data-table tbody tr:hover td.change-better')
    expect(source).toContain('.data-table tbody tr:hover td.change-worse')
    expect(source).toContain('.data-table tbody tr:hover td.baseline')
  })
})
