import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import AdminView from '@/views/AdminView.vue'
import { projectsApi } from '@/api/projects'

const projects = [
  {
    id: 1,
    name: 'Alpha',
    modules: [
      { id: 1, name: 'core' },
      { id: 2, name: 'io' }
    ]
  },
  {
    id: 2,
    name: 'Beta',
    modules: [{ id: 1, name: 'core' }]
  }
]

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
    listHiddenProjects: vi.fn().mockResolvedValue([]),
    restoreProject: vi.fn(),
    hardDeleteProject: vi.fn(),
    lockProject: vi.fn(),
    unlockProject: vi.fn(),
    createModule: vi.fn(),
    deleteModule: vi.fn(),
    listUsers: vi.fn().mockResolvedValue([]),
    getRecordOwners: vi.fn().mockResolvedValue([]),
    resetUserPassword: vi.fn()
  }
}))

async function mountModulesTab() {
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
        SnapshotBackupManager: true
      }
    }
  })
  await flushPromises()
  await wrapper
    .findAll('.tab-btn')
    .find(button => button.text().includes('模块管理'))
    .trigger('click')
  await flushPromises()
  return wrapper
}

const buttonByText = (wrapper, text) =>
  wrapper.findAll('button').find(button => button.text().trim() === text)
const renderedModuleRows = wrapper => wrapper.findAll('.card-body table tbody tr')
const visibleModuleCount = wrapper =>
  Number(wrapper.find('.module-list-header small').text().split('/')[0].trim())

describe('Admin module #pick filter', () => {
  beforeEach(() => {
    projectsApi.list.mockResolvedValue(projects)
  })

  it('keeps draft changes isolated until Apply and filters by project', async () => {
    const wrapper = await mountModulesTab()
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)

    await wrapper.get('.module-picker-trigger').trigger('click')
    const betaProject = wrapper
      .findAll('.module-picker fieldset:first-child label')
      .find(label => label.text().includes('Beta'))
    await betaProject.get('input').setValue(false)

    expect(wrapper.find('.module-picker fieldset:nth-child(2)').text()).not.toContain('Beta')
    await buttonByText(wrapper, 'Cancel').trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)

    await wrapper.get('.module-picker-trigger').trigger('click')
    const betaAgain = wrapper
      .findAll('.module-picker fieldset:first-child label')
      .find(label => label.text().includes('Beta'))
    await betaAgain.get('input').setValue(false)
    await buttonByText(wrapper, 'Apply').trigger('click')

    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.find('.module-list-header').text()).toContain('2 / 3 visible')
    expect(wrapper.find('.card-body table').text()).not.toContain('Beta')
  })

  it('keeps colliding local ids and duplicate names independently selectable through sort', async () => {
    const wrapper = await mountModulesTab()
    await wrapper.get('.module-picker-trigger').trigger('click')

    const duplicateLabels = wrapper
      .findAll('.module-picker fieldset:nth-child(2) label')
      .filter(label => label.text().includes('core'))
    expect(duplicateLabels).toHaveLength(2)
    expect(duplicateLabels[0].text()).toContain('Alpha')
    expect(duplicateLabels[1].text()).toContain('Beta')
    expect(duplicateLabels.map(label => label.get('input').attributes('value'))).toEqual([
      '1:1',
      '2:1'
    ])

    await duplicateLabels[0].get('input').setValue(false)
    await buttonByText(wrapper, 'Apply').trigger('click')

    let rows = renderedModuleRows(wrapper)
    expect(rows).toHaveLength(2)
    expect(visibleModuleCount(wrapper)).toBe(rows.length)
    expect(rows.some(row => row.text().includes('core') && row.text().includes('Beta'))).toBe(true)
    expect(rows.some(row => row.text().includes('core') && row.text().includes('Alpha'))).toBe(
      false
    )

    await wrapper
      .findAll('.card-body table th')
      .find(header => header.text().includes('名称'))
      .trigger('click')
    rows = renderedModuleRows(wrapper)
    expect(rows).toHaveLength(2)
    expect(visibleModuleCount(wrapper)).toBe(rows.length)
    expect(rows.some(row => row.text().includes('core') && row.text().includes('Beta'))).toBe(true)
  })

  it('shows a filtered empty state and Reset restores all modules', async () => {
    const wrapper = await mountModulesTab()
    await wrapper.get('.module-picker-trigger').trigger('click')

    const moduleActions = wrapper.findAll('.module-picker-actions')[1]
    await moduleActions
      .findAll('button')
      .find(button => button.text() === 'None')
      .trigger('click')
    await buttonByText(wrapper, 'Apply').trigger('click')

    expect(wrapper.find('.module-filter-empty').text()).toContain('没有模块匹配')
    expect(wrapper.find('.module-list-header').text()).toContain('0 / 3 visible')

    await wrapper.get('.module-filter-empty button').trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)
    expect(wrapper.find('.module-list-header').text()).toContain('3 total')
  })
})
