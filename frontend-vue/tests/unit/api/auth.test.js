import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from '@/api/client'
import { authApi } from '@/api/auth'

vi.mock('@/api/client', () => ({
  default: { post: vi.fn(), get: vi.fn() }
}))

describe('auth API contract', () => {
  beforeEach(() => vi.clearAllMocks())

  it('changes the current user password through the non-admin endpoint', async () => {
    apiClient.post.mockResolvedValue({
      data: { ok: true, must_change_password: false }
    })

    const result = await authApi.changePassword('OldPassword1', 'NewPassword2')

    expect(apiClient.post).toHaveBeenCalledWith('/user/password', {
      old_password: 'OldPassword1',
      new_password: 'NewPassword2'
    })
    expect(result.must_change_password).toBe(false)
  })
})

