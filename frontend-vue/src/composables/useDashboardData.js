import { ref, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { projectsApi } from '@/api/projects'
import { qorApi } from '@/api/qor'

export function useDashboardData() {
  const auth = useAuthStore()
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
      if (!filters.projectId) {
        // 未选项目时，从所有项目加载全部模块
        const allProjects = await projectsApi.list()
        const allModules = []
        for (const p of (allProjects || [])) {
          if (p.modules && Array.isArray(p.modules)) {
            for (const m of p.modules) {
              allModules.push({ ...m, project_id: p.id, project_name: p.name })
            }
          }
        }
        filters.modules = allModules
        return
      }
      const data = await projectsApi.getModules(filters.projectId)
      filters.modules = data || []
    } catch (e) {
      console.error('Failed to load modules:', e)
    }
  }

  async function loadVersions() {
    try {
      const params = {}
      if (filters.moduleIds.length > 0) {
        params.module_ids = filters.moduleIds.join(',')
      }
      if (filters.projectId) {
        params.project_id = filters.projectId
      }
      const versions = await projectsApi.getVersions(params)
      filters.versions = versions || []
    } catch (e) {
      console.error('Failed to load versions:', e)
    }
  }

  async function loadDashboardData() {
    const { seq, signal } = dashboard.startRequest()
    dashboard.setLoading(true)
    dashboard.setError(null)

    try {
      const params = {}
      if (filters.projectId) params.project_ids = filters.projectId
      if (filters.moduleIds.length > 0) params.module_ids = filters.moduleIds.join(',')
      if (filters.versionIds.length > 0) params.versions = filters.versionIds.join(',')
      if (filters.dirPrefix) params.dir_prefix = filters.dirPrefix

      const data = await qorApi.getQorData(params, signal)

      if (!dashboard.isRequestValid(seq)) return

      dashboard.setRecords(data)
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