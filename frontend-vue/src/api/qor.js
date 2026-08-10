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

  getRecordDetail(recordId) {
    return apiClient.get(`/qor/record/${recordId}/`).then(r => r.data)
  },

  getRunNotes(params) {
    return apiClient.get('/run_notes', { params }).then(r => r.data)
  },

  compare(params) {
    return apiClient.get('/compare', { params }).then(r => r.data)
  }
}