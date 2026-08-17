import apiClient from './client'

const unwrap = response => response.data?.data ?? response.data

export const annotationsApi = {
  get(projectId, recordId, signal) {
    return apiClient
      .get(`/v2/projects/${projectId}/records/${recordId}/annotation`, { signal })
      .then(unwrap)
  },
  save(projectId, recordId, formData) {
    return apiClient
      .post(`/v2/projects/${projectId}/records/${recordId}/annotation`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      .then(unwrap)
  },
  batch(records, signal) {
    return apiClient.post('/v2/annotations/batch', { records }, { signal }).then(unwrap)
  },
  image(url, signal) {
    return apiClient
      .get(url.replace(/^\/api/, ''), { responseType: 'blob', signal })
      .then(r => r.data)
  }
}
