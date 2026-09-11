import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import AdminView from '@/views/AdminView.vue'
import { adminApi } from '@/api/admin'
import { projectsApi } from '@/api/projects'

vi.mock('@/api/projects', () => ({
  projectsApi: { list: vi.fn() }
}))

vi.mock('@/api/qor', () => ({
  qorApi: { getQorData: vi.fn().mockResolvedValue([]) }
}))

vi.mock('@/api/admin', () => ({
  adminApi: {
    createProject: vi.fn(),
    deleteProject: vi.fn(),
    listHiddenProjects: vi.fn(),
    restoreProject: vi.fn(),
    hardDeleteProject: vi.fn(),
    lockProject: vi.fn(),
    unlockProject: vi.fn(),
    listUsers: vi.fn().mockResolvedValue([]),
    getRecordOwners: vi.fn().mockResolvedValue([])
  }
}))

const activeProjects = [
  {
    id: 1,
    name: 'Alpha',
    description: 'active',
    module_count: 2,
    status: 'active',
    is_writable: true,
    modules: []
  },
  {
    id: 2,
    name: 'Beta',
    description: 'locked',
    module_count: 1,
    status: 'locked',
    is_writable: false,
    lock_reason: 'freeze',
    modules: []
  }
]

async function mountProjectsTab() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/admin', component: AdminView }]
  })
  await router.push('/admin')
  await router.isReady()
  const wrapper = mount(AdminView, {
    global: {
      plugins: [router],
      stubs: {
        LoadingSpinner: true,
        DataUploadModal: true,
        SnapshotBackupManager: true,
        TableFontSizeControl: true
      }
    }
  })
  await flushPromises()
  await wrapper
    .findAll('button')
    .find(button => button.text() === '项目管理')
    .trigger('click')
  await flushPromises()
  return wrapper
}

function findRowAction(wrapper, rowLabel, actionLabel) {
  const row = wrapper.findAll('tr').find(item => item.text().includes(rowLabel))
  expect(row).toBeTruthy()
  return row.findAll('button').find(button => button.text() === actionLabel)
}

async function mountAdminWithQuery(query = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/admin', component: AdminView }]
  })
  await router.push({ path: '/admin', query })
  await router.isReady()
  const wrapper = mount(AdminView, {
    global: {
      plugins: [router],
      stubs: {
        LoadingSpinner: true,
        DataUploadModal: true,
        SnapshotBackupManager: true,
        TableFontSizeControl: true
      }
    }
  })
  await flushPromises()
  return { wrapper, router }
}

describe('Admin project restore and lock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    projectsApi.list.mockResolvedValue(activeProjects)
    adminApi.listHiddenProjects.mockResolvedValue([
      {
        id: 9,
        name: 'HiddenProj',
        module_count: 3,
        record_count: 12,
        hidden_by_name: 'admin',
        hidden_at: '2026-08-14T08:00:00Z'
      }
    ])
    adminApi.restoreProject.mockResolvedValue({ ok: true })
    adminApi.lockProject.mockResolvedValue({ id: 1, status: 'locked' })
    adminApi.unlockProject.mockResolvedValue({ id: 2, status: 'active' })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(window, 'prompt').mockReturnValue('freeze for review')
  })

  it('restores hidden projects and can lock/unlock visible ones', async () => {
    const wrapper = await mountProjectsTab()

    expect(adminApi.listHiddenProjects).toHaveBeenCalled()
    expect(wrapper.text()).toContain('HiddenProj')
    expect(wrapper.text()).toContain('锁定')
    expect(wrapper.text()).toContain('禁上传，可查看历史数据')

    await wrapper
      .findAll('button')
      .find(button => button.text() === '恢复')
      .trigger('click')
    await flushPromises()
    expect(adminApi.restoreProject).toHaveBeenCalledWith(9)

    await wrapper
      .findAll('button')
      .find(button => button.text() === '锁定')
      .trigger('click')
    await flushPromises()
    expect(adminApi.lockProject).toHaveBeenCalledWith(1, 'freeze for review')

    await wrapper
      .findAll('button')
      .find(button => button.text() === '解锁')
      .trigger('click')
    await flushPromises()
    expect(adminApi.unlockProject).toHaveBeenCalledWith(2)
  })
})

