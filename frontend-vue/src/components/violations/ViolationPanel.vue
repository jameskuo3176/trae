<script setup>
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { dashboardApi } from '@/api/dashboard'
import { violationsApi } from '@/api/violations'
import DataTable from '@/components/common/DataTable.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const ViolationDiffPanel = defineAsyncComponent(() => import('./ViolationDiffPanel.vue'))
const dashboard = useDashboardStore()
const recordId = ref('')
const group = ref('')
const source = ref('')
const sortBy = ref('slack')
const order = ref('asc')
const limit = ref(100)
const busGrouping = ref(true)
const mode = ref('table')
const rows = ref([])
const diffRows = ref([])
const loading = ref(false)
const error = ref('')
let controller

const records = computed(() => dashboard.records)
const selectedRecord = computed(() =>
  records.value.find(record => String(record.id) === recordId.value)
)
const groups = computed(() => [...new Set(rows.value.map(row => row.timing_group).filter(Boolean))])
const sources = computed(() => [
  ...new Set(
    rows.value
      .filter(row => !group.value || row.timing_group === group.value)
      .map(row => row.source_file)
      .filter(Boolean)
  )
])
const filtered = computed(() => {
  const values = rows.value.filter(
    row =>
      (!group.value || row.timing_group === group.value) &&
      (!source.value || row.source_file === source.value)
  )
  const grouped = busGrouping.value
    ? [
        ...new Map(
          values.map(row => [
            `${row.timing_group}|${String(row.startpoint).replace(/\[\d+\]/g, '[*]')}|${String(row.endpoint).replace(/\[\d+\]/g, '[*]')}`,
            row
          ])
        ).values()
      ]
    : values
  return grouped
    .sort((a, b) => {
      const left = a[sortBy.value],
        right = b[sortBy.value]
      const comparison =
        Number.isFinite(Number(left)) && Number.isFinite(Number(right))
          ? Number(left) - Number(right)
          : String(left ?? '').localeCompare(String(right ?? ''))
      return order.value === 'asc' ? comparison : -comparison
    })
    .slice(0, limit.value)
})
const columns = [
  { key: 'timing_group', label: 'Group' },
  { key: 'startpoint', label: 'Startpoint' },
  { key: 'endpoint', label: 'Endpoint' },
  { key: 'slack', label: 'Slack', numeric: true },
  { key: 'depth', label: 'Depth', numeric: true },
  { key: 'pure_depth', label: 'Pure depth', numeric: true },
  { key: 'cell_delay', label: 'Cell delay', numeric: true },
  { key: 'net_delay', label: 'Net delay', numeric: true },
  { key: 'source_file', label: 'Source' }
]

async function load() {
  if (!selectedRecord.value) return
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  try {
    rows.value = await dashboardApi.violations(
      selectedRecord.value.project_id,
      recordId.value,
      controller.signal
    )
  } catch (requestError) {
    if (requestError.code !== 'ERR_CANCELED') error.value = requestError.message
  } finally {
    loading.value = false
  }
}
async function loadDiff() {
  if (dashboard.selectedRecords.length < 2) return
  loading.value = true
  try {
    diffRows.value = await violationsApi.diff({
      base_record_id: dashboard.baselineId || dashboard.selectedRecords[0].id,
      target_record_id: dashboard.selectedRecords.find(r => String(r.id) !== dashboard.baselineId)
        ?.id
    })
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}
function setMode(value) {
  mode.value = value
  if (value === 'diff') loadDiff()
}
watch(recordId, () => {
  group.value = ''
  source.value = ''
  load()
})
watch(group, () => {
  source.value = ''
})
</script>

<template>
  <section class="card violation-panel">
    <header class="card-header">
      <div><strong>Violation explorer</strong><small>Lazy per-record path analysis</small></div>
      <div class="mode-tabs">
        <button
          v-for="value in ['table', 'chart', 'diff']"
          :key="value"
          type="button"
          :aria-pressed="mode === value"
          @click="setMode(value)"
        >
          {{ value }}
        </button>
      </div>
    </header>
    <div class="violation-controls">
      <select v-model="recordId" aria-label="Module and version">
        <option value="">Module / version</option>
        <option v-for="record in records" :key="record.id" :value="String(record.id)">
          {{ record.module_name }} · {{ record.version }}
        </option>
      </select>
      <select v-model="group" :disabled="!rows.length">
        <option value="">All timing groups</option>
        <option v-for="value in groups" :key="value">{{ value }}</option>
      </select>
      <select v-model="source" :disabled="!rows.length">
        <option value="">All source files</option>
        <option v-for="value in sources" :key="value">{{ value }}</option>
      </select>
      <select v-model="sortBy" aria-label="Sort field">
        <option value="slack">Slack</option>
        <option value="depth">Depth</option>
        <option value="cell_delay">Cell delay</option>
      </select>
      <select v-model="order" aria-label="Sort order">
        <option value="asc">Ascending</option>
        <option value="desc">Descending</option>
      </select>
      <select v-model.number="limit" aria-label="Limit">
        <option v-for="value in [20, 50, 100, 200]" :key="value" :value="value">{{ value }}</option>
      </select>
      <label><input v-model="busGrouping" type="checkbox" /> Bus grouping</label>
      <button class="btn btn-sm" type="button" :disabled="!recordId" @click="load">Refresh</button>
    </div>
    <LoadingSpinner v-if="loading" text="Loading violations…" />
    <div v-else-if="error" class="error-line" role="alert">{{ error }}</div>
    <ViolationDiffPanel v-else-if="mode === 'diff'" :rows="diffRows" :loading="loading" />
    <div v-else-if="mode === 'chart'" class="violation-chart" aria-label="Slack distribution">
      <div
        v-for="row in filtered.slice(0, 40)"
        :key="row.id"
        :title="`${row.slack}`"
        :style="{ width: `${Math.max(2, Math.min(100, Math.abs(Number(row.slack) || 0) * 20))}%` }"
      >
        <span>{{ row.timing_group }}</span>
      </div>
      <p v-if="!filtered.length">Select a run to chart violations.</p>
    </div>
    <DataTable
      v-else
      :rows="filtered"
      :columns="columns"
      empty-text="Select a module/version run to load violations."
      filename="violations.csv"
      copy-on-click
    />
  </section>
</template>

<style scoped>
.card-header small {
  display: block;
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 400;
}
.mode-tabs {
  display: flex;
}
.mode-tabs button {
  padding: 3px 8px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  text-transform: capitalize;
}
.mode-tabs button[aria-pressed='true'] {
  color: var(--color-primary);
  border-color: var(--color-primary);
}
.violation-controls {
  display: flex;
  gap: 5px;
  align-items: center;
  flex-wrap: wrap;
  padding: 7px 8px;
  border-bottom: 1px solid var(--color-border);
}
.violation-controls select {
  max-width: 220px;
  padding: 5px;
  font-size: 11px;
}
.violation-controls label {
  display: flex;
  gap: 4px;
  font-size: 11px;
}
.error-line {
  padding: 12px;
  color: #ff8c8c;
}
.violation-chart {
  min-height: 180px;
  padding: 12px;
}
.violation-chart div {
  min-width: 3px;
  margin: 3px 0;
  height: 16px;
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: 9px;
  overflow: hidden;
}
</style>
