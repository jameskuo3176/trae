import apiClient from './client'

export const authApi = {
  login(username, password) {
    return apiClient.post('/v1/auth/login', { username, password }).then(r => r.data)
  },

  me() {
    return apiClient.get('/v1/auth/me').then(r => r.data)
  },

  logout() {
    return apiClient.post('/v1/auth/logout').then(r => r.data)
  },

  changePassword(oldPassword, newPassword) {
    return apiClient
      .post('/user/password', { old_password: oldPassword, new_password: newPassword })
      .then(r => r.data)
  },

  getTheme() {
    return apiClient.get('/user/theme').then(r => r.data)
  },

  saveTheme(theme) {
    return apiClient.post('/user/theme', { theme }).then(r => r.data)
  }
}
