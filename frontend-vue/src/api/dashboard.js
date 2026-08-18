import apiClient from './client'

const unwrap = response => response.data?.data ?? response.data

export const dashboardApi = {
  modules(projectIds, signal) {
    const params =
      projectIds && projectIds.length ? { project_ids: projectIds.join(',') } : {}
    return apiClient.get('/v2/modules', { params, signal }).then(response => ({
      modules: response.data.data || [],
      meta: response.data.meta || {}
    }))
  },
  versions(projectIds, signal) {
    const params =
      projectIds && projectIds.length ? { project_ids: projectIds.join(',') } : {}
    return apiClient.get('/v2/versions', { params, signal }).then(unwrap)
  },
  records(params, signal) {
    return apiClient.get('/v2/records', { params, signal }).then(response => ({
      records: response.data.data || [],
      pagination: response.data.pagination || null,
      meta: response.data.meta || {}
    }))
  },
  record(projectId, recordId, signal) {
    return apiClient.get(`/v2/projects/${projectId}/records/${recordId}`, { signal }).then(unwrap)
  },
  setRisk(projectId, recordId, rating) {
    return apiClient
      .put(`/v2/projects/${projectId}/records/${recordId}/risk`, { rating })
      .then(unwrap)
  },
  clearRisk(projectId, recordId) {
    return apiClient.delete(`/v2/projects/${projectId}/records/${recordId}/risk`).then(unwrap)
  },
  rawReport(projectId, recordId, signal) {
    return apiClient
      .get(`/v2/projects/${projectId}/records/${recordId}/raw`, { signal })
      .then(unwrap)
      .then(value => value?.content ?? value)
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
