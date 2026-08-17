import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import AdminView from '@/views/AdminView.vue'
import { adminApi } from '@/api/admin'
import { projectsApi } from '@/api/projects'
import { qorApi } from '@/api/qor'

vi.mock('@/api/projects', () => ({
  projectsApi: { list: vi.fn() }
}))
vi.mock('@/api/qor', () => ({
  qorApi: { getQorData: vi.fn() }
}))
vi.mock('@/api/admin', () => ({
  adminApi: {
    updateReleaseDir: vi.fn(),
    batchRelease: vi.fn(),
    batchUpdateReleaseDir: vi.fn(),
    deleteRecord: vi.fn(),
    toggleRelease: vi.fn(),
    listUsers: vi.fn().mockResolvedValue([]),
    getRecordOwners: vi.fn().mockResolvedValue([]),
    listHiddenProjects: vi.fn().mockResolvedValue([])
  }
}))

const projects = [
  { id: 10, name: 'Alpha', modules: [{ id: 1, name: 'core' }] },
  { id: 20, name: 'Beta', modules: [{ id: 1, name: 'core' }] }
]
const records = [
  {
    id: 1,
    project_id: 10,
    project_name: 'Alpha',
    module_id: 1,
    module_name: 'core',
    version: 'a',
    release_dir: '/alpha/old',
    release_dir_effective: '/alpha/old',
    full_dir: '/alpha/full',
    uploader_display_name: 'Alpha Uploader',
    can_manage: true
  },
  {
    id: 1,
    project_id: 20,
    project_name: 'Beta',
    module_id: 1,
    module_name: 'core',
    version: 'b',
    release_dir: '/beta/old',
    release_dir_effective: '/beta/old',
    full_dir: '/beta/full',
    uploader_username: 'beta-uploader',
    can_manage: true
  }
]

async function mountRecords() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/admin', component: AdminView },
      { path: '/record/:id', name: 'RecordDetail', component: { template: '<div />' } }
    ]
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
  return wrapper
}

