import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import AdminView from '@/views/AdminView.vue'
import ReviewHierarchyTree from '@/components/admin/ReviewHierarchyTree.vue'
import { adminApi } from '@/api/admin'

vi.mock('@/api/projects', () => ({
  projectsApi: { list: vi.fn().mockResolvedValue([]) }
}))

vi.mock('@/api/qor', () => ({
  qorApi: { getQorData: vi.fn().mockResolvedValue([]) }
}))

vi.mock('@/api/admin', () => ({
  adminApi: {
    getReviewHierarchyStatus: vi.fn(),
    updateReviewHierarchyModuleOwner: vi.fn(),
    getRecordOwners: vi.fn().mockResolvedValue([]),
    listHiddenProjects: vi.fn().mockResolvedValue([])
  }
}))

const hierarchyStatus = (canEdit = true, releaseOwner = 'release-owner') => ({
  config_path: 'D:/app/config/review_hierarchy.yaml',
  config_version: '2',
  config_checksum: 'abc123',
  validation: { valid: true, errors: [] },
  last_applied: {
    config_version: '1',
    applied_at: '2026-08-12T12:00:00Z',
    summary: { total_changes: 4 }
  },
  current_db_diff: { in_sync: false, total_changes: 2 },
  permissions: { can_edit_module_owner: canEdit },
  owner_options: canEdit
    ? [
        { id: 8, username: 'release-owner', display_name: 'Release Owner' },
        { id: 9, username: 'new-owner', display_name: 'New Owner' }
      ]
    : [],
  projects: [
    {
      name: 'projectA',
      status: 'active',
      owner: 'project-owner',
      effective_thresholds: {
        tns_setup: { medium_percent: 12, high_percent: 30 }
      },
      groups: [
        {
          name: 'frontend',
          owner: 'group-owner',
          modules: [{ name: 'cpu', release_owner: releaseOwner }]
        },
        {
          name: 'backend',
          owner: 'backend-owner',
          modules: [{ name: 'cache', release_owner: 'release-owner' }]
        }
      ]
    },
    {
      name: 'projectB',
      status: 'locked',
      owner: 'locked-project-owner',
      effective_thresholds: {},
      groups: [
        {
          name: 'locked-group',
          owner: 'locked-group-owner',
          modules: [{ name: 'locked-module', release_owner: 'release-owner' }]
        }
      ]
    }
  ]
})

async function mountHierarchy() {
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
        BatchReleaseDirDialog: true,
        ReleaseDirEditDialog: true
      }
    }
  })
  await flushPromises()
  await wrapper
    .findAll('.tab-btn')
    .find(button => button.text().includes('评审层级状态'))
    .trigger('click')
  await flushPromises()
  return wrapper
}

