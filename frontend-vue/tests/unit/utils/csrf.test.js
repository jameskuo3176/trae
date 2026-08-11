import { describe, it, expect } from 'vitest'
import { getCsrfToken, readCookie } from '@/utils/csrf'

describe('CSRF Utils', () => {
  it('getCsrfToken reads from document.cookie', () => {
    const token = getCsrfToken()
    expect(token).toBe('test-csrf-token-value')
  })

  it('getCsrfToken returns empty string when no cookie', () => {
    const originalCookie = document.cookie
    document.cookie = 'other=value'
    const token = getCsrfToken()
    expect(token).toBe('')
    document.cookie = originalCookie
  })

  it('readCookie returns value for existing key', () => {
    document.cookie = 'key1=value1; key2=value2'
    expect(readCookie('key1')).toBe('value1')
    expect(readCookie('key2')).toBe('value2')
  })

  it('readCookie returns null for missing key', () => {
    expect(readCookie('nonexistent')).toBeNull()
  })
})
