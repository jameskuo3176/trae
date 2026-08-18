import apiClient from './client'

export const reviewApi = {
  weekly(params) {
    return apiClient.get('/reviews/weekly', { params }).then(r => r.data)
  },
  selectStar(payload) {
    return apiClient.post('/reviews/weekly/star', payload).then(r => r.data)
  },
  clearStar(payload) {
    return apiClient.delete('/reviews/weekly/star', { data: payload }).then(r => r.data)
  },
  setRisk(projectId, recordId, rating) {
    return apiClient
      .put(`/v2/projects/${projectId}/records/${recordId}/risk`, { rating })
      .then(r => r.data.data)
  },
  clearRisk(projectId, recordId) {
    return apiClient
      .delete(`/v2/projects/${projectId}/records/${recordId}/risk`)
      .then(r => r.data.data)
  },
  list(type, params) {
    return apiClient.get(`/reviews/${type}`, { params }).then(r => r.data.items || [])
  },
  create(type, payload) {
    return apiClient.post(`/reviews/${type}`, payload).then(r => r.data)
  },
  detail(type, id, projectId) {
    return apiClient
      .get(`/reviews/${type}/${id}`, { params: { project_id: projectId } })
      .then(r => r.data)
  },
  update(type, id, projectId, payload) {
    return apiClient
      .put(`/reviews/${type}/${id}`, { ...payload, project_id: projectId })
      .then(r => r.data)
  },
  remove(type, id, projectId) {
    return apiClient
      .delete(`/reviews/${type}/${id}`, { params: { project_id: projectId } })
      .then(r => r.data)
  },
  submit(type, id, projectId) {
    return apiClient
      .post(`/reviews/${type}/${id}/submit`, { project_id: projectId })
      .then(r => r.data)
  },
  decide(type, id, projectId, action, comment = '') {
    return apiClient
      .post(`/reviews/${type}/${id}/review`, { project_id: projectId, action, comment })
      .then(r => r.data)
  },
  listSnapshots(params) {
    return apiClient.get('/reviews/snapshots', { params }).then(r => r.data)
  },
  createSnapshot(payload) {
    return apiClient.post('/reviews/snapshots', payload).then(r => r.data)
  }
}
