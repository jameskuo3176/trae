import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { getCsrfToken } from '@/utils/csrf'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  },
  withCredentials: true
})

apiClient.interceptors.request.use(config => {
  const auth = useAuthStore()
  const headers = auth.getAuthHeaders()
  Object.assign(config.headers, headers)
  const csrfToken = getCsrfToken()
  if (csrfToken && !['get', 'head', 'options'].includes(config.method?.toLowerCase())) {
    config.headers['X-CSRFToken'] = csrfToken
  }
  return config
})

apiClient.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      const auth = useAuthStore()
      if (auth.isAuthenticated && !error.config?.url?.includes('/auth/')) {
        auth.logout()
        window.location.href = '/login'
      }
    }
    const payload = error.response?.data?.error
    const normalized = new Error(
      payload?.message || error.response?.data?.message || error.message || 'Request failed'
    )
    normalized.code = payload?.code || error.code
    normalized.status = error.response?.status
    normalized.details = payload?.details || {}
    normalized.cause = error
    if (error.name === 'CanceledError' || error.code === 'ERR_CANCELED') {
      normalized.name = 'CanceledError'
      normalized.code = 'ERR_CANCELED'
    }
    return Promise.reject(normalized)
  }
)

export function createRequestController() {
  const controller = new AbortController()
  return {
    signal: controller.signal,
    abort: () => controller.abort()
  }
}

export default apiClient
