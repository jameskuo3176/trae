import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { useDcComparisonStore } from '@/stores/dcComparison'
import { useDashboardData } from '@/composables/useDashboardData'

const SETTINGS_DEFAULTS = {
  orientation: 'vertical',
  height: 500,
  labelMode: 'both',
  chartType: 'bar',
  tableWidth: 0,
  tableFontSize: 12,
  activeView: 'charts'
}

function asStringList(value) {
  if (value == null || value === '') return []
  if (Array.isArray(value)) return value.map(item => String(item))
  return [String(value)]
}

function extractSettings(payload = {}) {
  return {
    orientation: payload.orientation ?? SETTINGS_DEFAULTS.orientation,
    height: Number(payload.height ?? payload.chartHeight ?? SETTINGS_DEFAULTS.height) || 500,
    labelMode: payload.labelMode ?? SETTINGS_DEFAULTS.labelMode,
    chartType: payload.chartType ?? SETTINGS_DEFAULTS.chartType,
    tableWidth: Number(payload.tableWidth ?? SETTINGS_DEFAULTS.tableWidth) || 0,
    tableFontSize: Number(payload.tableFontSize ?? SETTINGS_DEFAULTS.tableFontSize) || 12,
    activeView: payload.activeView ?? SETTINGS_DEFAULTS.activeView
  }
}

function extractFilters(payload = {}) {
  const projectIds = asStringList(
    payload.projectIds ?? payload.projects ?? (payload.project != null ? [payload.project] : [])
  )
  const moduleIds = asStringList(payload.moduleIds ?? payload.modules)
  const versionIds = asStringList(payload.versionIds ?? payload.versions ?? payload.version)
  return {
    projectIds,
    moduleIds,
    versionIds,
    dirPrefix: payload.dirPrefix != null ? String(payload.dirPrefix) : '',
    versionFilterApplied: Boolean(
      payload.versionFilterApplied ?? (versionIds.length > 0 && payload.versions != null)
    )
  }
}

function hasFilterKeys(payload = {}) {
  return [
    'projectIds',
    'projects',
    'project',
    'moduleIds',
    'modules',
    'versionIds',
    'versions',
    'version',
    'dirPrefix',
    'versionFilterApplied'
  ].some(key => Object.prototype.hasOwnProperty.call(payload, key))
}

/**
 * Snapshot / restore dashboard presentation + filter + selection state for saved configs.
 */
export function useDashboardConfigState() {
  const filters = useFiltersStore()
  const dashboard = useDashboardStore()
  const dc = useDcComparisonStore()
  const { loadModules, loadVersions, loadDashboardData } = useDashboardData()

  function snapshot(settings) {
    const prefs = { ...dc.preferences }
    delete prefs.runIds
    return {
      ...extractSettings(settings),
      projectIds: [...filters.projectIds].map(String),
      moduleIds: [...filters.moduleIds].map(String),
      versionIds: [...filters.versionIds].map(String),
      dirPrefix: filters.dirPrefix || '',
      versionFilterApplied: Boolean(filters.versionFilterApplied),
      selectedIds: [...dashboard.selectedIds].map(String),
      baselineId: dashboard.baselineId == null ? null : String(dashboard.baselineId),
      dcPreferences: prefs
    }
  }

  async function apply(payload, settingsTarget) {
    if (!payload || typeof payload !== 'object') return null

    filters.suppressReactiveReload = true
    try {
      const nextSettings = extractSettings(payload)
      Object.assign(settingsTarget, nextSettings)

      const shouldApplyFilters = hasFilterKeys(payload)
      if (shouldApplyFilters) {
        const nextFilters = extractFilters(payload)
        filters.projectIds = nextFilters.projectIds
        filters.moduleIds = nextFilters.moduleIds
        filters.versionIds = nextFilters.versionIds
        filters.dirPrefix = nextFilters.dirPrefix
        filters.versionFilterApplied = nextFilters.versionFilterApplied
      }

      if (payload.dcPreferences && typeof payload.dcPreferences === 'object') {
        dc.preferences = {
          ...dc.preferences,
          ...payload.dcPreferences,
          runIds: []
        }
      }

      if (shouldApplyFilters) {
        await Promise.all([loadModules(), loadVersions()])
      }

      const hasSelection = Object.prototype.hasOwnProperty.call(payload, 'selectedIds')
      await loadDashboardData({
        selectedIds: hasSelection ? asStringList(payload.selectedIds) : [],
        baselineId: payload.baselineId == null ? null : String(payload.baselineId),
        preserveSelection: hasSelection
      })
      return nextSettings
    } finally {
      filters.suppressReactiveReload = false
    }
  }

  return { snapshot, apply, extractSettings, SETTINGS_DEFAULTS }
}
