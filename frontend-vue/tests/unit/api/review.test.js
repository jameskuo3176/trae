import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from '@/api/client'
import { reviewApi } from '@/api/review'

vi.mock('@/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
}))

describe('weekly review API contract', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads the project week and selects or clears an official star', async () => {
    apiClient.get.mockResolvedValue({ data: { groups: [] } })
    apiClient.post.mockResolvedValue({ data: { ok: true } })
    apiClient.delete.mockResolvedValue({ data: { ok: true, cleared: true } })
    const star = { project_id: 4, module_id: 9, record_id: 12 }
    await reviewApi.weekly({ project_id: 4 })
    await reviewApi.selectStar(star)
    await reviewApi.clearStar(star)
    expect(apiClient.get).toHaveBeenCalledWith('/reviews/weekly', {
      params: { project_id: 4 }
    })
    expect(apiClient.post).toHaveBeenCalledWith('/reviews/weekly/star', star)
    expect(apiClient.delete).toHaveBeenCalledWith('/reviews/weekly/star', { data: star })
  })

  it('uses project review routes rather than subsystem terminology', async () => {
    apiClient.get.mockResolvedValue({ data: { items: [] } })
    apiClient.post.mockResolvedValue({ data: { id: 3 } })
    await reviewApi.list('project', { project_id: 4 })
    await reviewApi.create('project', { project_id: 4 })
    expect(apiClient.get).toHaveBeenCalledWith('/reviews/project', {
      params: { project_id: 4 }
    })
    expect(apiClient.post).toHaveBeenCalledWith('/reviews/project', { project_id: 4 })
  })

  it('uses the shared record risk endpoint for manual judgement', async () => {
    apiClient.put.mockResolvedValue({ data: { data: { rating: 'low' } } })
    apiClient.delete.mockResolvedValue({ data: { data: { rating: 'medium' } } })
    await reviewApi.setRisk(4, 12, 'low')
    await reviewApi.clearRisk(4, 12)
    expect(apiClient.put).toHaveBeenCalledWith('/v2/projects/4/records/12/risk', {
      rating: 'low'
    })
    expect(apiClient.delete).toHaveBeenCalledWith('/v2/projects/4/records/12/risk')
  })

  it('scopes every detail and workflow action by project id', async () => {
    apiClient.get.mockResolvedValue({ data: { id: 1 } })
    apiClient.post.mockResolvedValue({ data: { id: 1 } })
    apiClient.put.mockResolvedValue({ data: { id: 1 } })
    apiClient.delete.mockResolvedValue({ data: { ok: true } })

    await reviewApi.detail('group', 1, 7)
    await reviewApi.update('group', 1, 7, { title: 'Updated' })
    await reviewApi.remove('group', 1, 7)
    await reviewApi.submit('group', 1, 7)
    await reviewApi.decide('group', 1, 7, 'approve', 'Looks good')

    expect(apiClient.get).toHaveBeenCalledWith('/reviews/group/1', {
      params: { project_id: 7 }
    })
    expect(apiClient.put).toHaveBeenCalledWith('/reviews/group/1', {
      project_id: 7,
      title: 'Updated'
    })
    expect(apiClient.delete).toHaveBeenCalledWith('/reviews/group/1', {
      params: { project_id: 7 }
    })
    expect(apiClient.post).toHaveBeenCalledWith('/reviews/group/1/submit', {
      project_id: 7
    })
    expect(apiClient.post).toHaveBeenCalledWith('/reviews/group/1/review', {
      project_id: 7,
      action: 'approve',
      comment: 'Looks good'
    })
  })
})
