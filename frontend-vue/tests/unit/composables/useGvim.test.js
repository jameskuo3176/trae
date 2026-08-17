import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGvim } from '@/composables/useGvim'

describe('useGvim', () => {
  beforeEach(() => vi.clearAllMocks())

  it('builds protocol links only for safe absolute paths', () => {
    const gvim = useGvim()
    expect(gvim.href('/workspace/regr_a/main/report.rpt', 42)).toBe(
      'gvim://open?path=%2Fworkspace%2Fregr_a%2Fmain%2Freport.rpt&line=42'
    )
    expect(gvim.href('D:\\runs\\top.v')).toBe('gvim://open?path=D%3A%5Cruns%5Ctop.v')
    expect(gvim.href('relative/report.rpt')).toBeNull()
    expect(gvim.href('/workspace/bad?.rpt')).toBeNull()
  })

  it('copies the source path as the client fallback', async () => {
    const writeText = vi.fn().mockResolvedValue()
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText }
    })
    const gvim = useGvim()
    await expect(gvim.copy('/workspace/report.rpt')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('/workspace/report.rpt')
    expect(gvim.copied.value).toBe(true)
  })
})
