import apiClient from './client'

export const adminApi = {
  createProject(data) {
    return apiClient.post('/admin/projects', data).then(r => r.data)
  },

  deleteProject(id) {
    return apiClient.delete(`/admin/projects/${id}`).then(r => r.data)
  },

  listHiddenProjects() {
    return apiClient.get('/admin/projects/hidden').then(r => r.data)
  },

  restoreProject(id) {
    return apiClient.post(`/admin/projects/${id}/restore`, {}).then(r => r.data)
  },

  hardDeleteProject(id) {
    return apiClient
      .delete(`/admin/projects/${id}/hard_delete`, { data: { confirm: true } })
      .then(r => r.data)
  },

  lockProject(id, reason = '') {
    return apiClient.post(`/admin/projects/${id}/lock`, { reason }).then(r => r.data)
  },

  unlockProject(id) {
    return apiClient.post(`/admin/projects/${id}/unlock`, {}).then(r => r.data)
  },

  createModule(data) {
    return apiClient.post('/admin/modules', data).then(r => r.data)
  },

  deleteModule(id) {
    return apiClient.delete(`/admin/modules/${id}`).then(r => r.data)
  },

  uploadCsv(formData) {
    return apiClient
      .post('/admin/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      .then(r => r.data)
  },

  getRecordOwners(params = {}) {
    return apiClient.get('/admin/records/owners', { params }).then(r => r.data)
  },

  deleteRecord(id, projectId) {
    return apiClient
      .delete(`/admin/records/${id}`, { params: { project_id: projectId } })
      .then(r => r.data)
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

  getReviewHierarchyStatus() {
    return apiClient.get('/admin/review-hierarchy/status').then(r => r.data)
  },

  updateReviewHierarchyModuleOwner(data) {
    return apiClient.post('/admin/review-hierarchy/module-owner', data).then(r => r.data)
  },

  toggleRelease(recordId, projectId) {
    return apiClient
      .post(`/admin/qor/${recordId}/release`, { project_id: projectId })
      .then(r => r.data)
  },

  batchRelease(data) {
    return apiClient.post('/admin/qor/batch_release', data).then(r => r.data)
  },

  batchUpdateReleaseDir(data) {
    return apiClient.post('/admin/qor/batch_release_dir', data).then(r => r.data)
  },

  updateReleaseDir(recordId, projectId, dir) {
    return apiClient
      .post(`/admin/qor/${recordId}/release_dir`, {
        project_id: projectId,
        release_dir: dir
      })
      .then(r => r.data)
  },

  updateVersionDescription(recordId, projectId, desc) {
    return apiClient
      .post(`/admin/qor/${recordId}/description`, {
        project_id: projectId,
        description: desc
      })
      .then(r => r.data)
  },

  getDashboardConfigs() {
    return apiClient.get('/dashboard/list').then(r => r.data)
  },

  saveDashboardConfig(data) {
    return apiClient.post('/dashboard/save', data).then(r => r.data)
  },

  listBackups() {
    return apiClient.get('/admin/backups').then(r => r.data)
  },

  createBackup() {
    return apiClient.post('/admin/backups', {}).then(r => r.data)
  },

  verifyBackups() {
    return apiClient.post('/admin/backups/verify', {}).then(r => r.data)
  }
}
