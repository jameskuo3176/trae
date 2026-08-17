<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useDcComparisonStore } from '@/stores/dcComparison'
import { useRunLabelContext } from '@/composables/useChartPresentation'
import { dashboardApi } from '@/api/dashboard'
import { normalizeTimingSections } from '@/utils/timing'
import { useTimingAnalysis } from '@/composables/useTimingAnalysis'
import DataTable from '@/components/common/DataTable.vue'
import SourceFileLink from '@/components/common/SourceFileLink.vue'
import DcComparisonPicker from './DcComparisonPicker.vue'

const dashboard = useDashboardStore()
const dc = useDcComparisonStore()
const { runLabel } = useRunLabelContext()
const navWidth = ref(Number(localStorage.getItem('dcNavWidth')) || 236)
const vsDraftIds = ref(new Set())
const rawControllers = new Map()

const canonicalSections = [
  {
    id: 'qor_timing',
    label: 'Timing',
    metrics: [
      { id: 'wns_setup', label: 'Setup WNS', aliases: ['wns'] },
      { id: 'tns_setup', label: 'Setup TNS', aliases: ['tns'] },
      { id: 'nvp_setup', label: 'Setup NVP', aliases: ['nvp'] },
      { id: 'wns_hold', label: 'Hold WNS' },
      { id: 'tns_hold', label: 'Hold TNS' },
      { id: 'nvp_hold', label: 'Hold NVP' },
      { id: 'target_frequency', label: 'Target frequency' },
      { id: 'achieved_frequency', label: 'Achieved frequency' }
    ]
  },
  {
    id: 'qor_area_count',
    label: 'Area / Count',
    metrics: [
      { id: 'area_total', label: 'Total area' },
      { id: 'area_combinational', label: 'Combinational area' },
      { id: 'area_sequential', label: 'Sequential area' },
      { id: 'area_macro', label: 'Macro area' },
      { id: 'cell_count', label: 'Cell count' },
      { id: 'instance_count', label: 'Instance count' },
      { id: 'net_count', label: 'Net count' },
      { id: 'register_count', label: 'Register count' }
    ]
  },
  {
    id: 'qor_power',
    label: 'Power',
    metrics: [
      { id: 'power_internal', label: 'Internal power' },
      { id: 'power_switching', label: 'Switching power' },
      { id: 'power_leakage', label: 'Leakage power' },
      { id: 'power_total', label: 'Total power' }
    ]
  },
  {
    id: 'qor_physical',
    label: 'Physical',
    metrics: [
      { id: 'utilization', label: 'Utilization' },
      { id: 'mbb_ratio', label: 'MBB ratio' },
      { id: 'clock_gating_ratio', label: 'Clock gating' },
      { id: 'congestion_h', label: 'Congestion horizontal' },
      { id: 'congestion_v', label: 'Congestion vertical' },
      { id: 'congestion_b', label: 'Congestion combined', aliases: ['congestion'] }
    ]
  }
]

