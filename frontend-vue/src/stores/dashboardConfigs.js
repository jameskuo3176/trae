import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { dashboardApi } from '@/api/dashboard'

const LOCAL_KEY = 'qor_dashboard_configs_v2'

export const useDashboardConfigsStore = defineStore('dashboard-configs', () => {
  const configs = ref([])
  const activeId = ref('')
  const loading = ref(false)
  const error = ref('')
  const defaultConfig = computed(() => configs.value.find(config => config.is_default))

  function localConfigs() {
    try {
      return JSON.parse(localStorage.getItem(LOCAL_KEY) || '[]')
    } catch {
      return []
    }
  }

  async function load() {
    loading.value = true
    error.value = ''
    try {
      configs.value = await dashboardApi.listConfigs()
    } catch (requestError) {
      configs.value = localConfigs()
      error.value = 'Server configurations unavailable; using browser storage.'
    } finally {
      loading.value = false
    }
    activeId.value ||= String(defaultConfig.value?.id || configs.value[0]?.id || '')
  }

  async function save(name, payload, isDefault = false) {
    const entry = { id: activeId.value || undefined, name, config: payload, is_default: isDefault }
    try {
      await dashboardApi.saveConfig(entry)
      await load()
    } catch {
      const existing = localConfigs()
      const id = entry.id || `local-${Date.now()}`
      const next = [
        { ...entry, id },
        ...existing.filter(config => String(config.id) !== String(id))
      ]
      if (isDefault)
        next.forEach(config => {
          if (String(config.id) !== String(id)) config.is_default = false
        })
      localStorage.setItem(LOCAL_KEY, JSON.stringify(next))
      configs.value = next
      activeId.value = String(id)
      error.value = 'Saved locally because the server endpoint is unavailable.'
    }
  }

  async function loadConfig(id = activeId.value) {
    if (!id) return null
    const summary = configs.value.find(config => String(config.id) === String(id))
    if (summary?.config) return summary
    if (String(id).startsWith('local-')) return summary || null
    loading.value = true
    error.value = ''
    try {
      const detail = await dashboardApi.getConfig(id)
      configs.value = configs.value.map(config =>
        String(config.id) === String(id) ? { ...config, ...detail } : config
      )
      return detail
    } catch (requestError) {
      error.value = requestError.message || 'Unable to load dashboard configuration.'
      return null
    } finally {
      loading.value = false
    }
  }

  return { configs, activeId, loading, error, defaultConfig, load, loadConfig, save }
})
