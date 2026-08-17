export function getCsrfToken() {
  return readCookie('csrftoken') || ''
}

export function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`
  for (const part of document.cookie.split(';')) {
    const cookie = part.trim()
    if (cookie.startsWith(prefix)) {
      try {
        return decodeURIComponent(cookie.slice(prefix.length))
      } catch {
        return cookie.slice(prefix.length)
      }
    }
  }
  return null
}
