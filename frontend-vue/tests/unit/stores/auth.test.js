import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

describe('Auth Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('initial state: not authenticated', () => {
    const auth = useAuthStore()
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
    expect(auth.apiKey).toBeNull()
  })

  it('hasRole returns false for unauthenticated user', () => {
    const auth = useAuthStore()
    expect(auth.hasRole('admin')).toBe(false)
    expect(auth.hasRole('viewer')).toBe(false)
  })

  it('setUserFromSession updates user', () => {
    const auth = useAuthStore()
    const userData = {
      id: 1,
      username: 'admin',
      is_admin: true,
      is_owner: false,
      is_release: false,
      is_viewer: false
    }
    auth.setUserFromSession(userData)
    expect(auth.user.username).toBe('admin')
    expect(auth.isAdmin).toBe(true)
    expect(auth.isAuthenticated).toBe(true)
  })

  it('logout clears state', () => {
    const auth = useAuthStore()
    auth.setUserFromSession({ id: 1, username: 'admin', is_admin: true })
    expect(auth.isAuthenticated).toBe(true)
    auth.logout()
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.user).toBeNull()
  })

  it('getAuthHeaders includes CSRF token', () => {
    const auth = useAuthStore()
    const headers = auth.getAuthHeaders()
    expect(headers['X-CSRFToken']).toBe('test-csrf-token-value')
  })

  it('getAuthHeaders includes API key when set', () => {
    const auth = useAuthStore()
    auth.apiKey = 'qor_test_key_123'
    const headers = auth.getAuthHeaders()
    expect(headers['X-API-Key']).toBe('qor_test_key_123')
  })
})
