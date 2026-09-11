import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { dashboardApi } from '@/api/dashboard'
import { useDashboardConfigsStore } from '@/stores/dashboardConfigs'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/dashboard', () => ({
  dashboardApi: {
    listConfigs: vi.fn(),
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    deleteConfig: vi.fn()
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

  it('deletes through the server and switches active selection to unsaved', async () => {
    dashboardApi.listConfigs
      .mockResolvedValueOnce([
        { id: 4, name: 'Keep', is_default: false },
        { id: 5, name: 'Remove me', is_default: true }
      ])
      .mockResolvedValueOnce([{ id: 4, name: 'Keep', is_default: false }])
    dashboardApi.deleteConfig.mockResolvedValue({ ok: true })
    const store = useDashboardConfigsStore()
    await store.load()
    store.activeId = '5'

    const ok = await store.remove('5')

    expect(ok).toBe(true)
    expect(dashboardApi.deleteConfig).toHaveBeenCalledWith('5')
    expect(store.configs).toEqual([{ id: 4, name: 'Keep', is_default: false }])
    expect(store.activeId).toBe('')
  })

  it('falls back to local delete when the server endpoint is unavailable', async () => {
    localStorage.setItem(
      'qor_dashboard_configs_v2',
      JSON.stringify([
        { id: 'local-1', name: 'A', is_default: true, config: {} },
        { id: 'local-2', name: 'B', is_default: false, config: {} }
      ])
    )
    dashboardApi.deleteConfig.mockRejectedValue(new Error('offline'))
    const store = useDashboardConfigsStore()
    store.configs = [
      { id: 'local-1', name: 'A', is_default: true, config: {} },
      { id: 'local-2', name: 'B', is_default: false, config: {} }
    ]
    store.activeId = 'local-1'

    await store.remove('local-1')

    expect(store.activeId).toBe('')
    expect(store.configs).toEqual([{ id: 'local-2', name: 'B', is_default: false, config: {} }])
    expect(JSON.parse(localStorage.getItem('qor_dashboard_configs_v2'))).toEqual([
      { id: 'local-2', name: 'B', is_default: false, config: {} }
    ])
    expect(store.error).toContain('Deleted locally')
  })

  it('falls back to defaults when an optional saved configuration is missing', async () => {
    dashboardApi.listConfigs.mockResolvedValue([{ id: 9, name: 'Removed', is_default: true }])
    dashboardApi.getConfig.mockRejectedValue(
      Object.assign(new Error('Request failed with status code 404'), { status: 404 })
    )
    const store = useDashboardConfigsStore()

    await store.load()
    const detail = await store.loadConfig()

    expect(detail).toBeNull()
    expect(store.activeId).toBe('')
    expect(store.configs).toEqual([])
    expect(store.error).toBe('Saved configuration was not found; using dashboard defaults.')
  })

  it('does not request a previous account configuration after the list changes', async () => {
    dashboardApi.listConfigs.mockResolvedValue([])
    const store = useDashboardConfigsStore()
    store.activeId = '9'

    await store.load()

    expect(store.activeId).toBe('')
    expect(dashboardApi.getConfig).not.toHaveBeenCalled()
  })

  it('rejects viewer configuration saves without server or local fallback', async () => {
    useAuthStore().user = { id: 2, username: 'viewer', is_viewer: true }
    const store = useDashboardConfigsStore()

    const result = await store.save('Forbidden', { activeView: 'combined' })

    expect(result).toBeNull()
    expect(store.error).toContain('cannot save')
    expect(dashboardApi.saveConfig).not.toHaveBeenCalled()
    expect(localStorage.setItem).not.toHaveBeenCalled()
  })

  it('rejects viewer configuration deletes', async () => {
    useAuthStore().user = { id: 2, username: 'viewer', is_viewer: true }
    const store = useDashboardConfigsStore()
    store.activeId = '4'

    const ok = await store.remove('4')

    expect(ok).toBe(false)
    expect(store.error).toContain('cannot delete')
    expect(dashboardApi.deleteConfig).not.toHaveBeenCalled()
  })
})
