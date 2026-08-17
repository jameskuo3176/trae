import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DashboardView from '@/views/DashboardView.vue'
import { dashboardApi } from '@/api/dashboard'
import { projectsApi } from '@/api/projects'
import { useDashboardStore } from '@/stores/dashboard'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardConfigsStore } from '@/stores/dashboardConfigs'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/projects', () => ({
  projectsApi: { list: vi.fn() }
}))

vi.mock('@/api/dashboard', () => ({
  dashboardApi: {
    modules: vi.fn(),
    versions: vi.fn(),
    records: vi.fn(),
    listConfigs: vi.fn(),
    getConfig: vi.fn(),
    saveConfig: vi.fn()
  }
}))

const visualStubs = {
  FilterBar: true,
  DashboardStats: true,
  ChartSettingsPanel: true,
  LoadingSpinner: true,
  AreaChart: true,
  TimingChart: true,
  PowerChart: true,
  CellChart: true,
  PieChart: true,
  PhysicalMetricChart: true,
  ViolationPanel: true,
  DcReportPanel: true,
  CombinedTableView: true,
  TransposedTableView: true,
  DirAggregateView: true,
  DirModulesView: true,
  RunNotesPanel: true
}

describe('viewer dashboard startup', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
    projectsApi.list.mockResolvedValue([{ id: 5, name: 'Published project', status: 'active' }])
    dashboardApi.modules.mockResolvedValue({
      modules: [{ id: 77, name: 'CPU', project_ids: [5] }],
      meta: {}
    })
    dashboardApi.versions.mockResolvedValue(['2026Q3_w3'])
    dashboardApi.records.mockResolvedValue({
      records: [
        {
          id: 3,
          project_id: 5,
          module_id: 77,
          version: '2026Q3_w3',
          full_dir: '/workspace/regr_20260817/main/cpu',
          is_released: true
        },
        {
          id: 4,
          project_id: 5,
          module_id: 77,
          version: '2026Q3_w3',
          full_dir: '/workspace/regr_20260817/main/cpu-draft',
          is_released: false
        }
      ],
      pagination: { page: 1, page_size: 200, total: 2, pages: 1 },
      meta: {}
    })
    dashboardApi.listConfigs.mockResolvedValue([
      { id: 9, name: 'Deleted default', is_default: true }
    ])
    dashboardApi.getConfig.mockRejectedValue(
      Object.assign(new Error('Request failed with status code 404'), { status: 404 })
    )
  })

  it('renders readable QoR data when the optional configuration returns 404', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(DashboardView, {
      global: {
        plugins: [pinia],
        stubs: visualStubs
      }
    })

    await flushPromises()
    await flushPromises()

    const dashboard = useDashboardStore()
    const filters = useFiltersStore()
    const configs = useDashboardConfigsStore()
    expect(filters.projects).toHaveLength(1)
    expect(filters.modules).toHaveLength(1)
    expect(filters.versions).toEqual(['2026Q3_w3'])
    expect(dashboard.records).toHaveLength(2)
    expect(dashboard.records[0].is_released).toBe(true)
    expect(dashboard.records[1].is_released).toBe(false)
    expect(dashboard.loadError).toBeNull()
    expect(configs.error).toContain('using dashboard defaults')
    expect(wrapper.text()).not.toContain('No records match the current scope.')
    expect(wrapper.find('section#section-chart-area').exists()).toBe(true)
    expect(wrapper.find('section#section-chart-timing').exists()).toBe(true)
    expect(wrapper.find('section#section-chart-power').exists()).toBe(true)
    expect(wrapper.find('section#chart-area').exists()).toBe(false)
    expect(wrapper.find('section#chart-timing').exists()).toBe(false)
    expect(wrapper.find('section#chart-power').exists()).toBe(false)

    wrapper.unmount()
  })

  it('initializes identical read data and filters for admin, owner, and viewer', async () => {
    const snapshots = {}
    for (const role of ['admin', 'owner', 'viewer']) {
      const pinia = createPinia()
      setActivePinia(pinia)
      useAuthStore().user = {
        id: role === 'admin' ? 1 : role === 'owner' ? 2 : 3,
        username: role,
        [`is_${role}`]: true
      }
      const wrapper = mount(DashboardView, {
        global: {
          plugins: [pinia],
          stubs: visualStubs
        }
      })
      await flushPromises()
      await flushPromises()

      const dashboard = useDashboardStore()
      const filters = useFiltersStore()
      snapshots[role] = {
        projects: filters.projects,
        modules: filters.modules,
        versions: filters.versions,
        records: dashboard.records.map(({ __selectionKey, ...record }) => record),
        selected: dashboard.selectedRecords.map(record => record.id)
      }
      wrapper.unmount()
    }

    expect(snapshots.admin).toEqual(snapshots.owner)
    expect(snapshots.owner).toEqual(snapshots.viewer)
    expect(snapshots.viewer.records.some(record => record.is_released === false)).toBe(true)
  })
})
