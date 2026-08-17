import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useFiltersStore = defineStore('filters', () => {
  const projectIds = ref([])
  const moduleIds = ref([])
  const versionIds = ref([])
  const versionFilterApplied = ref(false)
  const dirPrefix = ref('')
  const projects = ref([])
  const modules = ref([])
  const versions = ref([])

  const fingerprint = computed(() => {
    const projs = [...projectIds.value].sort().join(',')
    const mods = [...moduleIds.value].sort().join(',')
    const vers = [...versionIds.value].sort().join(',')
    return `${projs}|${mods}|${vers}|${dirPrefix.value || ''}`
  })

  function reset() {
    projectIds.value = []
    moduleIds.value = []
    versionIds.value = []
    versionFilterApplied.value = false
    dirPrefix.value = ''
  }

  return {
    projectIds,
    moduleIds,
    versionIds,
    versionFilterApplied,
    dirPrefix,
    projects,
    modules,
    versions,
    fingerprint,
    reset
  }
})
