import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { annotationsApi } from '@/api/annotations'
import { useDashboardStore } from '@/stores/dashboard'
import RunNotesPanel from '@/components/dashboard/RunNotesPanel.vue'

vi.mock('@/api/annotations', () => ({
  annotationsApi: {
    batch: vi.fn(),
    image: vi.fn()
  }
}))

function mountPanel(records, selected = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const dashboard = useDashboardStore()
  dashboard.setRecords(records)
  if (selected) dashboard.selectAll()
  return mount(RunNotesPanel, {
    global: {
      plugins: [pinia],
      stubs: { AuthenticatedImage: { template: '<button class="image-stub">image</button>' } }
    }
  })
}

describe('Dashboard annotation panel', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses one batch request and preserves project-local record association', async () => {
    annotationsApi.batch.mockResolvedValue([
      {
        id: 4,
        project_id: 2,
        record_id: '7',
        text: 'Routing congestion reviewed.',
        author: { display_name: 'Timing Owner' },
        updated_at: '2026-08-12T08:00:00Z',
        record: { module_name: 'fallback', version: 'v2', tag: 'signoff' },
        images: [{ id: 9, filename: 'route.png', url: '/api/image' }]
      }
    ])
    const wrapper = mountPanel([
      { id: '7', project_id: 1, project_name: 'Alpha', module_name: 'cpu', version: 'a' },
      { id: '7', project_id: 2, project_name: 'Beta', module_name: 'gpu', version: 'b' }
    ])
    await flushPromises()
    expect(annotationsApi.batch).toHaveBeenCalledTimes(1)
    expect(annotationsApi.batch.mock.calls[0][0]).toEqual([
      { project_id: 1, record_id: '7' },
      { project_id: 2, record_id: '7' }
    ])
    expect(wrapper.text()).toContain('gpu')
    expect(wrapper.text()).toContain('Beta')
    expect(wrapper.text()).toContain('Routing congestion reviewed.')
    expect(wrapper.text()).toContain('Evidence 01')
    expect(wrapper.text()).toContain('record #7')
    expect(wrapper.text()).toContain('Revised')
    expect(wrapper.find('.image-stub').exists()).toBe(true)
  })

  it('shows one aggregate empty state without noisy record cards', async () => {
    annotationsApi.batch.mockResolvedValue([])
    const wrapper = mountPanel([{ id: '1', project_id: 1, module_name: 'cpu', version: 'v1' }])
    await flushPromises()
    expect(wrapper.find('.aggregate-empty').exists()).toBe(true)
    expect(wrapper.findAll('.annotation-ledger article')).toHaveLength(0)
  })

  it('distinguishes no run selection from selected runs without evidence', async () => {
    const wrapper = mountPanel(
      [{ id: '1', project_id: 1, module_name: 'cpu', version: 'v1' }],
      false
    )
    await flushPromises()
    expect(annotationsApi.batch).not.toHaveBeenCalled()
    expect(wrapper.find('.aggregate-empty').text()).toContain('Select one or more runs')
  })
})
