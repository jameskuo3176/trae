import { watch } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'

export function useFilters() {
  const filters = useFiltersStore()
  const dashboard = useDashboardStore()

  function onFilterChange(callback) {
    watch(
      () => filters.fingerprint,
      (newVal, oldVal) => {
        if (newVal !== oldVal) {
          dashboard.clearSelection()
          callback()
        }
      }
    )
  }

  function buildApiParams() {
    const params = {}
    if (filters.projectId) params.project_ids = filters.projectId
    if (filters.moduleIds.length > 0) params.module_ids = filters.moduleIds.join(',')
    if (filters.versionIds.length > 0) params.versions = filters.versionIds.join(',')
    if (filters.dirPrefix) params.dir_prefix = filters.dirPrefix
    return params
  }

  return {
    filters,
    onFilterChange,
    buildApiParams
  }
}
