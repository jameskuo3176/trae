import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { projectsApi } from '@/api/projects'
import { qorApi } from '@/api/qor'
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
      filters.modules = filters.projectId ? await dashboardApi.modules(filters.projectId) : []
    } catch (e) {
      console.error('Failed to load modules:', e)
    }
  }

  async function loadVersions() {
    try {
      filters.versions = filters.projectId ? await dashboardApi.versions(filters.projectId) : []
    } catch (e) {
      console.error('Failed to load versions:', e)
    }
  }

  async function loadDashboardData() {
    const { seq, signal } = dashboard.startRequest()
    dashboard.setLoading(true)
    dashboard.setError(null)

    try {
      let data
      let pagination = null
      if (filters.projectId) {
        const modules = filters.moduleIds.length ? filters.moduleIds : [null]
        const versions = filters.versionIds.length ? filters.versionIds : [null]
        const requests = modules.flatMap(moduleId =>
          versions.map(version =>
            dashboardApi.records(
              {
                project_id: filters.projectId,
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
              module_id: String(record.module_id)
            }
            if (!filters.dirPrefix || normalized.full_dir?.startsWith(filters.dirPrefix)) {
              unique.set(normalized.id, normalized)
            }
          })
        data = [...unique.values()]
        pagination =
          responses.length === 1
            ? responses[0].pagination
            : {
                page: 1,
                page_size: data.length,
                total: data.length,
                pages: 1
              }
      } else {
        const params = {}
        if (filters.dirPrefix) params.dir_prefix = filters.dirPrefix
        data = await qorApi.getQorData(params, signal)
        data = data.map(record => ({
          ...record,
          id: String(record.id),
          module_id: String(record.module_id)
        }))
      }

      if (!dashboard.isRequestValid(seq)) return

      dashboard.setRecords(data)
      dashboard.setPagination(pagination)
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
