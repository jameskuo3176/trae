import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useFiltersStore = defineStore('filters', () => {
  const projectIds = ref([])
  const ownerIds = ref([])
  const moduleIds = ref([])
  const versionIds = ref([])
  const versionFilterApplied = ref(false)
  const dirPrefix = ref('')
  const projects = ref([])
  const modules = ref([])
  const versions = ref([])
  /** When true, filter fingerprint watchers skip reload (config apply owns the load). */
  const suppressReactiveReload = ref(false)

  const fingerprint = computed(() => {
    const projs = [...projectIds.value].sort().join(',')
    const owners = [...ownerIds.value].sort().join(',')
    const mods = [...moduleIds.value].sort().join(',')
    const vers = [...versionIds.value].sort().join(',')
    return `${projs}|${owners}|${mods}|${vers}|${dirPrefix.value || ''}`
  })

  function reset() {
    projectIds.value = []
    ownerIds.value = []
    moduleIds.value = []
    versionIds.value = []
    versionFilterApplied.value = false
    dirPrefix.value = ''
    suppressReactiveReload.value = false
  }

  return {
    projectIds,
    ownerIds,
    moduleIds,
    versionIds,
    versionFilterApplied,
    dirPrefix,
    projects,
    modules,
    versions,
    suppressReactiveReload,
    fingerprint,
    reset
  }
})
