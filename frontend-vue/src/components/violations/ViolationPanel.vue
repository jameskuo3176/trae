<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { violationsApi } from '@/api/violations'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const dashboard = useDashboardStore()
const violations = ref([])
const loading = ref(false)
const activeModule = ref('')
const activeVersion = ref('')

const modules = computed(() => [...new Set(violations.value.map(v => v.module_name || v.module))])
const versions = computed(() => {
  if (!activeModule.value) return [...new Set(violations.value.map(v => v.version))]
  return [...new Set(
    violations.value
      .filter(v => (v.module_name || v.module) === activeModule.value)
      .map(v => v.version)
  )]
})

const filteredViolations = computed(() => {
  return violations.value.filter(v => {
    if (activeModule.value && (v.module_name || v.module) !== activeModule.value) return false
    if (activeVersion.value && v.version !== activeVersion.value) return false
    return true
  })
})

async function loadViolations() {
  loading.value = true
  try {
    const ids = [...dashboard.selectedIds].join(',')
    const data = await violationsApi.getList({ record_ids: ids })
    violations.value = data || []
    if (modules.value.length > 0) activeModule.value = modules.value[0]
  } catch (e) {
    console.error('Violations load failed:', e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card">
    <div class="card-header">
      <span>违例分析</span>
      <div class="violation-filters">
        <select v-model="activeModule">
          <option value="">全部模块</option>
          <option v-for="m in modules" :key="m" :value="m">{{ m }}</option>
        </select>
        <select v-model="activeVersion">
          <option value="">全部版本</option>
          <option v-for="v in versions" :key="v" :value="v">{{ v }}</option>
        </select>
        <button class="btn btn-sm" @click="loadViolations" :disabled="loading">
          刷新
        </button>
      </div>
    </div>
    <div class="card-body">
      <LoadingSpinner v-if="loading" text="加载违例数据..." />
      <div v-else-if="violations.length === 0" class="empty-state">
        暂无违例数据，请先选择记录并点击刷新
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>路径</th>
            <th>模块</th>
            <th>版本</th>
            <th>WNS</th>
            <th>TNS</th>
            <th>类型</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(v, idx) in filteredViolations" :key="idx">
            <td>{{ v.path || v.name }}</td>
            <td>{{ v.module_name || v.module }}</td>
            <td>{{ v.version }}</td>
            <td>{{ v.wns }}</td>
            <td>{{ v.tns }}</td>
            <td>
              <span class="tag">{{ v.type || v.group }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.violation-filters {
  display: flex;
  gap: 8px;
  align-items: center;
}
.violation-filters select {
  min-width: 120px;
}
</style>