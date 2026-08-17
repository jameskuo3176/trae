import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from '@/api/client'
import { adminApi } from '@/api/admin'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() }
}))

describe('admin release directory API contract', () => {
  beforeEach(() => vi.clearAllMocks())

  it('sends the project identity with the local record id', async () => {
    apiClient.post.mockResolvedValue({ data: { ok: true } })

    await adminApi.updateReleaseDir(1, 22, '/release/new')

    expect(apiClient.post).toHaveBeenCalledWith('/admin/qor/1/release_dir', {
      project_id: 22,
      release_dir: '/release/new'
    })
  })

  it('sends per-item release directories with composite identities', async () => {
    apiClient.post.mockResolvedValue({ data: { ok: true, updated: 2 } })
    const payload = {
      items: [
        { project_id: 10, record_id: 1, release_dir: '/release/alpha' },
        { project_id: 20, record_id: 1, release_dir: '/release/beta' }
      ]
    }

    await adminApi.batchUpdateReleaseDir(payload)

    expect(apiClient.post).toHaveBeenCalledWith(
      '/admin/qor/batch_release_dir',
      payload
    )
  })

  it('loads review hierarchy status through the read-only endpoint', async () => {
    apiClient.get.mockResolvedValue({ data: { validation: { valid: true } } })

    const result = await adminApi.getReviewHierarchyStatus()

    expect(apiClient.get).toHaveBeenCalledWith('/admin/review-hierarchy/status')
    expect(result.validation.valid).toBe(true)
  })

  it('updates a hierarchy module owner through the admin mutation endpoint', async () => {
    const payload = {
      project: 'projectA',
      group: 'groupA',
      module: 'moduleA',
      owner_id: 9,
      config_checksum: 'abc123'
    }
    apiClient.post.mockResolvedValue({ data: { ok: true } })

    await adminApi.updateReviewHierarchyModuleOwner(payload)

    expect(apiClient.post).toHaveBeenCalledWith(
      '/admin/review-hierarchy/module-owner',
      payload
    )
  })
})
