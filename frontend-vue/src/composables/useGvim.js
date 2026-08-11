import { ref } from 'vue'
import apiClient from '@/api/client'

const SAFE_PATH = /^(?:[a-zA-Z]:[\\/]|\/)[^<>"|?*]+$/

export function useGvim() {
  const opening = ref(false)
  const error = ref('')

  function href(path) {
    const value = String(path || '')
    if ([...value].some(character => character.charCodeAt(0) < 32) || !SAFE_PATH.test(value))
      return null
    return `gvim://open?path=${encodeURIComponent(path)}`
  }

  function open(path) {
    const url = href(path)
    if (!url) return false
    window.location.assign(url)
    return true
  }

  async function openServer(path, line = null) {
    if (!href(path)) throw new Error('Unsafe or unrecognized path')
    opening.value = true
    error.value = ''
    try {
      const response = await apiClient.post('/tools/source-files/gvim', {
        path: String(path),
        ...(line == null ? {} : { line })
      })
      if (response.data?.ok === false) throw new Error(response.data.error || 'Could not open path')
      return response.data
    } catch (requestError) {
      error.value = requestError.message || 'Could not open path'
      throw requestError
    } finally {
      opening.value = false
    }
  }

  function handleClick(event, path, line = null) {
    if (!event.altKey) return true
    event.preventDefault()
    event.stopPropagation()
    openServer(path, line).catch(() => {})
    return false
  }

  return { href, open, openServer, handleClick, opening, error }
}