describe('Admin release_dir persistence flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    projectsApi.list.mockResolvedValue(projects)
    qorApi.getQorData.mockResolvedValue(records)
    adminApi.updateReleaseDir.mockResolvedValue({ ok: true })
    adminApi.batchRelease.mockResolvedValue({ updated: 1 })
    adminApi.batchUpdateReleaseDir.mockResolvedValue({ updated: 2, skipped: 0 })
    adminApi.deleteRecord.mockResolvedValue({ ok: true })
    vi.spyOn(window, 'prompt').mockReturnValue('/beta/new')
    vi.spyOn(window, 'alert').mockImplementation(() => { })
  })

  it('opens the application dialog and updates the exact project record', async () => {
    qorApi.getQorData
      .mockResolvedValueOnce(records)
      .mockResolvedValueOnce([
        records[0],
        { ...records[1], release_dir: '/beta/new', release_dir_effective: '/beta/new' }
      ])
    const wrapper = await mountRecords()
    const betaRow = wrapper.findAll('tbody tr').find(row => row.text().includes('Beta'))

    await betaRow.get('button[title^="修改发布目录"]').trigger('click')
    await flushPromises()

    const dialog = wrapper.get('[role="dialog"][aria-labelledby="release-dir-edit-title"]')
    expect(window.prompt).not.toHaveBeenCalled()
    expect(dialog.text()).toContain('Beta / core / b')
    expect(dialog.text()).toContain('/beta/old')
    expect(dialog.text()).toContain('/beta/full')

    const input = dialog.get('#release-dir-edit-input')
    expect(input.element.value).toBe('/beta/old')
    expect(dialog.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await input.setValue('/beta/new')
    expect(dialog.text()).toContain('EXPLICIT')
    expect(dialog.text()).toContain('/beta/new')
    await dialog.trigger('submit')
    await flushPromises()

    expect(adminApi.updateReleaseDir).toHaveBeenCalledWith(1, 20, '/beta/new')
    expect(qorApi.getQorData).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('/beta/new')
    expect(wrapper.text()).toContain('/alpha/old')
    expect(wrapper.find('[role="dialog"][aria-labelledby="release-dir-edit-title"]').exists()).toBe(
      false
    )
  })

  it('keeps single-record API errors inside the edit dialog', async () => {
    adminApi.updateReleaseDir.mockRejectedValue(new Error('无权限'))
    const wrapper = await mountRecords()
    const betaRow = wrapper.findAll('tbody tr').find(row => row.text().includes('Beta'))

    await betaRow.get('button[title^="修改发布目录"]').trigger('click')
    const dialog = wrapper.get('[role="dialog"][aria-labelledby="release-dir-edit-title"]')
    await dialog.get('#release-dir-edit-input').setValue('/beta/denied')
    await dialog.trigger('submit')
    await flushPromises()

    expect(dialog.get('[role="alert"]').text()).toBe('无权限')
    expect(wrapper.find('[role="dialog"][aria-labelledby="release-dir-edit-title"]').exists()).toBe(
      true
    )
    expect(qorApi.getQorData).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('/beta/old')
  })

  it('normalizes unchanged values, validates length, and submits an empty fallback', async () => {
    const wrapper = await mountRecords()
    const betaRow = wrapper.findAll('tbody tr').find(row => row.text().includes('Beta'))
    await betaRow.get('button[title^="修改发布目录"]').trigger('click')

    const dialog = wrapper.get('[role="dialog"][aria-labelledby="release-dir-edit-title"]')
    const input = dialog.get('#release-dir-edit-input')
    const submit = dialog.get('button[type="submit"]')

    await input.setValue('  /beta/old  ')
    expect(submit.attributes('disabled')).toBeDefined()

    await input.setValue('x'.repeat(501))
    expect(dialog.text()).toContain('501 / 500')
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(submit.attributes('disabled')).toBeDefined()

    await input.setValue('')
    expect(dialog.text()).toContain('FALLBACK')
    expect(dialog.text()).toContain('/beta/full')
    expect(submit.attributes('disabled')).toBeUndefined()
    await dialog.trigger('submit')
    await flushPromises()

    expect(adminApi.updateReleaseDir).toHaveBeenCalledWith(1, 20, '')
  })

  it('renders uploader enrichment and batches composite project identities', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = await mountRecords()
    const rows = wrapper.findAll('tbody tr')
    await rows[0].get('input[type=checkbox]').setValue(true)
    await rows[1].get('input[type=checkbox]').setValue(true)
    await wrapper
      .findAll('button')
      .find(button => button.text() === '批量发布')
      .trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Alpha Uploader')
    expect(wrapper.text()).toContain('beta-uploader')
    expect(adminApi.batchRelease).toHaveBeenCalledWith({
      items: [
        { project_id: 10, record_id: 1 },
        { project_id: 20, record_id: 1 }
      ],
      released: true
    })
  })

  it('edits one row independently and submits only that changed record', async () => {
    const wrapper = await mountRecords()
    const rows = wrapper.findAll('tbody tr')
    await rows[0].get('input[type=checkbox]').setValue(true)
    await rows[1].get('input[type=checkbox]').setValue(true)

    await wrapper
      .findAll('button')
      .find(button => button.text() === '批量更新 release_dir')
      .trigger('click')
    await flushPromises()

    const dialog = wrapper.get('[role="dialog"][aria-labelledby="batch-release-dir-title"]')
    expect(dialog.text()).toContain('2 条记录')
    expect(dialog.text()).toContain('2 个项目')
    expect(dialog.text()).toContain('Alpha')
    expect(dialog.text()).toContain('Beta')
    expect(dialog.text()).toContain('/alpha/old')
    expect(dialog.text()).toContain('/beta/old')
    expect(adminApi.batchUpdateReleaseDir).not.toHaveBeenCalled()

    const rowInputs = dialog.findAll('.row-path-input')
    expect(rowInputs.map(input => input.element.value)).toEqual(['/alpha/old', '/beta/old'])
    expect(dialog.get('button[type="submit"]').text()).toBe('更新 0 条记录')
    expect(dialog.get('button[type="submit"]').attributes('disabled')).toBeDefined()

    await rowInputs[0].setValue('/alpha/new')
    expect(rowInputs[1].element.value).toBe('/beta/old')
    expect(dialog.text()).toContain('已修改 1 条')
    expect(dialog.get('button[type="submit"]').text()).toBe('更新 1 条记录')
    await dialog.trigger('submit')
    await flushPromises()

    expect(adminApi.batchUpdateReleaseDir).toHaveBeenCalledWith({
      items: [
        { project_id: 10, record_id: 1, release_dir: '/alpha/new' }
      ]
    })
    expect(wrapper.find('[role="dialog"][aria-labelledby="batch-release-dir-title"]').exists()).toBe(
      false
    )
  })

  it('submits different release_dir values for two independently edited rows', async () => {
    const wrapper = await mountRecords()
    const rows = wrapper.findAll('tbody tr')
    await rows[0].get('input[type=checkbox]').setValue(true)
    await rows[1].get('input[type=checkbox]').setValue(true)
    await wrapper
      .findAll('button')
      .find(button => button.text() === '批量更新 release_dir')
      .trigger('click')

    const dialog = wrapper.get('[role="dialog"][aria-labelledby="batch-release-dir-title"]')
    const rowInputs = dialog.findAll('.row-path-input')
    await rowInputs[0].setValue('/alpha/new')
    await rowInputs[1].setValue('/beta/new')
    await dialog.trigger('submit')
    await flushPromises()

    expect(adminApi.batchUpdateReleaseDir).toHaveBeenCalledWith({
      items: [
        { project_id: 10, record_id: 1, release_dir: '/alpha/new' },
        { project_id: 20, record_id: 1, release_dir: '/beta/new' }
      ]
    })
  })

  it('treats trimmed differences as changes while preserving the user value for submission', async () => {
    const wrapper = await mountRecords()
    const alphaRow = wrapper.findAll('tbody tr').find(row => row.text().includes('Alpha'))
    await alphaRow.get('input[type=checkbox]').setValue(true)
    await wrapper
      .findAll('button')
      .find(button => button.text() === '批量更新 release_dir')
      .trigger('click')

    const dialog = wrapper.get('[role="dialog"][aria-labelledby="batch-release-dir-title"]')
    await dialog.get('.row-path-input').setValue('   ')
    expect(dialog.get('button[type="submit"]').text()).toBe('更新 1 条记录')
    expect(dialog.text()).toContain('空值 · 回退 full_dir')
    await dialog.trigger('submit')
    await flushPromises()

    expect(adminApi.batchUpdateReleaseDir).toHaveBeenCalledWith({
      items: [{ project_id: 10, record_id: 1, release_dir: '   ' }]
    })
  })

  it('bulk fill changes rows only after the explicit action and supports per-row reset', async () => {
    const wrapper = await mountRecords()
    const rows = wrapper.findAll('tbody tr')
    await rows[0].get('input[type=checkbox]').setValue(true)
    await rows[1].get('input[type=checkbox]').setValue(true)
    await wrapper
      .findAll('button')
      .find(button => button.text() === '批量更新 release_dir')
      .trigger('click')

    const dialog = wrapper.get('[role="dialog"][aria-labelledby="batch-release-dir-title"]')
    const rowInputs = dialog.findAll('.row-path-input')
    const bulkInput = dialog.get('#batch-release-dir-bulk-input')
    await bulkInput.setValue('/shared/release')

    expect(rowInputs.map(input => input.element.value)).toEqual(['/alpha/old', '/beta/old'])
    expect(dialog.get('button[type="submit"]').attributes('disabled')).toBeDefined()

    await dialog
      .findAll('button')
      .find(button => button.text() === '填充所有行')
      .trigger('click')
    expect(rowInputs.map(input => input.element.value)).toEqual([
      '/shared/release',
      '/shared/release'
    ])
    expect(dialog.get('button[type="submit"]').text()).toBe('更新 2 条记录')

    await dialog.findAll('.row-reset')[0].trigger('click')
    expect(rowInputs[0].element.value).toBe('/alpha/old')
    expect(rowInputs[1].element.value).toBe('/shared/release')
    expect(dialog.get('button[type="submit"]').text()).toBe('更新 1 条记录')
  })

  it('shows fallback and row validation states while keeping backend errors in the dialog', async () => {
    adminApi.batchUpdateReleaseDir.mockRejectedValue({
      response: { data: { error: '目标项目已锁定' } }
    })
    qorApi.getQorData.mockResolvedValue([
      records[0],
      { ...records[1], release_dir: '', release_dir_effective: '/beta/full', full_dir: '/beta/full' }
    ])
    const wrapper = await mountRecords()
    const rows = wrapper.findAll('tbody tr')
    await rows[1].get('input[type=checkbox]').setValue(true)
    await wrapper
      .findAll('button')
      .find(button => button.text() === '批量更新 release_dir')
      .trigger('click')

    const dialog = wrapper.get('[role="dialog"][aria-labelledby="batch-release-dir-title"]')
    expect(dialog.text()).toContain('未设置 · fallback')
    expect(dialog.text()).toContain('空值 · 回退 full_dir')
    expect(dialog.text()).toContain('/beta/full')

    const input = dialog.get('.row-path-input')
    expect(input.element.value).toBe('')
    await input.setValue('x'.repeat(501))
    expect(dialog.text()).toContain('501 / 500')
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(dialog.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(adminApi.batchUpdateReleaseDir).not.toHaveBeenCalled()

    await input.setValue(' '.repeat(3))
    expect(dialog.get('button[type="submit"]').text()).toBe('更新 0 条记录')
    expect(dialog.get('button[type="submit"]').attributes('disabled')).toBeDefined()

    await input.setValue('/beta/new')
    await dialog.trigger('submit')
    await flushPromises()

    expect(adminApi.batchUpdateReleaseDir).toHaveBeenCalledWith({
      items: [{ project_id: 20, record_id: 1, release_dir: '/beta/new' }]
    })
    expect(dialog.get('[role="alert"]').text()).toBe('目标项目已锁定')
    expect(wrapper.find('[role="dialog"][aria-labelledby="batch-release-dir-title"]').exists()).toBe(
      true
    )
  })

  it('deletes the exact project record and includes pagination in detail next', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    qorApi.getQorData.mockResolvedValue({
      records,
      pagination: { page: 2, page_size: 25, total: 27, pages: 2 }
    })
    const wrapper = await mountRecords()
    const betaRow = wrapper.findAll('tbody tr').find(row => row.text().includes('Beta'))
    await betaRow
      .findAll('button')
      .find(button => button.text() === '删除')
      .trigger('click')
    await flushPromises()
    expect(adminApi.deleteRecord).toHaveBeenCalledWith(1, 20)
    const detailHref = betaRow.get('a').attributes('href')
    expect(decodeURIComponent(detailHref)).toContain('next=/admin?page=2&page_size=25')
  })

  it('filters records by selected owner/uploader', async () => {
    adminApi.getRecordOwners.mockResolvedValue([
      { id: 7, username: 'module-owner', display_name: 'Module Owner' },
      { id: 9, username: 'module-outsider', display_name: 'Module Outsider' }
    ])
    qorApi.getQorData.mockResolvedValue({
      records: [records[0]],
      pagination: { page: 1, page_size: 50, total: 1, pages: 1 }
    })
    const wrapper = await mountRecords()

    const ownerSelect = wrapper.get('select[aria-label="Owner"]')
    expect(ownerSelect.text()).toContain('Module Owner')
    await ownerSelect.setValue('7')
    await flushPromises()

    expect(qorApi.getQorData).toHaveBeenCalledWith(
      expect.objectContaining({ owner_id: '7' }),
      expect.anything()
    )
  })
})
