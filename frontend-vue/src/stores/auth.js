import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore(
  'auth',
  () => {
    const user = ref(null)
    const apiKey = ref(null)
    const mustChangePassword = ref(false)
    const loading = ref(false)
    const error = ref(null)

    const isAuthenticated = computed(() => !!user.value || !!apiKey.value)
    const isAdmin = computed(() => user.value?.is_admin === true)
    const isOwner = computed(() => user.value?.is_owner === true)
    const isViewer = computed(() => user.value?.is_viewer === true)

    const roles = computed(() => {
      if (!user.value) return []
      const r = []
      if (user.value.is_admin) r.push('admin')
      if (user.value.is_owner) r.push('owner')
      if (user.value.is_viewer) r.push('viewer')
      return r
    })

    function hasRole(role) {
      return roles.value.includes(role)
    }

    async function login(username, password) {
      loading.value = true
      error.value = null
      try {
        const data = await authApi.login(username, password)
        apiKey.value = data.api_key
        user.value = data.user
        mustChangePassword.value = data.must_change_password || false
        return data
      } catch (e) {
        error.value = e.response?.data?.error || e.message || '登录失败'
        throw e
      } finally {
        loading.value = false
      }
    }

    async function fetchUser() {
      try {
        const data = await authApi.me()
        user.value = data.user || data
        mustChangePassword.value = data.must_change_password || false
        return data
      } catch {
        user.value = null
        apiKey.value = null
        mustChangePassword.value = false
        return null
      }
    }

    async function logout() {
      user.value = null
      apiKey.value = null
      mustChangePassword.value = false
      try {
        await authApi.logout()
      } catch {
        // Local credentials are cleared even if the server session expired.
      }
    }

    async function changePassword(oldPassword, newPassword) {
      const data = await authApi.changePassword(oldPassword, newPassword)
      mustChangePassword.value = data.must_change_password ?? false
      return data
    }

    async function fetchTheme() {
      try {
        const data = await authApi.getTheme()
        return data
      } catch {
        return null
      }
    }

    async function saveTheme(theme) {
      return await authApi.saveTheme(theme)
    }

    function setUserFromSession(userData) {
      user.value = userData
    }

    function getAuthHeaders() {
      const headers = {}
      if (apiKey.value) {
        headers['X-API-Key'] = apiKey.value
      }
      return headers
    }

    return {
      user,
      apiKey,
      mustChangePassword,
      loading,
      error,
      isAuthenticated,
      isAdmin,
      isOwner,
      isViewer,
      roles,
      hasRole,
      login,
      fetchUser,
      logout,
      changePassword,
      fetchTheme,
      saveTheme,
      setUserFromSession,
      getAuthHeaders
    }
  },
  {
    persist: {
      key: 'qor-auth',
      storage: localStorage,
      pick: ['apiKey', 'user']
    }
  }
)
