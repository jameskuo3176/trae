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

  const compositeModuleIds = computed(() => {
    return moduleIds.value.map(mid => {
      const mod = modules.value.find(m => m.id === parseInt(mid))
      if (mod && mod.project_id) {
        return `${mod.project_id}:${mid}`
      }
      return mid
    })
  })

  const fingerprint = computed(() => {
    const mods = [...moduleIds.value].sort().join(',')
    const vers = [...versionIds.value].sort().join(',')
    return `${projectId.value || ''}|${mods}|${vers}|${dirPrefix.value || ''}`
  })

  function parseModuleValue(val) {
    const s = String(val)
    const idx = s.indexOf(':')
    if (idx > 0) {
      return { projectId: s.substring(0, idx), moduleId: s.substring(idx + 1) }
    }
    return { projectId: null, moduleId: s }
  }

  function resolveProjectIdsForModules(moduleValues) {
    const ids = new Set()
    moduleValues.forEach(v => {
      const parsed = parseModuleValue(v)
      if (parsed.projectId) ids.add(parsed.projectId)
    })
    return Array.from(ids)
  }

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
    compositeModuleIds,
    fingerprint,
    parseModuleValue,
    resolveProjectIdsForModules,
    reset
  }
})