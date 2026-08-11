<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useDashboardStore } from '@/stores/dashboard'
import { qorApi } from '@/api/qor'
import FilterBar from '@/components/filters/FilterBar.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const route = useRoute()
const dashboard = useDashboardStore()
const loading = ref(false)
const compareData = ref(null)
const columns = ref([])
const error = ref('')

onMounted(async () => {
  const recordIds = route.query.record_ids
  if (recordIds) {
    const ids = recordIds.split(',').map(Number)
    ids.forEach(id => dashboard.selectedIds.add(id))
  }
  await loadCompareData()
})

async function loadCompareData() {
  loading.value = true
  error.value = ''
  try {
    const ids = Array.from(dashboard.selectedIds)
    if (ids.length === 0) {
      error.value = '请先选择要对比的记录'
      loading.value = false
      return
    }
    const params = { record_ids: ids.join(',') }
    const data = await qorApi.compare(params)
    compareData.value = data.records || data
    columns.value = data.columns || data.metrics || []
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '加载失败'
    console.error('Compare load failed:', e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="compare-page">
    <h1>数据对比</h1>
    <FilterBar />
    <p v-if="error" style="color: var(--color-text-secondary); padding: 20px">{{ error }}</p>
    <LoadingSpinner v-else-if="loading" text="加载对比数据..." />
    <div v-else-if="compareData?.length > 0" class="card">
      <div class="card-header">对比结果</div>
      <div class="card-body" style="overflow-x: auto">
        <table class="table">
          <thead>
            <tr>
              <th>指标</th>
              <th v-for="(col, i) in columns" :key="i">{{ col }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in compareData" :key="idx">
              <td>{{ row.label || row.name }}</td>
              <td v-for="(col, ci) in columns" :key="ci">
                {{ row[col] ?? row.values?.[col] ?? '-' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div v-else class="empty-state">暂无对比数据</div>
  </div>
</template>

<style scoped>
.compare-page h1 {
  margin-bottom: 20px;
  font-size: 24px;
}
</style>
