<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useDcComparisonStore } from '@/stores/dcComparison'
import { dashboardApi } from '@/api/dashboard'
import { useGvim } from '@/composables/useGvim'
import DataTable from '@/components/common/DataTable.vue'
import DcComparisonPicker from './DcComparisonPicker.vue'

const dashboard = useDashboardStore()
const dc = useDcComparisonStore()
const { href: gvimHref, handleClick: handleGvimClick } = useGvim()
const navWidth = ref(Number(localStorage.getItem('dcNavWidth')) || 236)
const vsDraftIds = ref(new Set())
const rawControllers = new Map()

const records = computed(() =>
  dashboard.records.filter(
    record => !dc.preferences.onlyWithRaw || dashboard.rawReports[String(record.id)]
  )
)
const selected = computed(() =>
  dashboard.selectedRecords.filter(record => dashboard.rawReports[String(record.id)])
)
const activeSelection = computed(() =>
  dc.preferences.vsMode ? vsDraftIds.value : dashboard.selectedIds
)

function normalizedRaw(record) {
  const raw = dashboard.rawReports[String(record.id)]
  if (!raw) return {}
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

const sections = computed(() => {
  const result = new Map()
  selected.value.forEach(record => {
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

const visibleSections = computed(() => {
  const configured = dc.preferences.sectionIds
  return sections.value.filter(section => !configured.length || configured.includes(section.id))
})

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
        const data = normalizedRaw(record)[section.id]
        row[String(record.id)] = Array.isArray(data)
          ? data
              .map(item => item?.[metric])
              .filter(value => value != null)
              .join(' / ')
          : data?.[metric]
        row.__classes[String(record.id)] = changeClass(
          section.id,
          metric,
          row[String(record.id)],
          record
        )
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
  if (!dc.preferences.showChange || String(record.id) === dashboard.baselineId) return ''
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
      key: String(record.id),
      label: `${record.module_name || 'module'} · ${record.version || record.tag || record.id}`,
      numeric: true,
      sortValue: row => numericValue(row[String(record.id)]) ?? row[String(record.id)],
      class: row => [
        dashboard.baselineId === String(record.id) ? 'baseline' : '',
        row.__classes?.[String(record.id)] || ''
      ]
    }))
  ]
}

async function ensureRaw(record) {
  const id = String(record.id)
  if (dashboard.rawReports[id] || dashboard.rawLoadingIds.has(id)) return
  const controller = new AbortController()
  rawControllers.set(id, controller)
  dashboard.setRawLoading(id, true)
  try {
    const raw = await dashboardApi.rawReport(record.project_id, id, controller.signal)
    dashboard.setRawReport(id, raw)
  } catch (error) {
    if (error.code !== 'ERR_CANCELED') dc.rawErrors = { ...dc.rawErrors, [id]: error.message }
  } finally {
    dashboard.setRawLoading(id, false)
    rawControllers.delete(id)
  }
}

function toggle(record) {
  const id = String(record.id)
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
  () => dc.preferences.runIds,
  ids => {
    if (!ids) return
    dashboard.selectedIds = new Set(ids.map(String))
    dashboard.selectedRecords.forEach(ensureRaw)
    if (dc.preferences.vsMode) vsDraftIds.value = new Set(dashboard.selectedIds)
  }
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
        <strong id="dc-heading">DC comparison</strong><span>{{ selected.length }} ready</span>
      </header>
      <div class="nav-actions">
        <button class="btn btn-sm btn-default" type="button" @click="selectAllRuns">All</button>
        <button class="btn btn-sm btn-default" type="button" @click="dashboard.clearSelection">
          Clear
        </button>
      </div>
      <label
        v-for="record in records"
        :key="record.id"
        class="run-item"
        :class="{
          selected: activeSelection.has(String(record.id)),
          'vs-selected': dc.preferences.vsMode && vsDraftIds.has(String(record.id))
        }"
      >
        <input
          type="checkbox"
          :checked="activeSelection.has(String(record.id))"
          @change="toggle(record)"
        />
        <span
          ><b>{{ record.module_name || 'Module' }}</b
          ><small>{{ record.version || record.tag }} · {{ record.full_dir }}</small></span
        >
        <button
          type="button"
          class="baseline-button"
          :aria-pressed="dashboard.baselineId === String(record.id)"
          title="Set baseline"
          @click.prevent="dashboard.setBaseline(record.id)"
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
        Select runs from the checklist to load DC reports lazily.
      </div>
      <div v-else-if="dashboard.rawLoadingIds.size" class="status-line" role="status">
        Loading {{ dashboard.rawLoadingIds.size }} raw report(s)…
      </div>
      <div v-for="(message, id) in dc.rawErrors" :key="id" class="error-line" role="alert">
        {{ id }}: {{ message }}
      </div>
      <article v-for="section in visibleSections" :key="section.id" class="dc-section">
        <h3>{{ section.label }}</h3>
        <DataTable
          :rows="sectionRows(section)"
          :columns="sectionColumns()"
          row-key="id"
          :copy-on-click="dc.preferences.copyOnClick"
          :filename="`dc-${section.id}.csv`"
        >
          <template v-if="dc.preferences.pathLinks" #cell-metric="{ value }">
            <a
              v-if="gvimHref(value)"
              :href="gvimHref(value)"
              title="Open with gvim protocol; Alt+click uses server fallback"
              @click="handleGvimClick($event, value)"
              >{{ value }}</a
            ><span v-else>{{ value }}</span>
          </template>
        </DataTable>
      </article>
    </div>
    <DcComparisonPicker :records="dashboard.records" :sections="sections" />
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
.status-line,
.error-line {
  padding: 6px 10px;
  font-size: 11px;
}
.error-line {
  color: #ff8c8c;
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
