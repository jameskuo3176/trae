import apiClient from './client'

export const qorApi = {
  getQorData(params, signal) {
    return apiClient.get('/qor_data', { params, signal }).then(r => r.data)
  },

  getMetrics(params) {
    return apiClient.get('/metrics', { params }).then(r => r.data)
  },

  getAggregate(params) {
    return apiClient.get('/qor/aggregate', { params }).then(r => r.data)
  },

  getDirModules(params) {
    return apiClient.get('/qor/dir_modules', { params }).then(r => r.data)
  },

  getRecordDetail(recordId, projectId = null) {
    const params = projectId ? { project_id: projectId } : undefined
    return apiClient.get(`/qor/record/${recordId}/`, { params }).then(r => r.data)
  },

  getRunNotes(params) {
    return apiClient.get('/run_notes', { params }).then(r => r.data)
  }
}
