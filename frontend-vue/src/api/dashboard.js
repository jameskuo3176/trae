import apiClient from './client'

const unwrap = response => response.data?.data ?? response.data

export const dashboardApi = {
  modules(projectId, signal) {
    return apiClient.get('/v2/modules', { params: { project_id: projectId }, signal }).then(unwrap)
  },
  versions(projectId, signal) {
    return apiClient.get('/v2/versions', { params: { project_id: projectId }, signal }).then(unwrap)
  },
  records(params, signal) {
    return apiClient.get('/v2/records', { params, signal }).then(response => ({
      records: response.data.data || [],
      pagination: response.data.pagination || null
    }))
  },
  record(projectId, recordId, signal) {
    return apiClient.get(`/v2/projects/${projectId}/records/${recordId}`, { signal }).then(unwrap)
  },
  rawReport(projectId, recordId, signal) {
    return apiClient
      .get(`/v2/projects/${projectId}/records/${recordId}/raw`, { signal })
      .then(unwrap)
  },
  violations(projectId, recordId, signal) {
    return apiClient
      .get(`/v2/projects/${projectId}/records/${recordId}/violations`, { signal })
      .then(unwrap)
  },
  notes(projectId, recordId, signal) {
    return apiClient
      .get(`/v2/projects/${projectId}/records/${recordId}/notes`, { signal })
      .then(unwrap)
  },
  listConfigs() {
    return apiClient.get('/dashboard/list').then(response => response.data)
  },
  getConfig(configId) {
    return apiClient.get(`/dashboard/${configId}`).then(response => response.data)
  },
  saveConfig(config) {
    return apiClient.post('/dashboard/save', config).then(response => response.data)
  }
}
