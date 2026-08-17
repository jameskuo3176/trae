import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDashboardData } from '@/composables/useDashboardData'
import { useDashboardStore } from '@/stores/dashboard'
import { useFiltersStore } from '@/stores/filters'
import { dashboardApi } from '@/api/dashboard'

vi.mock('@/api/projects', () => ({
  projectsApi: { list: vi.fn().mockResolvedValue([]) }
}))
vi.mock('@/api/dashboard', () => ({
  dashboardApi: {
    modules: vi.fn(),
    versions: vi.fn(),
    records: vi.fn()
  }
}))

describe('useDashboardData module identity contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    dashboardApi.modules.mockResolvedValue({ modules: [], meta: {} })
    dashboardApi.versions.mockResolvedValue([])
  })

  it('uses GlobalModule IDs for all projects and preserves colliding record IDs', async () => {
    const filters = useFiltersStore()
    const dashboard = useDashboardStore()
    filters.moduleIds = ['77']
    dashboardApi.records.mockResolvedValue({
      records: [
        { id: 1, project_id: 10, module_id: 77, module_name: 'CPU' },
        { id: 1, project_id: 20, module_id: 77, module_name: 'CPU' }
      ],
      pagination: { total: 2 },
      meta: {}
    })

    await useDashboardData().loadDashboardData()

    expect(dashboardApi.records).toHaveBeenCalledWith(
      expect.objectContaining({ project_ids: undefined, module_id: '77' }),
      expect.any(AbortSignal)
    )
    expect(dashboard.records).toHaveLength(2)
    expect(new Set(dashboard.records.map(dashboard.selectionKey)).size).toBe(2)
  })

  it('uses the same identity contract for one project and reports unmapped modules', async () => {
    const filters = useFiltersStore()
    const dashboard = useDashboardStore()
    filters.projectIds = ['10']
    filters.moduleIds = ['77']
    dashboardApi.records.mockResolvedValue({
      records: [{ id: 3, project_id: 10, module_id: null, module_name: 'legacy' }],
      pagination: { total: 1 },
      meta: {
        unmapped_modules: [{ project_id: 10, record_id: '3', legacy_module_id: 4 }]
      }
    })

    await useDashboardData().loadDashboardData()

    expect(dashboardApi.records).toHaveBeenCalledWith(
      expect.objectContaining({ project_ids: '10', module_id: '77' }),
      expect.any(AbortSignal)
    )
    expect(dashboard.diagnostics).toHaveLength(1)
  })

  it('keeps an applied version pattern with no matches empty', async () => {
    const filters = useFiltersStore()
    const dashboard = useDashboardStore()
    dashboard.setRecords([{ id: 'old', project_id: 10 }])
    dashboard.selectFirstN()
    filters.versionFilterApplied = true
    filters.versionIds = []

    await useDashboardData().loadDashboardData()

    expect(dashboardApi.records).not.toHaveBeenCalled()
    expect(dashboard.records).toEqual([])
    expect(dashboard.selectedRecords).toEqual([])
    expect(dashboard.pagination.total).toBe(0)
  })

  it('loads and reselects only records matching the applied version', async () => {
    const filters = useFiltersStore()
    const dashboard = useDashboardStore()
    filters.projectIds = ['5']
    filters.versionFilterApplied = true
    filters.versionIds = ['2026Q3_w3']
    dashboardApi.records.mockResolvedValue({
      records: [
        { id: 30, project_id: 5, version: '2026Q3_w3' },
        { id: 62, project_id: 5, version: '2026Q3_w3' }
      ],
      pagination: { total: 2 },
      meta: {}
    })

    await useDashboardData().loadDashboardData()

    expect(dashboardApi.records).toHaveBeenCalledWith(
      expect.objectContaining({
        project_ids: '5',
        version: '2026Q3_w3'
      }),
      expect.any(AbortSignal)
    )
    expect(dashboard.records.map(record => record.version)).toEqual([
      '2026Q3_w3',
      '2026Q3_w3'
    ])
    expect(dashboard.selectedRecords).toHaveLength(2)
    expect(dashboard.baselineRecord.version).toBe('2026Q3_w3')
  })
})
