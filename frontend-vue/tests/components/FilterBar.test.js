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

    await wrapper
      .findAll('button')
      .find(button => button.text().includes('选择版本') || button.text().includes('已选'))
      .trigger('click')
    await wrapper.get('input[placeholder*="regr_"]').setValue('*2026Q3_w3*')
    await wrapper
      .findAll('button')
      .find(button => button.text() === 'Apply')
      .trigger('click')
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

    await wrapper
      .findAll('button')
      .find(button => /选择版本|已选 .* 个版本/.test(button.text()))
      .trigger('click')
    await wrapper.get('input[placeholder*="regr_"]').setValue('*2026Q3_w3*')
    await wrapper
      .findAll('button')
      .find(button => button.text() === 'Apply')
      .trigger('click')
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

    await wrapper
      .findAll('button')
      .find(button => button.text() === 'Apply')
      .trigger('click')
    await flushPromises()

    expect(filters.dirPrefix).toBe('admin')
    expect(dataMocks.loadDashboardData).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('renders path-derived versions as a multi-select dropdown', async () => {
    const filters = useFiltersStore()
    filters.projectIds = ['5']
    filters.versions = ['regr_a', 'regr_b']
    filters.versionIds = ['regr_b']
    const wrapper = mount(FilterBar)

    expect(wrapper.text()).toContain('已选 1 个版本')
    expect(wrapper.find('.chips[aria-label="Version filters"]').exists()).toBe(false)

    await wrapper
      .findAll('button')
      .find(button => button.text().includes('已选 1 个版本'))
      .trigger('click')

    const versionButtons = wrapper.find('[aria-label="Version filters"]').findAll('button')
    expect(versionButtons.map(button => button.text())).toEqual(['regr_a', 'regr_b'])
    expect(versionButtons[1].attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })

  it('defaults to the latest version after project selection changes', async () => {
    const filters = useFiltersStore()
    filters.projects = [{ id: 5, name: 'Demo' }]
    filters.projectIds = []
    const wrapper = mount(FilterBar)

    dataMocks.loadVersions.mockImplementation(async options => {
      filters.versions = ['regr_20251210', 'regr_20260629']
      if (options?.selectLatest) {
        filters.versionIds = ['regr_20260629']
      }
    })

    await wrapper
      .findAll('button')
      .find(button => button.text().includes('选择项目'))
      .trigger('click')
    await wrapper.find('[aria-label="Project filters"]').find('button').trigger('click')
    await flushPromises()

    expect(dataMocks.loadVersions).toHaveBeenCalledWith({ selectLatest: true })
    expect(filters.versionIds).toEqual(['regr_20260629'])
    wrapper.unmount()
  })

  it('auto-selects modules owned by the chosen owner under the current project', async () => {
    const filters = useFiltersStore()
    filters.projectIds = ['5']
    filters.modules = [
      {
        id: 1,
        name: 'cpu',
        owner_id: 9,
        owner_username: 'alice',
        owner_display_name: 'Alice',
        owner_ids: [9],
        owners: [{ id: 9, username: 'alice', display_name: 'Alice', project_id: 5 }]
      },
      {
        id: 2,
        name: 'cache',
        owner_id: 9,
        owner_username: 'alice',
        owner_display_name: 'Alice',
        owner_ids: [9],
        owners: [{ id: 9, username: 'alice', display_name: 'Alice', project_id: 5 }]
      },
      {
        id: 3,
        name: 'noc',
        owner_id: 8,
        owner_username: 'bob',
        owner_display_name: 'Bob',
        owner_ids: [8],
        owners: [{ id: 8, username: 'bob', display_name: 'Bob', project_id: 5 }]
      }
    ]
    const wrapper = mount(FilterBar)

    await wrapper
      .findAll('button')
      .find(button => button.text().includes('选择 Owner'))
      .trigger('click')
    await wrapper
      .find('[aria-label="Owner filters"]')
      .findAll('button')
      .find(button => button.text() === 'Alice')
      .trigger('click')
    await flushPromises()

    expect(filters.ownerIds).toEqual(['9'])
    expect(filters.moduleIds.sort()).toEqual(['1', '2'])
    expect(dataMocks.loadDashboardData).toHaveBeenCalled()
    wrapper.unmount()
  })
})
