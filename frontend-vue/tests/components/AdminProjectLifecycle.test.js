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
