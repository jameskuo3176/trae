export function getCsrfToken() {
  const name = 'csrftoken='
  const decoded = decodeURIComponent(document.cookie)
  const parts = decoded.split(';')
  for (let part of parts) {
    part = part.trim()
    if (part.startsWith(name)) {
      return part.substring(name.length)
    }
  }
  return ''
}

export function readCookie(name) {
  const value = `; ${document.cookie}`
  const parts = value.split(`; ${name}=`)
  if (parts.length === 2) return parts.pop().split(';').shift()
  return null
}