const records = computed(() => dashboard.records)
const selected = computed(() => dashboard.selectedRecords)
const recordKey = record => dashboard.selectionKey(record)
const rawSelected = computed(() =>
  dashboard.selectedRecords.filter(record => dashboard.rawReports[recordKey(record)])
)
const timingScopes = computed(() => {
  const scenarios = new Set()
  const pathGroups = new Set()
  rawSelected.value.forEach(record => {
    const sections = normalizeTimingSections({
      raw_dc_report: normalizedRaw(record)
    })
    Object.values(sections).forEach(analysis => {
      Object.entries(analysis).forEach(([scenario, groups]) => {
        scenarios.add(scenario)
        Object.keys(groups).forEach(group => pathGroups.add(group))
      })
    })
  })
  return {
    scenarios: [...scenarios].sort(),
    pathGroups: [...pathGroups].sort()
  }
})
const timingRecords = computed(() =>
  selected.value.map(record => ({
    ...record,
    raw_dc_report: normalizedRaw(record)
  }))
)
const { computedMetrics: scopedTimingMetrics, groupDetails: scopedTimingGroups } = useTimingAnalysis(
  () => timingRecords.value,
  {
    selectedScenarios: computed({
      get: () => dc.preferences.scenarioIds,
      set: value => {
        dc.preferences.scenarioIds = value
      }
    }),
    selectedPathGroups: computed({
      get: () => dc.preferences.pathGroupIds,
      set: value => {
        dc.preferences.pathGroupIds = value
      }
    })
  }
)
const scopedTimingByRun = computed(
  () =>
    new Map(
      scopedTimingMetrics.value.map(item => [
        recordKey(item.record),
        {
          wns_setup: item.wns,
          tns_setup: item.tns,
          nvp_setup: item.nvp,
          aggregateAnalyses: item.aggregateAnalyses
        }
      ])
    )
)
const timingGroupsByRun = computed(
  () =>
    new Map(
      scopedTimingGroups.value.map(item => [
        recordKey(item.record),
        new Map(
          item.groups.map(group => [
            `${group.analysis}\u0000${group.scenario}\u0000${group.pathGroup}`,
            group
          ])
        )
      ])
    )
)
const timingHierarchy = computed(() => {
  const analyses = new Map()
  scopedTimingGroups.value.forEach(item => {
    item.groups.forEach(group => {
      if (!analyses.has(group.analysis)) analyses.set(group.analysis, new Map())
      const scenarios = analyses.get(group.analysis)
      if (!scenarios.has(group.scenario)) scenarios.set(group.scenario, new Set())
      scenarios.get(group.scenario).add(group.pathGroup)
    })
  })
  return [...analyses.entries()]
    .sort(([left], [right]) => {
      if (left === 'default') return -1
      if (right === 'default') return 1
      return left.localeCompare(right)
    })
    .map(([analysis, scenarios]) => ({
      analysis,
      scenarios: [...scenarios.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([scenario, groups]) => ({ scenario, groups: [...groups].sort() }))
    }))
})
const activeSelection = computed(() =>
  dc.preferences.vsMode ? vsDraftIds.value : dashboard.selectedIds
)

