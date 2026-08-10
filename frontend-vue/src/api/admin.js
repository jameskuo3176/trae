import apiClient from './client'

export const adminApi = {
  createProject(data) {
    return apiClient.post('/admin/projects', data).then(r => r.data)
  },

  deleteProject(id) {
    return apiClient.delete(`/admin/projects/${id}`).then(r => r.data)
  },

  createModule(data) {
    return apiClient.post('/admin/modules', data).then(r => r.data)
  },

  deleteModule(id) {
    return apiClient.delete(`/admin/modules/${id}`).then(r => r.data)
  },

  uploadCsv(formData) {
    return apiClient.post('/admin/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    }).then(r => r.data)
  },

  getRecordOwners() {
    return apiClient.get('/admin/records/owners').then(r => r.data)
  },

  deleteRecord(id) {
    return apiClient.delete(`/admin/records/${id}`).then(r => r.data)
  },

  listUsers() {
    return apiClient.get('/admin/users').then(r => r.data)
  },

  createUser(data) {
    return apiClient.post('/admin/users', data).then(r => r.data)
  },

  resetUserPassword(userId) {
    return apiClient.post(`/admin/users/${userId}/reset-password`).then(r => r.data)
  },

  toggleRelease(recordId) {
    return apiClient.post(`/admin/qor/${recordId}/release`).then(r => r.data)
  },

  batchRelease(data) {
    return apiClient.post('/admin/qor/batch_release', data).then(r => r.data)
  },

  updateReleaseDir(recordId, dir) {
    return apiClient.post(`/admin/qor/${recordId}/release_dir`, { release_dir: dir }).then(r => r.data)
  },

  updateVersionDescription(recordId, desc) {
    return apiClient.post(`/admin/qor/${recordId}/description`, { description: desc }).then(r => r.data)
  },

  getDashboardConfigs() {
    return apiClient.get('/dashboard/list').then(r => r.data)
  },

  saveDashboardConfig(data) {
    return apiClient.post('/dashboard/save', data).then(r => r.data)
  }
}