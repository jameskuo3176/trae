import apiClient from './client'

export const projectsApi = {
  list() {
    return apiClient.get('/projects').then(r => r.data)
  },

  getModules(projectId) {
    return apiClient.get(`/modules/${projectId}/`).then(r => r.data)
  },

  getVersions(params) {
    return apiClient.get('/versions', { params }).then(r => r.data)
  },

  listV1() {
    return apiClient.get('/v1/projects').then(r => r.data)
  },

  getV1(id) {
    return apiClient.get(`/v1/projects/${id}`).then(r => r.data)
  }
}