function normalizedRaw(record) {
  const raw = dashboard.rawReports[recordKey(record)]
  if (!raw) return {}
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

const rawSections = computed(() => {
  const result = new Map()
  rawSelected.value.forEach(record => {
    Object.entries(normalizedRaw(record)).forEach(([id, value]) => {
      if (id === 'metadata' || !value || typeof value !== 'object') return
      const metrics = Array.isArray(value)
        ? [...new Set(value.flatMap(item => Object.keys(item || {})))]
        : Object.keys(value)
      if (!result.has(id))
        result.set(id, { id, label: id.replaceAll('_', ' '), metrics: new Set() })
      metrics.forEach(metric => result.get(id).metrics.add(metric))
    })
  })
  return [...result.values()].map(section => ({ ...section, metrics: [...section.metrics] }))
})

const pickerSections = computed(() => [
  ...canonicalSections.map(section => ({
    ...section,
    metrics: section.metrics.map(metric => ({ id: metric.id, label: metric.label }))
  })),
  ...rawSections.value
])

const visibleRawSections = computed(() => {
  const configured = dc.preferences.sectionIds
  return rawSections.value.filter(
    section => !dc.preferences.catalogConfigured || configured.includes(section.id)
  )
})

const visibleCanonicalSections = computed(() => {
  const configured = dc.preferences.sectionIds
  return canonicalSections
    .filter(section => !dc.preferences.catalogConfigured || configured.includes(section.id))
    .map(section => ({
      ...section,
      metrics: section.metrics.filter(metric => {
        if (dc.preferences.compactTiming && section.id === 'qor_timing') {
          return /wns|tns|nvp/.test(metric.id)
        }
        return (
          !dc.preferences.catalogConfigured ||
          dc.preferences.metricIds.includes(`${section.id}.${metric.id}`)
        )
      })
    }))
    .filter(section => section.metrics.length)
})

function hasTimingSections(record) {
  return Object.keys(normalizeTimingSections({ raw_dc_report: normalizedRaw(record) })).length > 0
}

function canonicalValue(record, metric, sectionId = '') {
  if (
    sectionId === 'qor_timing' &&
    ['wns_setup', 'tns_setup', 'nvp_setup'].includes(metric.id) &&
    hasTimingSections(record)
  ) {
    return scopedTimingByRun.value.get(recordKey(record))?.[metric.id] ?? null
  }
  for (const key of [metric.id, ...(metric.aliases || [])]) {
    const value = record?.[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function formatCanonicalValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(2) : value
}

function canonicalChangeClass(section, metric, currentValue, record) {
  if (!dc.preferences.showChange || recordKey(record) === dashboard.baselineId) return ''
  const baseValue = canonicalValue(dashboard.baselineRecord, metric, section.id)
  const current = Number(currentValue)
  const base = Number(baseValue)
  if (!Number.isFinite(current) || !Number.isFinite(base) || current === base) return ''
  const higherIsBetter =
    /wns|tns|frequency|utilization|gating/.test(metric.id) && !/target_frequency/.test(metric.id)
  const better = higherIsBetter ? current > base : current < base
  return better ? 'change-better' : 'change-worse'
}

function canonicalRows(section) {
  return section.metrics.map(metric => {
    const row = { id: metric.id, metric: metric.label, __classes: {} }
    selected.value.forEach(record => {
      const key = recordKey(record)
      const value = canonicalValue(record, metric, section.id)
      row[key] = value
      row.__classes[key] = canonicalChangeClass(section, metric, value, record)
    })
    return row
  })
}

function timingGroup(record, analysis, scenario, pathGroup) {
  return timingGroupsByRun.value
    .get(recordKey(record))
    ?.get(`${analysis}\u0000${scenario}\u0000${pathGroup}`)
}

function formatTimingPart(value) {
  return value == null ? '—' : Number(value).toFixed(2)
}

function timingAnalysisContributes(record, analysis) {
  return scopedTimingByRun.value.get(recordKey(record))?.aggregateAnalyses?.includes(analysis)
}

function canonicalColumns() {
  return [
    { key: 'metric', label: 'QoR metric', width: '190px', sortable: false },
    ...selected.value.map(record => ({
      key: recordKey(record),
      label: runLabel(record),
      numeric: true,
      format: formatCanonicalValue,
      sortValue: row => numericValue(row[recordKey(record)]) ?? row[recordKey(record)],
      class: row => [
        dashboard.baselineId === recordKey(record) ? 'baseline' : '',
        row.__classes?.[recordKey(record)] || ''
      ]
    }))
  ]
}

function sectionRows(section) {
  return section.metrics
    .filter(metric => {
      if (dc.preferences.compactTiming && section.id.toLowerCase().includes('timing')) {
        return /wns|tns|nvp/i.test(metric)
      }
      return (
        !dc.preferences.metricIds.length ||
        dc.preferences.metricIds.includes(`${section.id}.${metric}`)
      )
    })
    .map(metric => {
      const row = { id: metric, metric, __classes: {} }
      selected.value.forEach(record => {
        const key = recordKey(record)
        const data = normalizedRaw(record)[section.id]
        row[key] = Array.isArray(data)
          ? data
              .map(item => item?.[metric])
              .filter(value => value != null)
              .join(' / ')
          : data?.[metric]
        row.__classes[key] = changeClass(section.id, metric, row[key], record)
      })
      return row
    })
}

function numericValue(value) {
  const index = { WNS: 0, TNS: 1, NVP: 2 }[dc.preferences.sortMetric] ?? 0
  const part = String(value ?? '')
    .split('/')
    [index]?.trim()
  const number = Number(part?.replace(/[%,$]/g, ''))
  return Number.isFinite(number) ? number : null
}

function changeClass(sectionId, metric, currentValue, record) {
  if (!dc.preferences.showChange || recordKey(record) === dashboard.baselineId) return ''
  const baseline = dashboard.baselineRecord
  if (!baseline) return ''
  const baselineData = normalizedRaw(baseline)[sectionId]
  const baselineValue = Array.isArray(baselineData)
    ? baselineData
        .map(item => item?.[metric])
        .filter(value => value != null)
        .join(' / ')
    : baselineData?.[metric]
  const current = numericValue(currentValue)
  const base = numericValue(baselineValue)
  if (current == null || base == null || current === base) return ''
  const name = `${sectionId}.${metric}`.toLowerCase()
  const higherIsBetter = /wns|tns|slack|gating|utilization|coverage/.test(name)
  const better = higherIsBetter ? current > base : current < base
  return better ? 'change-better' : 'change-worse'
}

function sectionColumns() {
  return [
    { key: 'metric', label: 'Metric', width: '180px' },
    ...selected.value.map(record => ({
      key: recordKey(record),
      label: runLabel(record),
      numeric: true,
      sortValue: row => numericValue(row[recordKey(record)]) ?? row[recordKey(record)],
      class: row => [
        dashboard.baselineId === recordKey(record) ? 'baseline' : '',
        row.__classes?.[recordKey(record)] || ''
      ]
    }))
  ]
}

async function ensureRaw(record) {
  const key = recordKey(record)
  if (dashboard.rawReports[key] || dashboard.rawLoadingIds.has(key)) return
  const controller = new AbortController()
  rawControllers.set(key, controller)
  dashboard.setRawLoading(key, true)
  try {
    const raw = await dashboardApi.rawReport(record.project_id, record.id, controller.signal)
    dashboard.setRawReport(key, raw)
  } catch (error) {
    if (error.code !== 'ERR_CANCELED') dc.rawErrors = { ...dc.rawErrors, [key]: error.message }
  } finally {
    dashboard.setRawLoading(key, false)
    rawControllers.delete(key)
  }
}

function toggle(record) {
  const id = recordKey(record)
  if (dc.preferences.vsMode) {
    const next = new Set(vsDraftIds.value)
    next.has(id) ? next.delete(id) : next.add(id)
    vsDraftIds.value = next
    if (next.has(id)) ensureRaw(record)
    return
  }
  dashboard.toggleSelect(id)
  if (dashboard.selectedIds.has(id)) ensureRaw(record)
}
function selectAllRuns() {
  dashboard.selectAll()
  dashboard.selectedRecords.forEach(ensureRaw)
}

function openPicker() {
  dc.open([...dashboard.selectedIds])
  if (!dc.preferences.catalogConfigured) {
    dc.draft.sectionIds = pickerSections.value.map(section => section.id)
    dc.draft.metricIds = pickerSections.value.flatMap(section =>
      section.metrics.map(metric => `${section.id}.${metric.id || metric}`)
    )
  }
}

function applyVsSelection() {
  dashboard.selectedIds = new Set(vsDraftIds.value)
  dashboard.selectedRecords.forEach(ensureRaw)
  dc.preferences.vsMode = false
}

function cancelVsSelection() {
  vsDraftIds.value = new Set(dashboard.selectedIds)
  dc.preferences.vsMode = false
}

function startResize(event) {
  const start = event.clientX
  const width = navWidth.value
  const move = moveEvent => {
    navWidth.value = Math.max(170, Math.min(420, width + moveEvent.clientX - start))
  }
  const stop = () => {
    localStorage.setItem('dcNavWidth', String(navWidth.value))
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', stop)
  }
  document.addEventListener('mousemove', move)
  document.addEventListener('mouseup', stop)
}

watch(
  () => dc.applyVersion,
  () => {
    const ids = dc.preferences.runIds
    dashboard.selectedIds = new Set(ids.map(String))
    dashboard.selectedRecords.forEach(ensureRaw)
    if (dc.preferences.vsMode) vsDraftIds.value = new Set(dashboard.selectedIds)
  }
)
watch(
  () => dashboard.selectedRecords.map(recordKey).join('|'),
  () => dashboard.selectedRecords.forEach(ensureRaw),
  { immediate: true }
)
watch(
  () => dc.preferences.vsMode,
  enabled => {
    if (enabled) vsDraftIds.value = new Set(dashboard.selectedIds)
  }
)
onBeforeUnmount(() => rawControllers.forEach(controller => controller.abort()))
defineExpose({ sectionRows, sectionColumns, vsDraftIds, applyVsSelection, cancelVsSelection })
</script>

<template>
  <section class="dc-shell" aria-labelledby="dc-heading">
    <aside class="dc-nav" :style="{ width: `${navWidth}px` }">
      <header>
        <strong id="dc-heading">QoR comparison</strong
        ><span>{{ selected.length }} selected · {{ rawSelected.length }} raw</span>
      </header>
      <div class="nav-actions">
        <button class="btn btn-sm btn-default" type="button" @click="selectAllRuns">All</button>
        <button class="btn btn-sm btn-default" type="button" @click="dashboard.clearSelection">
          Clear
        </button>
      </div>
      <label
        v-for="record in records"
        :key="recordKey(record)"
        class="run-item"
        :class="{
          selected: activeSelection.has(recordKey(record)),
          'vs-selected': dc.preferences.vsMode && vsDraftIds.has(recordKey(record))
        }"
      >
        <input
          type="checkbox"
          :checked="activeSelection.has(recordKey(record))"
          @change="toggle(record)"
        />
        <span
          ><b>{{ record.module_name || 'Module' }}</b
          ><small>{{ record.version || record.tag }} · {{ record.full_dir }}</small></span
        >
        <button
          type="button"
          class="baseline-button"
          :aria-pressed="dashboard.baselineId === recordKey(record)"
          title="Set baseline"
          @click.prevent="dashboard.setBaseline(recordKey(record))"
        >
          B
        </button>
      </label>
    </aside>
    <div
      class="resize"
      role="separator"
      aria-orientation="vertical"
      tabindex="0"
      @mousedown.prevent="startResize"
    />
    <div class="dc-content">
      <div class="dc-toolbar">
        <div>
          <strong>Run × metric instrument</strong
          ><small>Baseline: {{ dashboard.baselineRecord?.version || 'not set' }}</small>
        </div>
        <div class="toolbar-actions">
          <span v-if="dc.preferences.vsMode" class="vs-status" aria-live="polite">
            VS draft: {{ vsDraftIds.size }} run(s)
          </span>
          <button
            v-if="dc.preferences.vsMode"
            class="btn btn-sm btn-default"
            type="button"
            @click="cancelVsSelection"
          >
            Cancel VS
          </button>
          <button
            v-if="dc.preferences.vsMode"
            class="btn btn-sm"
            type="button"
            @click="applyVsSelection"
          >
            Apply VS
          </button>
          <button class="picker-button" type="button" aria-haspopup="dialog" @click="openPicker">
            # <span>{{ dc.visibleCount || 'all' }}</span>
          </button>
        </div>
      </div>
      <div v-if="!dashboard.selectedIds.size" class="empty-state">
        Select runs from the checklist to compare canonical QoR metrics.
      </div>
      <template v-if="dashboard.selectedIds.size">
        <article
          v-for="section in visibleCanonicalSections"
          :key="section.id"
          class="dc-section canonical-section"
        >
          <h3>{{ section.label }}</h3>
          <DataTable
            :rows="canonicalRows(section)"
            :columns="canonicalColumns()"
            row-key="id"
            :copy-on-click="dc.preferences.copyOnClick"
            :filename="`${section.id}.csv`"
          />
          <details
            v-if="section.id === 'qor_timing' && timingHierarchy.length"
            class="timing-breakdown"
            :open="!dc.preferences.compactTiming"
          >
            <summary>
              <span>Scenario → path-group contributions</span>
              <small>WNS minimum · negative TNS sum · NVP total</small>
            </summary>
            <section
              v-for="analysis in timingHierarchy"
              :key="analysis.analysis"
              class="timing-analysis"
            >
              <h4>
                {{ analysis.analysis }}
                <span
                  v-if="selected.some(record => timingAnalysisContributes(record, analysis.analysis))"
                  class="aggregate-source"
                >
                  aggregate source
                </span>
              </h4>
              <div
                v-for="scenario in analysis.scenarios"
                :key="scenario.scenario"
                class="timing-scenario"
              >
                <h5>{{ scenario.scenario }}</h5>
                <div class="timing-table-scroll">
                  <table class="table timing-group-table">
                    <thead>
                      <tr>
                        <th>Path group</th>
                        <th v-for="record in selected" :key="recordKey(record)">
                          {{ runLabel(record) }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="pathGroup in scenario.groups" :key="pathGroup">
                        <th scope="row">{{ pathGroup }}</th>
                        <td v-for="record in selected" :key="recordKey(record)">
                          <template
                            v-if="
                              timingGroup(
                                record,
                                analysis.analysis,
                                scenario.scenario,
                                pathGroup
                              )
                            "
                          >
                            <span>
                              WNS
                              {{
                                formatTimingPart(
                                  timingGroup(
                                    record,
                                    analysis.analysis,
                                    scenario.scenario,
                                    pathGroup
                                  ).summary.wns
                                )
                              }}
                            </span>
                            <span>
                              TNS
                              {{
                                formatTimingPart(
                                  timingGroup(
                                    record,
                                    analysis.analysis,
                                    scenario.scenario,
                                    pathGroup
                                  ).summary.tns
                                )
                              }}
                            </span>
                            <span>
                              NVP
                              {{
                                formatTimingPart(
                                  timingGroup(
                                    record,
                                    analysis.analysis,
                                    scenario.scenario,
                                    pathGroup
                                  ).summary.nvp
                                )
                              }}
                            </span>
                          </template>
                          <span v-else class="missing-value" aria-label="Not present">—</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </details>
        </article>
      </template>
      <div v-if="dashboard.rawLoadingIds.size" class="status-line" role="status">
        Loading {{ dashboard.rawLoadingIds.size }} raw report(s)…
      </div>
      <div v-for="(message, id) in dc.rawErrors" :key="id" class="error-line" role="alert">
        {{ id }}: {{ message }}
      </div>
      <article
        v-for="section in visibleRawSections"
        :key="section.id"
        class="dc-section raw-section"
      >
        <h3>Raw · {{ section.label }}</h3>
        <DataTable
          :rows="sectionRows(section)"
          :columns="sectionColumns()"
          row-key="id"
          :copy-on-click="dc.preferences.copyOnClick"
          :filename="`dc-${section.id}.csv`"
        >
          <template v-if="dc.preferences.pathLinks" #cell-metric="{ value }">
            <SourceFileLink :path="value" />
          </template>
        </DataTable>
      </article>
    </div>
    <DcComparisonPicker
      :records="dashboard.records"
      :sections="pickerSections"
      :timing-scenarios="timingScopes.scenarios"
      :timing-path-groups="timingScopes.pathGroups"
    />
  </section>
</template>

<style scoped>
.dc-shell {
  display: flex;
  min-height: 340px;
  max-height: 76vh;
  margin-bottom: 14px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  overflow: hidden;
}
.dc-nav {
  flex: 0 0 auto;
  overflow: auto;
  border-right: 1px solid var(--color-border);
}
.dc-nav header {
  display: flex;
  justify-content: space-between;
  padding: 10px;
  border-bottom: 1px solid var(--color-border);
  font-size: 12px;
}
.dc-nav header span {
  color: var(--color-text-secondary);
}
.nav-actions {
  display: flex;
  gap: 4px;
  padding: 6px;
}
.run-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 6px;
  align-items: start;
  padding: 6px 8px;
  font-size: 11px;
  cursor: pointer;
  border-top: 1px solid transparent;
  border-bottom: 1px solid transparent;
}
.run-item.selected {
  background: var(--color-surface-hover);
  border-color: var(--color-border);
}
.run-item.vs-selected {
  border-left: 3px solid var(--color-primary);
}
.run-item span {
  min-width: 0;
}
.run-item b,
.run-item small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run-item small {
  color: var(--color-text-secondary);
  font-family: Consolas, monospace;
}
.baseline-button {
  width: 20px;
  height: 20px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
}
.baseline-button[aria-pressed='true'] {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.resize {
  width: 5px;
  flex: none;
  cursor: col-resize;
}
.resize:hover,
.resize:focus {
  background: var(--color-primary);
  outline: 0;
}
.dc-content {
  min-width: 0;
  flex: 1;
  overflow: auto;
}
.dc-toolbar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}
.dc-toolbar small {
  display: block;
  color: var(--color-text-secondary);
  font-size: 10px;
}
.picker-button {
  padding: 4px 10px;
  border: 1px solid var(--color-primary);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-weight: 800;
}
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}
.vs-status {
  color: var(--color-primary);
  font-size: 10px;
  font-weight: 600;
}
.picker-button span {
  font-size: 9px;
}
.dc-section {
  margin: 8px;
  border: 1px solid var(--color-border);
}
.dc-section h3 {
  padding: 6px 8px;
  font-size: 12px;
  text-transform: capitalize;
  background: var(--color-surface-hover);
  border-bottom: 1px solid var(--color-border);
}
.canonical-section h3 {
  box-shadow: inset 3px 0 var(--color-primary);
}
.timing-breakdown {
  border-top: 1px solid var(--color-border);
}
.timing-breakdown > summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 7px 10px;
  cursor: pointer;
  color: var(--color-text);
  font-size: 11px;
  font-weight: 700;
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface));
}
.timing-breakdown > summary small {
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 400;
}
.timing-analysis {
  padding: 8px;
}
.timing-analysis + .timing-analysis {
  border-top: 1px solid var(--color-border);
}
.timing-analysis h4 {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 5px;
  font-size: 11px;
  text-transform: capitalize;
}
.aggregate-source {
  padding: 1px 5px;
  border: 1px solid var(--color-primary);
  color: var(--color-primary);
  font-size: 9px;
  font-weight: 600;
  text-transform: none;
}
.timing-scenario {
  border: 1px solid var(--color-border);
}
.timing-scenario + .timing-scenario {
  margin-top: 6px;
}
.timing-scenario h5 {
  padding: 4px 7px;
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
  font-family: Consolas, Monaco, monospace;
  font-size: 10px;
}
.timing-table-scroll {
  overflow-x: auto;
}
.timing-group-table {
  width: 100%;
  font-family: Consolas, Monaco, monospace;
  font-size: 10px;
}
.timing-group-table th,
.timing-group-table td {
  padding: 4px 7px;
  border-right: 1px solid var(--color-border);
  white-space: nowrap;
}
.timing-group-table thead th,
.timing-group-table tbody th {
  text-align: left;
}
.timing-group-table tbody th {
  color: var(--color-text);
  font-weight: 600;
}
.timing-group-table td {
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.timing-group-table td > span + span {
  margin-left: 10px;
}
.timing-group-table td > span::first-letter {
  color: var(--color-text-secondary);
}
.missing-value {
  color: var(--color-text-secondary);
}
.raw-section {
  opacity: 0.96;
}
.dc-section :deep(.data-table th:first-child),
.dc-section :deep(.data-table td:first-child) {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--color-surface);
}
.dc-section :deep(.data-table th:first-child) {
  z-index: 3;
  background: var(--color-surface-hover);
}
.dc-section :deep(.data-table tbody tr:hover td:first-child) {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.dc-section :deep(.data-table tbody tr:hover td:first-child *) {
  color: inherit;
}
.dc-section :deep(.data-table tbody tr:hover td.change-better) {
  background: var(--color-success-background);
  color: var(--color-success);
}
.dc-section :deep(.data-table tbody tr:hover td.change-worse) {
  background: var(--color-danger-background);
  color: var(--color-danger);
}
.dc-section :deep(.data-table tbody tr:hover td.baseline) {
  box-shadow: inset 3px 0 var(--color-primary);
}
.status-line,
.error-line {
  padding: 6px 10px;
  font-size: 11px;
}
.error-line {
  color: var(--color-danger);
}
:deep(.baseline) {
  box-shadow: inset 3px 0 var(--color-primary);
}
:deep(.change-better) {
  background: color-mix(in srgb, #2ca66f 24%, var(--color-surface));
  color: var(--color-text);
}
:deep(.change-worse) {
  background: color-mix(in srgb, #d84a4a 25%, var(--color-surface));
  color: var(--color-text);
}
</style>
