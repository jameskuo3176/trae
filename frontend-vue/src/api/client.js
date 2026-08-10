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
    return Promise.reject(error)
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