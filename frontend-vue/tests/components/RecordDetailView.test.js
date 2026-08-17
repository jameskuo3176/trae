import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import RecordDetailView from '@/views/RecordDetailView.vue'
import { qorApi } from '@/api/qor'
import { annotationsApi } from '@/api/annotations'

vi.mock('@/api/qor', () => ({
  qorApi: { getRecordDetail: vi.fn() }
}))
vi.mock('@/api/annotations', () => ({
  annotationsApi: {
    get: vi.fn(),
    save: vi.fn(),
    image: vi.fn()
  }
}))

async function mountDetail(query = '', attachTo = null) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/record/:id', name: 'RecordDetail', component: RecordDetailView }]
  })
  await router.push(`/record/7${query}`)
  await router.isReady()
  const wrapper = mount(RecordDetailView, {
    attachTo,
    global: { plugins: [router] }
  })
  await flushPromises()
  return wrapper
}

describe('RecordDetailView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    annotationsApi.get.mockResolvedValue({ annotation: null, can_edit: false })
    URL.createObjectURL = vi.fn(() => 'blob:preview')
    URL.revokeObjectURL = vi.fn()
  })

  it('parses the detail envelope and renders grouped fields', async () => {
    qorApi.getRecordDetail.mockResolvedValue({
      record: {
        id: 7,
        module_name: 'top',
        version: 'v1',
        area_total: 123,
        source_file: '/workspace/top.sv',
        extra_fields: { density: 0.72 }
      },
      siblings: [{ id: 7, version: 'v1', area_total: 123 }],
      sibling_count: 1
    })

    const wrapper = await mountDetail('?next=%2Fadmin')
    expect(wrapper.text()).toContain('面积')
    expect(wrapper.text()).toContain('density')
    expect(wrapper.text()).toContain('同版本 Runs（1）')
    expect(wrapper.get('.back-link').attributes('href')).toBe('/admin')
  })

  it('rejects an external next target', async () => {
    qorApi.getRecordDetail.mockResolvedValue({
      record: { id: 7, extra_fields: {} },
      siblings: [],
      sibling_count: 0
    })

    const wrapper = await mountDetail('?next=%2F%2Fevil.example')
    expect(wrapper.get('.back-link').attributes('href')).toBe('/admin')
  })

  it('restores the exact filtered and paginated admin URL', async () => {
    qorApi.getRecordDetail.mockResolvedValue({
      record: { id: 7, project_id: 3, extra_fields: {} },
      siblings: []
    })
    const next = encodeURIComponent('/admin?project_id=3&module_id=9&page=4&page_size=25')
    const wrapper = await mountDetail(`?project_id=3&next=${next}`)
    expect(wrapper.get('.back-link').attributes('href')).toBe(
      '/admin?project_id=3&module_id=9&page=4&page_size=25'
    )
  })

  it('keeps default/final path groups separate and excludes timing extras', async () => {
    qorApi.getRecordDetail.mockResolvedValue({
      record: {
        id: 7,
        project_id: 3,
        extra_fields: {
          timing_sections: {
            default: { slow: { CORE: { WNS: -2, TNS: -10 } } },
            final: { slow: { CORE: { WNS: -1, TNS: -4 } } }
          },
          clocks: { LEGACY: { wns: -3 } },
          density: 0.72
        }
      },
      siblings: []
    })
    const wrapper = await mountDetail('?project_id=3')
    const analyses = wrapper.findAll('.timing-analysis')
    expect(analyses).toHaveLength(2)
    expect(analyses[0].text()).toContain('-2.00')
    expect(analyses[1].text()).toContain('-1.00')
    expect(wrapper.find('.extra-fields').text()).toContain('density')
    expect(wrapper.find('.extra-fields').text()).not.toContain('timing_sections')
    expect(wrapper.find('.extra-fields').text()).not.toContain('clocks')
  })

  it('supports edit cancel, image preview removal, and atomic save form data', async () => {
    qorApi.getRecordDetail.mockResolvedValue({
      record: { id: 7, project_id: 3, module_name: 'top', extra_fields: {} },
      siblings: []
    })
    annotationsApi.get.mockResolvedValue({
      annotation: {
        id: 1,
        text: 'Persisted evidence',
        author: { username: 'owner' },
        updated_at: '2026-08-12T08:00:00Z',
        images: []
      },
      can_edit: true
    })
    annotationsApi.save.mockResolvedValue({
      annotation: {
        id: 1,
        text: 'Saved evidence',
        author: { username: 'owner' },
        updated_at: '2026-08-12T09:00:00Z',
        images: []
      },
      can_edit: true
    })
    const wrapper = await mountDetail('?project_id=3')
    const editButton = wrapper.findAll('button').find(button => button.text() === '编辑模式')
    await editButton.trigger('click')
    await wrapper.get('textarea').setValue('Unsaved change')
    await wrapper
      .findAll('button')
      .find(button => button.text() === 'Cancel')
      .trigger('click')
    expect(wrapper.text()).toContain('Persisted evidence')
    expect(annotationsApi.save).not.toHaveBeenCalled()

    await wrapper
      .findAll('button')
      .find(button => button.text() === '编辑模式')
      .trigger('click')
    await wrapper.get('textarea').setValue('Saved evidence')
    const input = wrapper.get('input[type=file]')
    const file = new File(['image'], 'evidence.png', { type: 'image/png' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    expect(wrapper.find('.edit-gallery').text()).toContain('evidence.png')
    await wrapper.find('.edit-gallery button').trigger('click')
    expect(wrapper.find('.edit-gallery').exists()).toBe(false)
    await wrapper
      .findAll('button')
      .find(button => button.text() === 'Save annotation')
      .trigger('click')
    await flushPromises()
    expect(annotationsApi.save).toHaveBeenCalled()
    const form = annotationsApi.save.mock.calls[0][2]
    expect(form.get('text')).toBe('Saved evidence')
    expect(wrapper.text()).toContain('Saved evidence')
  })

  it('focuses the lightbox close control, closes on Escape, and restores thumbnail focus', async () => {
    qorApi.getRecordDetail.mockResolvedValue({
      record: { id: 7, project_id: 3, module_name: 'top', extra_fields: {} },
      siblings: []
    })
    annotationsApi.get.mockResolvedValue({
      annotation: {
        id: 1,
        text: 'Image evidence',
        author: { username: 'owner' },
        created_at: '2026-08-12T08:00:00Z',
        updated_at: '2026-08-12T09:00:00Z',
        images: [
          {
            id: 2,
            filename: 'timing.png',
            byte_size: 1200,
            content_type: 'image/png',
            url: '/api/v2/image'
          }
        ]
      },
      can_edit: true
    })
    annotationsApi.image.mockResolvedValue(new Blob(['image'], { type: 'image/png' }))
    const wrapper = await mountDetail('?project_id=3', document.body)
    await flushPromises()
    const thumbnail = wrapper.get('.authenticated-image')
    await thumbnail.trigger('click')
    await flushPromises()
    const close = wrapper.get('[aria-label="Close image preview"]')
    expect(document.activeElement).toBe(close.element)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('.image-lightbox').exists()).toBe(false)
    expect(document.activeElement).toBe(thumbnail.element)
    wrapper.unmount()
  })

  it('keeps sticky path-group hover colors theme-safe', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/RecordDetailView.vue'), 'utf8')
    expect(source).toMatch(
      /\.timing-table tbody tr:hover th:first-child\s*\{[^}]*background:\s*var\(--color-surface-hover\);[^}]*color:\s*var\(--color-text-on-hover\)/s
    )
    expect(source).toContain('.timing-table tbody tr:hover th:first-child *')
  })
})
