import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

const STORAGE_KEY = 'qor_dc_picker_preferences_v2'
const defaults = {
  sectionIds: [],
  metricIds: [],
  sortMetric: 'WNS',
  showChange: true,
  compactTiming: false,
  onlyWithRaw: false,
  copyOnClick: false,
  pathLinks: true,
  vsMode: false
}

function loadPreferences() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return { ...defaults, ...value, runIds: [] }
  } catch {
    return { ...defaults, runIds: [] }
  }
}

export const useDcComparisonStore = defineStore('dc-comparison', () => {
  const preferences = ref(loadPreferences())
  const draft = ref(null)
  const pickerOpen = ref(false)
  const rawErrors = ref({})
  const visibleCount = computed(
    () => preferences.value.sectionIds.length + preferences.value.metricIds.length
  )

  function open(runIds) {
    draft.value = {
      ...JSON.parse(JSON.stringify(preferences.value)),
      runIds: [...runIds],
      sectionIds: [...preferences.value.sectionIds],
      metricIds: [...preferences.value.metricIds]
    }
    pickerOpen.value = true
  }

  function cancel() {
    draft.value = null
    pickerOpen.value = false
  }

  function apply() {
    if (!draft.value) return
    preferences.value = JSON.parse(JSON.stringify(draft.value))
    pickerOpen.value = false
    draft.value = null
  }

  watch(
    preferences,
    value => {
      try {
        const persistent = { ...value }
        delete persistent.runIds
        localStorage.setItem(STORAGE_KEY, JSON.stringify(persistent))
      } catch {
        // Storage is optional in locked-down intranet browsers.
      }
    },
    { deep: true }
  )

  return { preferences, draft, pickerOpen, rawErrors, visibleCount, open, cancel, apply }
})
