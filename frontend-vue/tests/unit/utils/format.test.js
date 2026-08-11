import { describe, it, expect } from 'vitest'
import { formatNumber, formatPercent, formatMetric, escapeHtml, truncate } from '@/utils/format'

describe('Format Utils', () => {
  describe('formatNumber', () => {
    it('formats number with default decimals', () => {
      expect(formatNumber(3.1415926)).toBe('3.142')
    })
    it('returns dash for null/undefined', () => {
      expect(formatNumber(null)).toBe('-')
      expect(formatNumber(undefined)).toBe('-')
    })
    it('formats with custom decimals', () => {
      expect(formatNumber(1.234567, 5)).toBe('1.23457')
    })
  })

  describe('formatPercent', () => {
    it('converts decimal to percentage', () => {
      expect(formatPercent(0.856)).toBe('85.60%')
    })
    it('returns dash for null', () => {
      expect(formatPercent(null)).toBe('-')
    })
  })

  describe('formatMetric', () => {
    it('formats with unit', () => {
      expect(formatMetric(1.5, 'ns')).toBe('1.500 ns')
    })
    it('formats without unit', () => {
      expect(formatMetric(2)).toBe('2.000')
    })
    it('returns dash for null', () => {
      expect(formatMetric(null)).toBe('-')
    })
  })

  describe('escapeHtml', () => {
    it('escapes HTML special characters', () => {
      expect(escapeHtml('<script>alert("xss")</script>')).toBe(
        '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
      )
    })
    it('returns empty string for null', () => {
      expect(escapeHtml(null)).toBe('')
    })
  })

  describe('truncate', () => {
    it('truncates long strings', () => {
      expect(truncate('this is a very long string that should be truncated', 20)).toBe(
        'this is a very long ...'
      )
    })
    it('does not truncate short strings', () => {
      expect(truncate('short', 50)).toBe('short')
    })
    it('handles empty string', () => {
      expect(truncate('', 10)).toBe('')
    })
  })
})
