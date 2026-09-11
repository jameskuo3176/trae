import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { useDashboardConfigState } from '@/composables/useDashboardConfigState'
import { dashboardApi } from '@/api/dashboard'

vi.mock('@/api/dashboard', () => ({
  dashboardApi: {
    modules: vi.fn(),
    versions: vi.fn(),
    records: vi.fn()
  }
}))

describe('useDashboardConfigState', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
    dashboardApi.modules.mockResolvedValue({ modules: [{ id: 7, name: 'CPU' }], meta: {} })
    dashboardApi.versions.mockResolvedValue(['regr_a', 'regr_b'])
    dashboardApi.records.mockResolvedValue({
      records: [
        { id: '10', project_id: 1, module_id: 7, version: 'regr_a', full_dir: '/a' },
        { id: '11', project_id: 1, module_id: 7, version: 'regr_b', full_dir: '/b' }
      ],
      pagination: { page: 1, page_size: 200, total: 2, pages: 1 },
      meta: {}
    })
  })

  it('snapshots filters, settings, selection, and restores them on apply', async () => {
    const filters = useFiltersStore()
    const dashboard = useDashboardStore()
    filters.projects = [{ id: 1, name: 'P1' }]
    filters.projectIds = ['1']
    filters.moduleIds = ['7']
    filters.versionIds = ['regr_b']
    filters.versionFilterApplied = true
    filters.dirPrefix = '/b'
    dashboard.setRecords([
      { id: '10', project_id: 1, module_id: 7, version: 'regr_a', full_dir: '/a' },
      { id: '11', project_id: 1, module_id: 7, version: 'regr_b', full_dir: '/b' }
    ])
    dashboard.selectedIds = new Set(['11'])
    dashboard.setBaseline('11')

    const { snapshot, apply } = useDashboardConfigState()
    const payload = snapshot({
      orientation: 'horizontal',
      height: 640,
      labelMode: 'version_tag',
      chartType: 'line',
      tableWidth: 800,
      tableFontSize: 14,
      activeView: 'combined'
    })

    expect(payload.projectIds).toEqual(['1'])
    expect(payload.moduleIds).toEqual(['7'])
    expect(payload.versionIds).toEqual(['regr_b'])
    expect(payload.selectedIds).toEqual(['11'])
    expect(payload.baselineId).toBe('11')
    expect(payload.activeView).toBe('combined')

    // Mutate live state, then re-apply saved config.
    filters.projectIds = []
    filters.moduleIds = []
    filters.versionIds = []
    filters.dirPrefix = ''
    dashboard.selectedIds = new Set(['10'])
    const settings = {
      orientation: 'vertical',
      height: 500,
      labelMode: 'both',
      chartType: 'bar',
      tableWidth: 0,
      tableFontSize: 12,
      activeView: 'charts'
    }

    await apply(payload, settings)

    expect(settings.activeView).toBe('combined')
    expect(settings.labelMode).toBe('version_tag')
    expect(settings.height).toBe(640)
    expect(filters.projectIds).toEqual(['1'])
    expect(filters.moduleIds).toEqual(['7'])
    expect(filters.versionIds).toEqual(['regr_b'])
    expect(filters.dirPrefix).toBe('/b')
    expect([...dashboard.selectedIds]).toEqual(['11'])
    expect(dashboard.baselineId).toBe('11')
    expect(dashboardApi.records).toHaveBeenCalled()
  })

  it('does not wipe filters when applying settings-only legacy payloads', async () => {
    const filters = useFiltersStore()
    filters.projectIds = ['1']
    filters.moduleIds = ['7']
    filters.versionIds = ['regr_a']
    const settings = {
      orientation: 'vertical',
      height: 500,
      labelMode: 'both',
      chartType: 'bar',
      tableWidth: 0,
      tableFontSize: 12,
      activeView: 'charts'
    }
    const { apply } = useDashboardConfigState()
    await apply({ activeView: 'transposed', labelMode: 'module', height: 800 }, settings)
    expect(settings.activeView).toBe('transposed')
    expect(filters.projectIds).toEqual(['1'])
    expect(filters.moduleIds).toEqual(['7'])
  })
})
