import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useDashboardStore = defineStore('dashboard', () => {
  const records = ref([])
  const loading = ref(false)
  const loadError = ref(null)
  const selectedIds = ref(new Set())
  const baselineId = ref(null)
  const requestSeq = ref(0)
  const abortController = ref(null)

  const selectedRecords = computed(() => {
    return records.value.filter(r => selectedIds.value.has(r.id))
  })

  const baselineRecord = computed(() => {
    if (!baselineId.value) return null
    return records.value.find(r => r.id === baselineId.value) || null
  })

  function setRecords(data) {
    records.value = data || []
  }

  function setLoading(val) {
    loading.value = val
  }

  function setError(err) {
    loadError.value = err
  }

  function toggleSelect(id) {
    const newSet = new Set(selectedIds.value)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    selectedIds.value = newSet
  }

  function selectAll() {
    selectedIds.value = new Set(records.value.map(r => r.id))
  }

  function clearSelection() {
    selectedIds.value = new Set()
    baselineId.value = null
  }

  function setBaseline(id) {
    baselineId.value = id
  }

  function selectFirstN(n = 4) {
    const ids = records.value.slice(0, n).map(r => r.id)
    selectedIds.value = new Set(ids)
    if (ids.length > 0) {
      baselineId.value = ids[0]
    }
  }

  function startRequest() {
    if (abortController.value) {
      abortController.value.abort()
    }
    abortController.value = new AbortController()
    return {
      seq: ++requestSeq.value,
      signal: abortController.value.signal
    }
  }

  function isRequestValid(seq) {
    return seq === requestSeq.value
  }

  function reset() {
    records.value = []
    selectedIds.value = new Set()
    baselineId.value = null
    loadError.value = null
  }

  return {
    records,
    loading,
    loadError,
    selectedIds,
    baselineId,
    requestSeq,
    selectedRecords,
    baselineRecord,
    setRecords,
    setLoading,
    setError,
    toggleSelect,
    selectAll,
    clearSelection,
    setBaseline,
    selectFirstN,
    startRequest,
    isRequestValid,
    reset
  }
})