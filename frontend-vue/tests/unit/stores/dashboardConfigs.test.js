import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { dashboardApi } from '@/api/dashboard'
import { useDashboardConfigsStore } from '@/stores/dashboardConfigs'

vi.mock('@/api/dashboard', () => ({
  dashboardApi: {
    listConfigs: vi.fn(),
    getConfig: vi.fn(),
    saveConfig: vi.fn()
  }
}))

describe('dashboard configuration store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('loads the default summary then fetches its detail', async () => {
    dashboardApi.listConfigs.mockResolvedValue([{ id: 4, name: 'Default', is_default: true }])
    dashboardApi.getConfig.mockResolvedValue({
      id: 4,
      name: 'Default',
      is_default: true,
      config: { activeView: 'combined' }
    })
    const store = useDashboardConfigsStore()
    await store.load()
    expect(store.activeId).toBe('4')
    const detail = await store.loadConfig()
    expect(dashboardApi.getConfig).toHaveBeenCalledWith('4')
    expect(detail.config.activeView).toBe('combined')
  })

  it('saves through the server before refreshing summaries', async () => {
    dashboardApi.saveConfig.mockResolvedValue({ id: 5 })
    dashboardApi.listConfigs.mockResolvedValue([{ id: 5, name: 'Saved', is_default: false }])
    const store = useDashboardConfigsStore()
    await store.save('Saved', { height: 640 }, false)
    expect(dashboardApi.saveConfig).toHaveBeenCalledWith({
      id: undefined,
      name: 'Saved',
      config: { height: 640 },
      is_default: false
    })
  })
})
