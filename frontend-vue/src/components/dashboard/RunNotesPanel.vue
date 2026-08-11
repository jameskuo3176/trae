<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { dashboardApi } from '@/api/dashboard'
import DataTable from '@/components/common/DataTable.vue'

const dashboard = useDashboardStore()
const recordId = ref('')
const notes = ref([])
const loading = ref(false)
const error = ref('')
let controller
const record = computed(() => dashboard.records.find(item => String(item.id) === recordId.value))
const columns = [
  { key: 'created_at', label: 'Time' },
  { key: 'author', label: 'Author' },
  { key: 'comment', label: 'Note' },
  { key: 'params', label: 'Parameters' },
  { key: 'full_dir', label: 'Run path' }
]
async function load() {
  if (!record.value) return
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  error.value = ''
  try {
    notes.value = await dashboardApi.notes(
      record.value.project_id,
      recordId.value,
      controller.signal
    )
  } catch (requestError) {
    if (requestError.code !== 'ERR_CANCELED') error.value = requestError.message
  } finally {
    loading.value = false
  }
}
watch(recordId, load)
onBeforeUnmount(() => controller?.abort())
</script>
<template>
  <section class="card notes-panel">
    <header class="card-header">
      <span>Run notes / parameters</span>
      <select v-model="recordId">
        <option value="">Select module / version / run</option>
        <option v-for="item in dashboard.records" :key="item.id" :value="String(item.id)">
          {{ item.module_name }} · {{ item.version }} · {{ item.full_dir }}
        </option>
      </select>
    </header>
    <div v-if="loading" class="empty-state">Loading run notes…</div>
    <div v-else-if="error" class="error-line" role="alert">{{ error }}</div>
    <DataTable
      v-else
      :rows="notes"
      :columns="columns"
      empty-text="Select a run to load its notes lazily."
      filename="run-notes.csv"
      copy-on-click
    />
  </section>
</template>
<style scoped>
.notes-panel select {
  max-width: 560px;
  font:
    11px Consolas,
    monospace;
}
.error-line {
  padding: 12px;
  color: #ff8c8c;
}
</style>
