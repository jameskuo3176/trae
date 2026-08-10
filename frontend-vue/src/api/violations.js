import apiClient from './client'

export const violationsApi = {
  getSummary(params) {
    return apiClient.get('/violations/summary', { params }).then(r => r.data)
  },

  getTimingGroups(params) {
    return apiClient.get('/violations/timing_groups', { params }).then(r => r.data)
  },

  getSourceFiles(params) {
    return apiClient.get('/violations/source_files', { params }).then(r => r.data)
  },

  getList(params) {
    return apiClient.get('/violations', { params }).then(r => r.data)
  },

  diff(params) {
    return apiClient.get('/violations/diff', { params }).then(r => r.data)
  }
}