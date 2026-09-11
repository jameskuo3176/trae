import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DataUploadModal from '@/components/admin/DataUploadModal.vue'
import { adminApi } from '@/api/admin'

vi.mock('@/api/admin', () => ({
  adminApi: {
    previewCsvUpload: vi.fn(),
    uploadCsv: vi.fn()
  }
}))

const projects = [
  {
    id: 7,
    name: 'Writable',
    is_writable: true,
    modules: [{ id: 71, name: 'cpu' }]
  },
  { id: 8, name: 'Locked', is_writable: false }
]

async function mountOpen(props = {}) {
  const wrapper = mount(DataUploadModal, {
    props: {
      modelValue: false,
      projects,
      ...props
    },
    global: {
      stubs: {
        LoadingSpinner: { template: '<span class="loading-stub">loading</span>' }
      }
    }
  })
  await wrapper.setProps({ modelValue: true })
  await flushPromises()
  return wrapper
}

async function selectCsv(wrapper) {
  const csv = new File(['module_name,area_total,wns_setup\ncpu,100,-0.2\n'], 'qor.csv', {
    type: 'text/csv'
  })
  const input = wrapper.get('input[type="file"]:not([webkitdirectory])')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [csv]
  })
  await input.trigger('change')
  await flushPromises()
  return csv
}

