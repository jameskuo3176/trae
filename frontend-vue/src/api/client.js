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

const SAFE_METHODS = new Set(['get', 'head', 'options'])

export function isUnsafeSameOriginRequest(config) {
  if (SAFE_METHODS.has((config.method || 'get').toLowerCase())) return false
  try {
    const base = new URL(config.baseURL || '/', window.location.origin)
    return new URL(config.url || '', base).origin === window.location.origin
  } catch {
    return false
  }
}

export function extractErrorMessage(data) {
  if (!data) return ''
  if (typeof data === 'string') return data.trim().startsWith('<') ? '' : data
  const error = data.error
  if (typeof error === 'string') return error
  if (error?.message) return error.message
  if (typeof data.detail === 'string') return data.detail
  if (typeof data.message === 'string') return data.message
  const fieldError = Object.values(data).find(value => typeof value === 'string')
  if (fieldError) return fieldError
  const listError = Object.values(data).find(value => Array.isArray(value) && value.length)
  return listError ? String(listError[0]) : ''
}

apiClient.interceptors.request.use(config => {
  const auth = useAuthStore()
  const headers = auth.getAuthHeaders()
  Object.assign(config.headers, headers)
  const csrfToken = getCsrfToken()
  if (csrfToken && isUnsafeSameOriginRequest(config)) {
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
    const responseData = error.response?.data
    const payload = responseData?.error
    const normalized = new Error(
      extractErrorMessage(responseData) || error.message || 'Request failed'
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
