import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from '@/api/client'
import { dashboardApi } from '@/api/dashboard'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() }
}))

describe('dashboard API contract', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses Django list and detail routes', async () => {
    apiClient.get
      .mockResolvedValueOnce({ data: [{ id: 7, name: 'Default', is_default: true }] })
      .mockResolvedValueOnce({ data: { id: 7, name: 'Default', config: { height: 500 } } })
    await dashboardApi.listConfigs()
    await dashboardApi.getConfig(7)
    expect(apiClient.get).toHaveBeenNthCalledWith(1, '/dashboard/list')
    expect(apiClient.get).toHaveBeenNthCalledWith(2, '/dashboard/7')
  })

  it('uses the CSRF-protected Django save route', async () => {
    const payload = { name: 'QoR', config: { activeView: 'charts' }, is_default: true }
    apiClient.post.mockResolvedValue({ data: { id: 9 } })
    await dashboardApi.saveConfig(payload)
    expect(apiClient.post).toHaveBeenCalledWith('/dashboard/save', payload)
  })
})
