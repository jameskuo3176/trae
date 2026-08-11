import { beforeEach, describe, expect, it, vi } from 'vitest'
import apiClient from '@/api/client'
import { useGvim } from '@/composables/useGvim'

vi.mock('@/api/client', () => ({
  default: { post: vi.fn() }
}))

describe('useGvim', () => {
  beforeEach(() => vi.clearAllMocks())

  it('builds protocol links only for safe absolute paths', () => {
    const gvim = useGvim()
    expect(gvim.href('/workspace/regr_a/main/report.rpt')).toMatch(/^gvim:\/\//)
    expect(gvim.href('relative/report.rpt')).toBeNull()
    expect(gvim.href('/workspace/bad?.rpt')).toBeNull()
  })

  it('uses the authenticated server fallback on Alt+click', async () => {
    apiClient.post.mockResolvedValue({ data: { ok: true, message: 'opened' } })
    const gvim = useGvim()
    const event = { altKey: true, preventDefault: vi.fn(), stopPropagation: vi.fn() }
    expect(gvim.handleClick(event, '/workspace/report.rpt')).toBe(false)
    await vi.waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith('/tools/source-files/gvim', {
        path: '/workspace/report.rpt'
      })
    )
    expect(event.preventDefault).toHaveBeenCalled()
  })
})
