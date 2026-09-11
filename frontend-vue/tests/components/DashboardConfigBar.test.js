import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DashboardConfigBar from '@/components/dashboard/DashboardConfigBar.vue'
import { dashboardApi } from '@/api/dashboard'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/dashboard', () => ({
  dashboardApi: {
    listConfigs: vi.fn(),
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    deleteConfig: vi.fn(),
    modules: vi.fn().mockResolvedValue({ modules: [], meta: {} }),
    versions: vi.fn().mockResolvedValue([]),
    records: vi.fn().mockResolvedValue({
      records: [],
      pagination: { page: 1, page_size: 200, total: 0, pages: 0 },
      meta: {}
    })
  }
}))

async function mountFor(user) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().user = user
  const wrapper = mount(DashboardConfigBar, {
    props: {
      modelValue: {
        orientation: 'vertical',
        activeView: 'charts'
      }
    },
    global: { plugins: [pinia] }
  })
  await wrapper.vm.bootstrap()
  await flushPromises()
  return wrapper
}

describe('DashboardConfigBar role behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    dashboardApi.listConfigs.mockResolvedValue([
      { id: 4, name: 'Shared presentation', is_default: true }
    ])
    dashboardApi.getConfig.mockResolvedValue({
      id: 4,
      name: 'Shared presentation',
      is_default: true,
      config: { activeView: 'combined', labelMode: 'version_tag' }
    })
    dashboardApi.deleteConfig.mockResolvedValue({ ok: true })
  })

  it('lets owner and viewer read and apply the same saved metadata', async () => {
    const owner = await mountFor({ id: 1, username: 'owner', is_owner: true })
    const ownerOptions = owner.findAll('option').map(option => option.text())
    const ownerPayload = owner.emitted('update:modelValue')[0][0]
    expect(ownerPayload.labelMode).toBe('version_tag')
    owner.unmount()

    const viewer = await mountFor({ id: 2, username: 'viewer', is_viewer: true })
    expect(viewer.findAll('option').map(option => option.text())).toEqual(ownerOptions)
    expect(viewer.emitted('update:modelValue')[0][0]).toEqual(ownerPayload)
    expect(viewer.text()).toContain('Shared presentation')
    viewer.unmount()
  })

  it('keeps configuration mutation controls owner-only', async () => {
    const owner = await mountFor({ id: 1, username: 'owner', is_owner: true })
    expect(owner.find('input[aria-label="Configuration name"]').exists()).toBe(true)
    expect(owner.text()).toContain('Save current')
    expect(owner.text()).toContain('Delete')
    owner.unmount()

    const viewer = await mountFor({ id: 2, username: 'viewer', is_viewer: true })
    expect(viewer.find('input[aria-label="Configuration name"]').exists()).toBe(false)
    expect(viewer.text()).not.toContain('Save current')
    expect(viewer.text()).not.toContain('Delete')
    expect(viewer.text()).toContain('Read-only dashboard')
    viewer.unmount()
  })

  it('hides Delete for unsaved selection and deletes the active saved config after confirm', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    dashboardApi.listConfigs
      .mockResolvedValueOnce([{ id: 4, name: 'Shared presentation', is_default: true }])
      .mockResolvedValueOnce([])

    const owner = await mountFor({ id: 1, username: 'owner', is_owner: true })
    expect(owner.text()).toContain('Delete')

    const select = owner.find('select[aria-label="Saved configuration"]')
    await select.setValue('')
    await flushPromises()
    expect(owner.text()).not.toContain('Delete')

    await select.setValue('4')
    await flushPromises()
    expect(owner.text()).toContain('Delete')

    const deleteButton = owner.findAll('button').find(button => button.text() === 'Delete')
    await deleteButton.trigger('click')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalled()
    expect(dashboardApi.deleteConfig).toHaveBeenCalledWith('4')
    expect(select.element.value).toBe('')
    confirmSpy.mockRestore()
    owner.unmount()
  })
})
