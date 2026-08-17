import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'

vi.mock('@/api/auth', () => ({
  authApi: {
    login: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn(),
    getTheme: vi.fn(),
    saveTheme: vi.fn()
  }
}))

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

  it('getAuthHeaders leaves CSRF handling to the request client', () => {
    const auth = useAuthStore()
    const headers = auth.getAuthHeaders()
    expect(headers['X-CSRFToken']).toBeUndefined()
  })

  it('getAuthHeaders includes API key when set', () => {
    const auth = useAuthStore()
    auth.apiKey = 'qor_test_key_123'
    const headers = auth.getAuthHeaders()
    expect(headers['X-API-Key']).toBe('qor_test_key_123')
  })

  it('restores the user and forced-password state through auth/me', async () => {
    authApi.me.mockResolvedValue({
      user: { id: 1, username: 'admin', is_admin: true },
      must_change_password: true
    })
    const auth = useAuthStore()

    await auth.fetchUser()

    expect(auth.user.username).toBe('admin')
    expect(auth.mustChangePassword).toBe(true)
  })

  it('clears the forced-password state after a successful password change', async () => {
    authApi.changePassword.mockResolvedValue({
      ok: true,
      must_change_password: false
    })
    const auth = useAuthStore()
    auth.mustChangePassword = true

    await auth.changePassword('OldPassword1', 'NewPassword2')

    expect(authApi.changePassword).toHaveBeenCalledWith('OldPassword1', 'NewPassword2')
    expect(auth.mustChangePassword).toBe(false)
  })
})
