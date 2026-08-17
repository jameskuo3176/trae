import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { projectsApi } from '@/api/projects'
import { dashboardApi } from '@/api/dashboard'

export function useDashboardData() {
  const filters = useFiltersStore()
  const dashboard = useDashboardStore()

  async function loadProjects() {
    try {
      const data = await projectsApi.list()
      filters.projects = data || []
    } catch (e) {
      console.error('Failed to load projects:', e)
    }
  }

  async function loadModules() {
    try {
      const response = await dashboardApi.modules(filters.projectIds)
      filters.modules = response.modules
      dashboard.setDiagnostics(response.meta?.diagnostics || [])
    } catch (e) {
      console.error('Failed to load modules:', e)
      filters.modules = []
      dashboard.setDiagnostics([{ message: e.message || 'Global module query failed' }])
    }
  }

  async function loadVersions() {
    try {
      if (filters.projectIds.length) {
        filters.versions = await dashboardApi.versions(filters.projectIds)
      } else {
        const responses = await Promise.all(
          filters.projects.map(project => dashboardApi.versions([project.id]))
        )
        filters.versions = [...new Set(responses.flat())].sort()
      }
    } catch (e) {
      console.error('Failed to load versions:', e)
    }
  }

  async function loadDashboardData() {
    const { seq, signal } = dashboard.startRequest()
    dashboard.setLoading(true)
    dashboard.setError(null)

    try {
      if (filters.versionFilterApplied && !filters.versionIds.length) {
        dashboard.setRecords([])
        dashboard.setPagination({ page: 1, page_size: 0, total: 0, pages: 0 })
        dashboard.setDiagnostics([])
        dashboard.clearSelection()
        return
      }
      const modules = filters.moduleIds.length ? filters.moduleIds : [null]
      const versions = filters.versionIds.length ? filters.versionIds : [null]
      const requests = modules.flatMap(moduleId =>
        versions.map(version =>
          dashboardApi.records(
            {
              project_ids: filters.projectIds.length ? filters.projectIds.join(',') : undefined,
              module_id: moduleId || undefined,
              version: version || undefined,
              page: 1,
              page_size: 200
            },
            signal
          )
        )
      )
      const responses = await Promise.all(requests)
      const unique = new Map()
      responses
        .flatMap(response => response.records)
        .forEach(record => {
          const normalized = {
            ...record,
            id: String(record.id),
            module_id: record.module_id == null ? null : String(record.module_id)
          }
          if (!filters.dirPrefix || normalized.full_dir?.startsWith(filters.dirPrefix)) {
            unique.set(`${normalized.project_id}:${normalized.id}`, normalized)
          }
        })
      const data = [...unique.values()]
      const pagination =
        responses.length === 1
          ? responses[0].pagination
          : { page: 1, page_size: data.length, total: data.length, pages: 1 }
      const diagnostics = responses.flatMap(response => response.meta?.unmapped_modules || [])

      if (!dashboard.isRequestValid(seq)) return

      dashboard.setRecords(data)
      dashboard.setPagination(pagination)
      dashboard.setDiagnostics(diagnostics)
      if (data.length > 0) {
        dashboard.selectFirstN(4)
      }
    } catch (e) {
      if (e.name === 'CanceledError' || e.code === 'ERR_CANCELED') return
      if (!dashboard.isRequestValid(seq)) return
      dashboard.setError(e.message || '数据加载失败')
      console.error('Dashboard data load failed:', e)
    } finally {
      if (dashboard.isRequestValid(seq)) {
        dashboard.setLoading(false)
      }
    }
  }

  return {
    loadProjects,
    loadModules,
    loadVersions,
    loadDashboardData
  }
}
