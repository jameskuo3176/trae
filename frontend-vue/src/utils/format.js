export function formatNumber(value, decimals = 3) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    return value.toFixed(decimals)
  }
  return String(value)
}

export function formatPercent(value) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    return (value * 100).toFixed(2) + '%'
  }
  return String(value)
}

export function formatMetric(value, unit = '') {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    return value.toFixed(3) + (unit ? ` ${unit}` : '')
  }
  return String(value)
}

export function escapeHtml(str) {
  if (str == null) return ''
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function truncate(str, maxLen = 50) {
  if (!str || str.length <= maxLen) return str || ''
  return str.substring(0, maxLen) + '...'
}