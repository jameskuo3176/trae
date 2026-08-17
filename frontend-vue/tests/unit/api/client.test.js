import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import apiClient, { extractErrorMessage } from '@/api/client'

function captureConfig(config) {
  return apiClient.request({
    ...config,
    adapter: requestConfig =>
      Promise.resolve({
        data: {},
        status: 200,
        statusText: 'OK',
        headers: {},
        config: requestConfig
      })
  })
}

describe('API client CSRF contract', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.cookie = 'csrftoken=test-csrf-token-value'
  })

  it.each(['post', 'put', 'patch', 'delete'])(
    'sends X-CSRFToken for same-origin %s',
    async method => {
      const response = await captureConfig({ method, url: '/reviews/group' })
      expect(response.config.headers.get('X-CSRFToken')).toBe('test-csrf-token-value')
    }
  )

  it.each(['get', 'head', 'options'])('does not send X-CSRFToken for %s', async method => {
    const response = await captureConfig({ method, url: '/reviews/group' })
    expect(response.config.headers.get('X-CSRFToken')).toBeUndefined()
  })

  it('does not expose the CSRF token to a cross-origin request', async () => {
    const response = await captureConfig({
      method: 'post',
      url: 'https://example.invalid/reviews/group'
    })
    expect(response.config.headers.get('X-CSRFToken')).toBeUndefined()
  })

  it('extracts common JSON permission error shapes', () => {
    expect(extractErrorMessage({ error: 'forbidden' })).toBe('forbidden')
    expect(extractErrorMessage({ detail: 'Permission denied' })).toBe('Permission denied')
    expect(extractErrorMessage({ non_field_errors: ['Not allowed'] })).toBe('Not allowed')
  })
})
