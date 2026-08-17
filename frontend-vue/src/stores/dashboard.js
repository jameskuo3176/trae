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
  const pagination = ref(null)
  const diagnostics = ref([])
  const rawReports = ref({})
  const rawLoadingIds = ref(new Set())

  const selectionKey = record => String(record?.__selectionKey ?? record?.id)

  const selectedRecords = computed(() => {
    return records.value.filter(record => selectedIds.value.has(selectionKey(record)))
  })

  const baselineRecord = computed(() => {
    if (!baselineId.value) return null
    return records.value.find(record => selectionKey(record) === baselineId.value) || null
  })

  function setRecords(data) {
    const incoming = data || []
    const idCounts = incoming.reduce((counts, record) => {
      const id = String(record.id)
      counts.set(id, (counts.get(id) || 0) + 1)
      return counts
    }, new Map())
    const usedKeys = new Set()
    records.value = incoming.map((record, index) => {
      const id = String(record.id)
      let key = id
      if (idCounts.get(id) > 1) {
        const scope = record.project_id ?? record.project_name ?? 'record'
        key = `${scope}:${id}`
        if (usedKeys.has(key)) key = `${key}:${index}`
      }
      usedKeys.add(key)
      return { ...record, __selectionKey: key }
    })
    const validIds = new Set(records.value.map(selectionKey))
    selectedIds.value = new Set([...selectedIds.value].filter(id => validIds.has(String(id))))
  }

  function setPagination(value) {
    pagination.value = value
  }

  function setDiagnostics(value) {
    diagnostics.value = value || []
  }

  function setRawReport(id, value) {
    rawReports.value = { ...rawReports.value, [String(id)]: value }
  }

  function setRawLoading(id, value) {
    const next = new Set(rawLoadingIds.value)
    value ? next.add(String(id)) : next.delete(String(id))
    rawLoadingIds.value = next
  }

  function setLoading(val) {
    loading.value = val
  }

  function setError(err) {
    loadError.value = err
  }

  function toggleSelect(id) {
    id = String(id)
    const newSet = new Set(selectedIds.value)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    selectedIds.value = newSet
  }

  function selectAll() {
    selectedIds.value = new Set(records.value.map(selectionKey))
  }

  function clearSelection() {
    selectedIds.value = new Set()
    baselineId.value = null
  }

  function setBaseline(id) {
    baselineId.value = id == null ? null : String(id)
  }

  function selectFirstN(n = 4) {
    const ids = records.value.slice(0, n).map(selectionKey)
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
    pagination.value = null
    diagnostics.value = []
    rawReports.value = {}
    abortController.value?.abort()
  }

  return {
    records,
    loading,
    loadError,
    selectedIds,
    baselineId,
    requestSeq,
    pagination,
    diagnostics,
    rawReports,
    rawLoadingIds,
    selectionKey,
    selectedRecords,
    baselineRecord,
    setRecords,
    setPagination,
    setDiagnostics,
    setRawReport,
    setRawLoading,
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
