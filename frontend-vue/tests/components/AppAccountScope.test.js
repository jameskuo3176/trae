import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import App from '@/App.vue'
import { useAuthStore } from '@/stores/auth'
import { useDashboardStore } from '@/stores/dashboard'
import { useDashboardConfigsStore } from '@/stores/dashboardConfigs'
import { useFiltersStore } from '@/stores/filters'

vi.mock('@/composables/useTheme', () => ({
  useTheme: () => ({ initTheme: vi.fn() })
}))

describe('account-scoped dashboard state', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('clears owner filters, records, and config selection when a viewer logs in', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = { id: 1, username: 'owner', is_owner: true }
    const filters = useFiltersStore()
    filters.projectIds = ['5']
    filters.moduleIds = ['77']
    filters.dirPrefix = 'admin'
    const dashboard = useDashboardStore()
    dashboard.setRecords([{ id: 'private-owner-record', project_id: 5 }])
    const configs = useDashboardConfigsStore()
    configs.configs = [{ id: 9, name: 'Owner default' }]
    configs.activeId = '9'

    const wrapper = mount(App, {
      global: {
        plugins: [pinia],
        stubs: {
          AppNavbar: true,
          ThemeModal: true,
          ChangePasswordModal: true,
          RouterView: true
        }
      }
    })

    auth.user = { id: 2, username: 'viewer', is_viewer: true }
    await flushPromises()

    expect(filters.projectIds).toEqual([])
    expect(filters.moduleIds).toEqual([])
    expect(filters.dirPrefix).toBe('')
    expect(dashboard.records).toEqual([])
    expect(configs.activeId).toBe('')
    expect(configs.configs).toEqual([])
    wrapper.unmount()
  })
})
