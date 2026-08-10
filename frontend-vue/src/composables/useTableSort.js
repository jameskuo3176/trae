import { ref, computed } from 'vue'

export function useTableSort(initialSortKey = null, initialSortOrder = 'asc') {
  const sortKey = ref(initialSortKey)
  const sortOrder = ref(initialSortOrder) // 'asc' | 'desc'

  function sortBy(key) {
    if (sortKey.value === key) {
      // Toggle order
      sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortKey.value = key
      sortOrder.value = 'asc'
    }
  }

  function resetSort() {
    sortKey.value = initialSortKey
    sortOrder.value = initialSortOrder
  }

  function getSortIcon(key) {
    if (sortKey.value !== key) return ''
    return sortOrder.value === 'asc' ? '↑' : '↓'
  }

  function getSortClass(key) {
    return sortKey.value === key ? 'sorted' : ''
  }

  function compareValues(a, b, key) {
    const valA = a?.[key]
    const valB = b?.[key]

    // Handle null/undefined
    if (valA == null && valB == null) return 0
    if (valA == null) return 1
    if (valB == null) return -1

    // Number comparison
    const numA = typeof valA === 'number' ? valA : (typeof valA === 'string' && !isNaN(Number(valA)) ? Number(valA) : null)
    const numB = typeof valB === 'number' ? valB : (typeof valB === 'string' && !isNaN(Number(valB)) ? Number(valB) : null)
    if (numA !== null && numB !== null) {
      return numA - numB
    }

    // Date comparison (ISO strings)
    if (typeof valA === 'string' && typeof valB === 'string') {
      const dateA = Date.parse(valA)
      const dateB = Date.parse(valB)
      if (!isNaN(dateA) && !isNaN(dateB)) {
        return dateA - dateB
      }
    }

    // String comparison (case insensitive)
    const strA = String(valA).toLowerCase()
    const strB = String(valB).toLowerCase()
    if (strA < strB) return -1
    if (strA > strB) return 1
    return 0
  }

  function sortedData(data) {
    if (!sortKey.value || !Array.isArray(data)) return data

    return [...data].sort((a, b) => {
      const comparison = compareValues(a, b, sortKey.value)
      return sortOrder.value === 'asc' ? comparison : -comparison
    })
  }

  return {
    sortKey,
    sortOrder,
    sortBy,
    resetSort,
    getSortIcon,
    getSortClass,
    sortedData: computed(() => sortedData),
    computeSorted: sortedData
  }
}