describe('Admin hierarchy status', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    adminApi.getRecordOwners.mockResolvedValue([])
    adminApi.getReviewHierarchyStatus.mockResolvedValue(hierarchyStatus())
  })

  it('renders diagnostics and the complete project/group/module tree', async () => {
    const wrapper = await mountHierarchy()

    expect(adminApi.getReviewHierarchyStatus).toHaveBeenCalledTimes(1)
    expect(wrapper.get('.hierarchy-console').text()).toContain('配置有效')
    expect(wrapper.get('.hierarchy-console').text()).toContain('abc123')
    expect(wrapper.get('.hierarchy-console').text()).toContain('2 项待同步')
    expect(wrapper.get('.project-node').text()).toContain('Project Owner · project-owner')
    expect(wrapper.get('.group-node').text()).toContain('Group Owner · group-owner')
    expect(wrapper.get('.module-node').text()).toContain('cpu')
    expect(wrapper.get('.module-node').text()).toContain('release-owner')
    expect(wrapper.get('.threshold-details').text()).toContain('medium 12% · high 30%')
  })

  it('collapses project and group branches independently', async () => {
    const wrapper = await mountHierarchy()
    const projectButton = wrapper.get('.project-toggle')
    expect(projectButton.attributes('aria-expanded')).toBe('true')

    await projectButton.trigger('click')
    expect(projectButton.attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('.project-children').isVisible()).toBe(false)

    await projectButton.trigger('click')
    const groups = wrapper.findAll('.group-node')
    await groups[0].get('.group-toggle').trigger('click')
    expect(groups[0].get('.group-toggle').attributes('aria-expanded')).toBe('false')
    expect(groups[0].get('.module-list').attributes('style')).toContain('display: none')
    expect(groups[1].get('.group-toggle').attributes('aria-expanded')).toBe('true')
    expect(groups[1].get('.module-list').attributes('style') || '').not.toContain('display: none')
  })

  it('filters by project and resets safely when the selection disappears', async () => {
    const status = hierarchyStatus()
    const wrapper = mount(ReviewHierarchyTree, { props: { status } })
    const selector = wrapper.get('#hierarchy-project-filter')

    expect(selector.findAll('option').map(option => option.text())).toEqual([
      '全部项目',
      'projectA',
      'projectB（已锁定）'
    ])
    await selector.setValue('projectB')
    expect(wrapper.findAll('.project-node')).toHaveLength(1)
    expect(wrapper.get('.project-node').text()).toContain('projectB')

    await wrapper.setProps({
      status: {
        ...status,
        config_checksum: 'refreshed-checksum',
        projects: status.projects.map(project => ({ ...project }))
      }
    })
    expect(wrapper.get('#hierarchy-project-filter').element.value).toBe('projectB')

    await wrapper.setProps({
      status: {
        ...status,
        projects: status.projects.filter(project => project.name !== 'projectB')
      }
    })
    await flushPromises()

    expect(wrapper.get('#hierarchy-project-filter').element.value).toBe('')
    expect(wrapper.findAll('.project-node')).toHaveLength(1)
    expect(wrapper.get('.project-node').text()).toContain('projectA')
  })

  it('edits and saves a release owner then refreshes the rendered state', async () => {
    const updatedStatus = hierarchyStatus(true, 'new-owner')
    adminApi.updateReviewHierarchyModuleOwner.mockResolvedValue({
      ok: true,
      updated: { release_owner: 'new-owner' },
      status: updatedStatus
    })
    const wrapper = await mountHierarchy()

    await wrapper.get('.owner-edit').trigger('click')
    await wrapper.get('.owner-editor select').setValue('9')
    await wrapper.get('.owner-editor').trigger('submit')
    await flushPromises()

    expect(adminApi.updateReviewHierarchyModuleOwner).toHaveBeenCalledWith({
      project: 'projectA',
      group: 'frontend',
      module: 'cpu',
      owner_id: 9,
      config_checksum: 'abc123'
    })
    expect(wrapper.get('.module-node').text()).toContain('new-owner')
    expect(wrapper.get('.row-message.is-success').text()).toContain('已更新')
  })

  it('keeps owner accounts read-only', async () => {
    adminApi.getReviewHierarchyStatus.mockResolvedValue(hierarchyStatus(false))
    const wrapper = await mountHierarchy()

    expect(wrapper.get('.read-only-note').text()).toContain('只有管理员')
    expect(wrapper.find('.owner-edit').exists()).toBe(false)
    expect(wrapper.get('.read-only-tag').text()).toBe('只读')
  })

  it('shows a row-local API error and keeps the editor open', async () => {
    adminApi.updateReviewHierarchyModuleOwner.mockRejectedValue({
      response: { data: { error: 'YAML 目录只读' } }
    })
    const wrapper = await mountHierarchy()

    await wrapper.get('.owner-edit').trigger('click')
    await wrapper.get('.owner-editor select').setValue('9')
    await wrapper.get('.owner-editor').trigger('submit')
    await flushPromises()

    expect(wrapper.get('.row-message.is-error').text()).toContain('YAML 目录只读')
    expect(wrapper.find('.owner-editor').exists()).toBe(true)
  })
})
