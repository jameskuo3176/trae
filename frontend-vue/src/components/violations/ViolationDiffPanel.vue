<script setup>
import DataTable from '@/components/common/DataTable.vue'
defineProps({ rows: { type: Array, default: () => [] }, loading: Boolean })
const columns = [
  { key: 'status', label: 'Status' },
  { key: 'timing_group', label: 'Group' },
  { key: 'startpoint', label: 'Startpoint' },
  { key: 'endpoint', label: 'Endpoint' },
  { key: 'base_slack', label: 'Base slack', numeric: true },
  { key: 'target_slack', label: 'Target slack', numeric: true },
  { key: 'delta', label: 'Δ slack', numeric: true }
]
</script>
<template>
  <div class="diff-panel">
    <div v-if="loading" class="empty-state">Loading violation diff…</div>
    <DataTable
      v-else
      :rows="rows"
      :columns="columns"
      empty-text="No violation differences"
      filename="violation-diff.csv"
    />
  </div>
</template>