describe('Admin project delete success handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    projectsApi.list.mockResolvedValue(activeProjects)
    adminApi.listHiddenProjects.mockResolvedValue([])
    adminApi.deleteProject.mockResolvedValue({ ok: true, message: '项目 "Alpha" 已隐藏' })
    adminApi.hardDeleteProject.mockResolvedValue({
      ok: true,
      message: '项目 "HiddenProj" 已彻底删除 (不可恢复)'
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('hides a project once, refreshes once, and shows backend success text', async () => {
    projectsApi.list
      .mockResolvedValueOnce(activeProjects)
      .mockResolvedValueOnce(activeProjects)
      .mockResolvedValueOnce(activeProjects)
      .mockResolvedValueOnce([activeProjects[1]])

    const { wrapper } = await mountAdminWithQuery()
    await wrapper
      .findAll('button')
      .find(button => button.text() === '项目管理')
      .trigger('click')
    await flushPromises()

    const listCallsBeforeDelete = projectsApi.list.mock.calls.length
    await findRowAction(wrapper, 'Alpha', '隐藏').trigger('click')
    await flushPromises()

    expect(adminApi.deleteProject).toHaveBeenCalledTimes(1)
    expect(adminApi.deleteProject).toHaveBeenCalledWith(1)
    expect(projectsApi.list.mock.calls.length - listCallsBeforeDelete).toBe(1)
    expect(wrapper.text()).toContain('项目 "Alpha" 已隐藏')
    expect(wrapper.find('.error-text').exists()).toBe(false)
    expect(wrapper.text()).toContain('项目列表 (1)')
    expect(wrapper.text()).not.toMatch(/1Alphaactive/)
  })

  it('does not refetch records when hiding on the projects tab with stale selection', async () => {
    const { qorApi } = await import('@/api/qor')
    const { wrapper } = await mountAdminWithQuery({ project_id: '1' })
    await wrapper
      .findAll('button')
      .find(button => button.text() === '项目管理')
      .trigger('click')
    await flushPromises()

    const qorCallsBeforeDelete = qorApi.getQorData.mock.calls.length
    await findRowAction(wrapper, 'Alpha', '隐藏').trigger('click')
    await flushPromises()

    expect(adminApi.deleteProject).toHaveBeenCalledTimes(1)
    expect(qorApi.getQorData.mock.calls.length).toBe(qorCallsBeforeDelete)
    expect(wrapper.find('.error-text').exists()).toBe(false)
  })

  it('shows success when hide succeeds even if project refresh fails', async () => {
    projectsApi.list
      .mockResolvedValueOnce(activeProjects)
      .mockResolvedValueOnce(activeProjects)
      .mockResolvedValueOnce(activeProjects)
      .mockRejectedValueOnce(new Error('network down'))

    const { wrapper } = await mountAdminWithQuery()
    await wrapper
      .findAll('button')
      .find(button => button.text() === '项目管理')
      .trigger('click')
    await flushPromises()

    await findRowAction(wrapper, 'Alpha', '隐藏').trigger('click')
    await flushPromises()

    expect(adminApi.deleteProject).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('项目 "Alpha" 已隐藏')
    expect(wrapper.find('.error-text').exists()).toBe(false)
  })

  it('hard deletes once, refreshes hidden list once, and shows success', async () => {
    adminApi.listHiddenProjects
      .mockResolvedValueOnce([
        {
          id: 9,
          name: 'HiddenProj',
          module_count: 3,
          record_count: 12,
          hidden_by_name: 'admin',
          hidden_at: '2026-08-14T08:00:00Z'
        }
      ])
      .mockResolvedValueOnce([])

    const { wrapper } = await mountAdminWithQuery()
    await wrapper
      .findAll('button')
      .find(button => button.text() === '项目管理')
      .trigger('click')
    await flushPromises()

    const hiddenCallsBeforeDelete = adminApi.listHiddenProjects.mock.calls.length
    await wrapper
      .findAll('button')
      .find(button => button.text() === '彻底删除')
      .trigger('click')
    await flushPromises()

    expect(adminApi.hardDeleteProject).toHaveBeenCalledTimes(1)
    expect(adminApi.hardDeleteProject).toHaveBeenCalledWith(9)
    expect(adminApi.listHiddenProjects.mock.calls.length - hiddenCallsBeforeDelete).toBe(1)
    expect(wrapper.text()).toContain('项目 "HiddenProj" 已彻底删除 (不可恢复)')
    expect(wrapper.find('.error-text').exists()).toBe(false)
    expect(wrapper.text()).toContain('无已隐藏项目')
  })
})
