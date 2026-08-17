import { ref } from 'vue'

const SAFE_PATH = /^(?:[a-zA-Z]:[\\/]|\/)[^<>"|?*]+$/

export function useGvim() {
  const copied = ref(false)
  let copyTimer

  function href(path, line = null) {
    const value = String(path || '')
    if ([...value].some(character => character.charCodeAt(0) < 32) || !SAFE_PATH.test(value))
      return null
    const params = new URLSearchParams({ path: value })
    if (line != null && Number.isInteger(Number(line)) && Number(line) > 0) {
      params.set('line', String(Number(line)))
    }
    return `gvim://open?${params.toString()}`
  }

  function open(path, line = null) {
    const url = href(path, line)
    if (!url) return false
    window.location.assign(url)
    return true
  }

  async function copy(path) {
    const value = String(path || '')
    if (!value) return false
    copied.value = true
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = value
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        textarea.remove()
      }
    } catch (error) {
      copied.value = false
      throw error
    }
    window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => {
      copied.value = false
    }, 1400)
    return true
  }

  return { href, open, copy, copied }
}