describe('DataUploadModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    adminApi.previewCsvUpload.mockResolvedValue({
      ok: true,
      files: [
        {
          filename: 'qor.csv',
          relative_path: 'qor.csv',
          inferred_module: 'cpu',
          module_exists: true,
          can_auto_create: false,
          total_rows: 1,
          columns: ['module_name', 'area_total', 'wns_setup'],
          preview: [{ module_name: 'cpu', area_total: '100', wns_setup: '-0.2' }],
          errors: []
        }
      ],
      summary: { total_files: 1, valid_files: 1, total_rows: 1, error_files: 0 }
    })
    adminApi.uploadCsv.mockResolvedValue({
      ok: true,
      saved: 1,
      updated: 0,
      skipped: 0
    })
  })

  it('previews a single CSV and sends the aligned multi-file contract', async () => {
    const wrapper = await mountOpen({ initialProjectId: 7 })
    expect(wrapper.get('#upload-project').element.value).toBe('7')
    expect(wrapper.get('#upload-project').findAll('option')).toHaveLength(2)

    const csv = await selectCsv(wrapper)
    const previewForm = adminApi.previewCsvUpload.mock.calls[0][0]
    expect(previewForm.getAll('files')).toEqual([csv])
    expect(previewForm.getAll('file_paths')).toEqual(['qor.csv'])
    expect(previewForm.get('project_id')).toBe('7')
    expect(previewForm.get('module_name_source')).toBe('csv')
    expect(previewForm.get('filename_suffixes')).toBe('_qor,qor,_qor_report')
    expect(wrapper.get('.preview-table').text()).toContain('module_name')
    expect(wrapper.get('.preview-table').text()).toContain('cpu')
    expect(wrapper.get('.summary-strip').text()).toContain('1 行')

    await wrapper.get('.release-options').trigger('click')
    await wrapper.get('#release-dir').setValue('/release/run')
    await wrapper.get('.checkbox-group input').setValue(true)
    await wrapper
      .findAll('.modal-footer button')
      .find(button => button.text().includes('确认导入'))
      .trigger('click')
    await flushPromises()

    const uploadForm = adminApi.uploadCsv.mock.calls[0][0]
    expect(uploadForm.getAll('files')).toEqual([csv])
    expect(uploadForm.getAll('file_paths')).toEqual(['qor.csv'])
    expect(uploadForm.get('project_id')).toBe('7')
    expect(uploadForm.get('module_id')).toBe('71')
    expect(uploadForm.get('release_dir')).toBe('/release/run')
    expect(uploadForm.get('mark_released')).toBe('true')
    expect(uploadForm.get('auto_release')).toBeNull()
    expect(wrapper.get('.success-content').text()).toContain('新增 1')
    expect(wrapper.get('.success-content').exists()).toBe(true)
    expect(wrapper.emitted('success')).toHaveLength(1)
  })

  it('shows preview and upload failures inside the dialog', async () => {
    adminApi.previewCsvUpload.mockRejectedValueOnce(new Error('CSV 列缺失'))
    const wrapper = await mountOpen({ initialProjectId: 7 })

    await selectCsv(wrapper)

    expect(wrapper.get('.upload-error').text()).toBe('CSV 列缺失')
    expect(wrapper.find('.preview-section').exists()).toBe(false)

    adminApi.previewCsvUpload.mockResolvedValueOnce({
      files: [
        {
          filename: 'qor.csv',
          relative_path: 'qor.csv',
          inferred_module: 'cpu',
          module_exists: true,
          total_rows: 1,
          columns: ['module_name'],
          preview: [{ module_name: 'cpu' }],
          errors: []
        }
      ],
      summary: { total_files: 1, valid_files: 1, total_rows: 1, error_files: 0 }
    })
    await selectCsv(wrapper)
    adminApi.uploadCsv.mockRejectedValueOnce(new Error('缺少 project_id'))
    await wrapper
      .findAll('.modal-footer button')
      .find(button => button.text().includes('确认导入'))
      .trigger('click')
    await flushPromises()

    expect(wrapper.get('.upload-error').text()).toBe('缺少 project_id')
    expect(wrapper.find('.success-content').exists()).toBe(false)
  })

  it('shows the backend message from a direct Axios 400 response', async () => {
    const axiosError = new Error('Request failed with status code 400')
    axiosError.response = {
      status: 400,
      data: { error: '上传文件数量超过服务器限制（最多 500 个）' }
    }
    adminApi.previewCsvUpload.mockRejectedValueOnce(axiosError)
    const wrapper = await mountOpen({ initialProjectId: 7 })

    await selectCsv(wrapper)

    expect(wrapper.get('.upload-error').text()).toBe('上传文件数量超过服务器限制（最多 500 个）')
  })

  it('keeps an explicit module selection ahead of CSV module_name', async () => {
    const wrapper = await mountOpen({
      initialProjectId: 7,
      projects: [
        {
          id: 7,
          name: 'Writable',
          is_writable: true,
          modules: [
            { id: 71, name: 'cpu' },
            { id: 72, name: 'manual-target' }
          ]
        }
      ]
    })
    await wrapper.get('#upload-module').setValue('72')
    await wrapper.get('#upload-module').trigger('change')
    await selectCsv(wrapper)

    expect(wrapper.get('.upload-target').text()).toContain('Writable')
    expect(wrapper.get('.upload-target').text()).toContain('manual-target')
    await wrapper
      .findAll('.modal-footer button')
      .find(button => button.text().includes('确认导入'))
      .trigger('click')
    await flushPromises()

    expect(adminApi.uploadCsv.mock.calls[0][0].get('module_id')).toBe('72')
  })

  it('does not show success when the backend reports zero imported rows', async () => {
    adminApi.uploadCsv.mockResolvedValueOnce({
      ok: false,
      saved: 0,
      updated: 0,
      skipped: 1,
      error: '上传失败：所有文件均未保存或更新任何记录',
      file_results: [{ ok: false, error: '没有导入任何记录。第 2 行：缺少 full_dir' }]
    })
    const wrapper = await mountOpen({ initialProjectId: 7 })
    await selectCsv(wrapper)
    await wrapper
      .findAll('.modal-footer button')
      .find(button => button.text().includes('确认导入'))
      .trigger('click')
    await flushPromises()

    expect(wrapper.find('.success-content').exists()).toBe(false)
    expect(wrapper.get('.upload-error').text()).toContain('没有导入任何记录')
    expect(wrapper.emitted('success')).toBeUndefined()
  })

  it('requires a writable project before previewing a file', async () => {
    const wrapper = await mountOpen({
      projects: [
        { id: 7, name: 'Alpha', is_writable: true },
        { id: 8, name: 'Beta', is_writable: true }
      ]
    })

    await selectCsv(wrapper)

    expect(adminApi.previewCsvUpload).not.toHaveBeenCalled()
    expect(wrapper.get('.upload-error').text()).toBe('请先选择目标项目')
  })

  it('disables directory import when every previewed file is invalid', async () => {
    adminApi.previewCsvUpload.mockResolvedValueOnce({
      ok: false,
      files: [
        {
          filename: 'block_qor.csv',
          relative_path: 'demo_batch_upload/block_qor.csv',
          inferred_module: null,
          module_exists: false,
          can_auto_create: false,
          total_rows: 0,
          columns: [],
          preview: [],
          errors: [
            {
              code: 'invalid_upload_file',
              message: '目录模式要求 CSV 位于 base/module_name/ 文件夹下'
            }
          ]
        }
      ],
      summary: { total_files: 1, valid_files: 0, total_rows: 0, error_files: 1 }
    })
    const wrapper = await mountOpen({ initialProjectId: 7 })
    await wrapper.get('input[type="radio"][value="directory"]').setValue()

    const csv = new File(['area_total\n1'], 'block_qor.csv', { type: 'text/csv' })
    Object.defineProperty(csv, 'webkitRelativePath', {
      configurable: true,
      value: 'demo_batch_upload/block_qor.csv'
    })
    const input = wrapper.get('input[webkitdirectory]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [csv] })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.get('.inline-error').text()).toContain('均无法导入')
    const confirm = wrapper
      .findAll('.modal-footer button')
      .find(button => button.text().includes('确认导入'))
    expect(confirm.attributes('disabled')).toBeDefined()
  })

  it('shows readable preview errors and allows partial directory import', async () => {
    adminApi.previewCsvUpload.mockResolvedValueOnce({
      ok: true,
      files: [
        {
          filename: 'module_alu_qor.csv',
          relative_path: 'base/module_alu/module_alu_qor.csv',
          inferred_module: 'module_alu',
          module_exists: true,
          can_auto_create: false,
          total_rows: 2,
          columns: ['wns_setup'],
          preview: [{ wns_setup: '-0.1' }],
          errors: []
        },
        {
          filename: 'block_qor.csv',
          relative_path: 'base/block_qor.csv',
          inferred_module: null,
          module_exists: false,
          can_auto_create: false,
          total_rows: 0,
          columns: [],
          preview: [],
          errors: [
            {
              code: 'invalid_upload_file',
              message: '目录模式要求 CSV 位于 base/module_name/ 文件夹下'
            }
          ]
        }
      ],
      summary: { total_files: 2, valid_files: 1, total_rows: 2, error_files: 1 }
    })
    const wrapper = await mountOpen({ initialProjectId: 7 })
    await wrapper.get('input[type="radio"][value="directory"]').setValue()

    const good = new File(['wns_setup\n-0.1'], 'module_alu_qor.csv', { type: 'text/csv' })
    Object.defineProperty(good, 'webkitRelativePath', {
      configurable: true,
      value: 'base/module_alu/module_alu_qor.csv'
    })
    const bad = new File(['area_total\n1'], 'block_qor.csv', { type: 'text/csv' })
    Object.defineProperty(bad, 'webkitRelativePath', {
      configurable: true,
      value: 'base/block_qor.csv'
    })
    const input = wrapper.get('input[webkitdirectory]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [good, bad] })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.get('.partial-warning').text()).toContain('1 个文件无法导入')
    expect(wrapper.get('.manifest-table').text()).toContain('base/module_name')
    const confirm = wrapper
      .findAll('.modal-footer button')
      .find(button => button.text().includes('确认导入 1 个模块'))
    expect(confirm.attributes('disabled')).toBeUndefined()
  })

  it('previews a directory with CSV-only files and relative paths', async () => {
    adminApi.previewCsvUpload.mockResolvedValueOnce({
      ok: true,
      files: [
        {
          filename: 'module_alu_qor.csv',
          relative_path: 'base/module_alu/module_alu_qor.csv',
          inferred_module: 'module_alu',
          module_exists: false,
          can_auto_create: true,
          total_rows: 3,
          columns: ['wns_setup'],
          preview: [{ wns_setup: '-0.1' }],
          errors: []
        }
      ],
      summary: { total_files: 1, valid_files: 1, total_rows: 3, error_files: 0 }
    })
    const wrapper = await mountOpen({ initialProjectId: 7 })
    await wrapper.get('input[type="radio"][value="directory"]').setValue()

    const csv = new File(['wns_setup\n-0.1'], 'module_alu_qor.csv', { type: 'text/csv' })
    Object.defineProperty(csv, 'webkitRelativePath', {
      configurable: true,
      value: 'base/module_alu/module_alu_qor.csv'
    })
    const ignored = new File(['notes'], 'README.txt', { type: 'text/plain' })
    const input = wrapper.get('input[webkitdirectory]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [csv, ignored]
    })
    await input.trigger('change')
    await flushPromises()

    const previewForm = adminApi.previewCsvUpload.mock.calls[0][0]
    expect(previewForm.getAll('files')).toEqual([csv])
    expect(previewForm.getAll('file_paths')).toEqual(['base/module_alu/module_alu_qor.csv'])
    expect(previewForm.get('module_name_source')).toBe('dirname')
    expect(wrapper.get('.manifest-table').text()).toContain('module_alu')
    expect(wrapper.get('.manifest-table').text()).toContain('可新建')
  })

  it('keeps partial failures visible in the completion summary', async () => {
    adminApi.uploadCsv.mockResolvedValueOnce({
      ok: true,
      saved: 2,
      updated: 0,
      skipped: 1,
      errors: 1,
      file_results: [
        { ok: true, relative_path: 'base/cpu/a.csv', inferred_module: 'cpu', saved: 2 },
        { ok: false, relative_path: 'base/gpu/b.csv', inferred_module: 'gpu', error: '列缺失' }
      ]
    })
    const wrapper = await mountOpen({ initialProjectId: 7 })
    await selectCsv(wrapper)
    await wrapper
      .findAll('.modal-footer button')
      .find(button => button.text().includes('确认导入'))
      .trigger('click')
    await flushPromises()

    expect(wrapper.get('.success-content').text()).toContain('错误 1')
    expect(wrapper.get('.success-content').text()).toContain('base/gpu/b.csv')
    expect(wrapper.get('.success-content').text()).toContain('列缺失')
  })
})
