import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import FilterBar from '@/components/filters/FilterBar.vue'
import { useFiltersStore } from '@/stores/filters'

const dataMocks = vi.hoisted(() => ({
  loadModules: vi.fn(),
  loadVersions: vi.fn(),
  loadDashboardData: vi.fn()
}))

vi.mock('@/composables/useDashboardData', () => ({
  useDashboardData: () => dataMocks
}))

describe('FilterBar path-derived version filter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    dataMocks.loadModules.mockResolvedValue()
    dataMocks.loadVersions.mockResolvedValue()
    dataMocks.loadDashboardData.mockResolvedValue()
  })

  it('expands a wildcard, applies exact versions, and reloads once', async () => {
    const filters = useFiltersStore()
    filters.projectIds = ['5']
    filters.versions = ['2026Q3_w1', '2026Q3_w2', '2026Q3_w3']
    const wrapper = mount(FilterBar)

    await wrapper.get('input[placeholder*="regr_"]').setValue('*2026Q3_w3*')
    await wrapper.findAll('button').find(button => button.text() === 'Apply').trigger('click')
    await flushPromises()

    expect(filters.versionIds).toEqual(['2026Q3_w3'])
    expect(filters.versionFilterApplied).toBe(true)
    expect(dataMocks.loadDashboardData).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('marks an unmatched applied pattern instead of falling back to all records', async () => {
    const filters = useFiltersStore()
    filters.projectIds = ['5']
    filters.versions = ['2026Q3_w1', '2026Q3_w2']
    const wrapper = mount(FilterBar)

    await wrapper.get('input[placeholder*="regr_"]').setValue('*2026Q3_w3*')
    await wrapper.findAll('button').find(button => button.text() === 'Apply').trigger('click')
    await flushPromises()

    expect(filters.versionIds).toEqual([])
    expect(filters.versionFilterApplied).toBe(true)
    expect(dataMocks.loadDashboardData).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('does not activate an autofilled directory prefix before Apply', async () => {
    const filters = useFiltersStore()
    const wrapper = mount(FilterBar)
    const directoryInput = wrapper.get('input[name="qor-directory-prefix"]')

    await directoryInput.setValue('admin')

    expect(directoryInput.attributes('autocomplete')).toBe('off')
    expect(filters.dirPrefix).toBe('')
    expect(dataMocks.loadDashboardData).not.toHaveBeenCalled()

    await wrapper.findAll('button').find(button => button.text() === 'Apply').trigger('click')
    await flushPromises()

    expect(filters.dirPrefix).toBe('admin')
    expect(dataMocks.loadDashboardData).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
