import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useFiltersStore = defineStore('filters', () => {
  const projectId = ref(null)
  const moduleIds = ref([])
  const versionIds = ref([])
  const dirPrefix = ref('')
  const projects = ref([])
  const modules = ref([])
  const versions = ref([])

  const fingerprint = computed(() => {
    const mods = [...moduleIds.value].sort().join(',')
    const vers = [...versionIds.value].sort().join(',')
    return `${projectId.value || ''}|${mods}|${vers}|${dirPrefix.value || ''}`
  })

  function reset() {
    projectId.value = null
    moduleIds.value = []
    versionIds.value = []
    dirPrefix.value = ''
  }

  return {
    projectId,
    moduleIds,
    versionIds,
    dirPrefix,
    projects,
    modules,
    versions,
    fingerprint,
    reset
  }
})
