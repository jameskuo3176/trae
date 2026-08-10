<script setup>
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { qorApi } from '@/api/qor'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const dashboard = useDashboardStore()
const notes = ref([])
const loading = ref(false)

const activeModule = ref('')
const activeVersion = ref('')
const activeFullDir = ref('')

const modules = computed(() => {
  return [...new Set(dashboard.records.map(r => r.module_name).filter(Boolean))]
})

const versions = computed(() => {
  if (!activeModule.value) {
    return [...new Set(dashboard.records.map(r => r.version || r.tag).filter(Boolean))]
  }
  return [...new Set(
    dashboard.records
      .filter(r => r.module_name === activeModule.value)
      .map(r => r.version || r.tag)
      .filter(Boolean)
  )]
})

const fullDirs = computed(() => {
  return [...new Set(dashboard.records.map(r => r.full_dir).filter(Boolean))]
})

const filteredNotes = computed(() => {
  return notes.value.filter(n => {
    if (activeModule.value && n.module_name !== activeModule.value) return false
    if (activeVersion.value && n.version !== activeVersion.value) return false
    if (activeFullDir.value && n.full_dir !== activeFullDir.value) return false
    return true
  })
})

async function loadNotes() {
  loading.value = true
  try {
    const params = {}
    if (activeModule.value) params.module_name = activeModule.value
    if (activeVersion.value) params.version = activeVersion.value
    const data = await qorApi.getRunNotes(params)
    notes.value = data || []
  } catch (e) {
    console.error('Run notes load failed:', e)
  } finally {
    loading.value = false
  }
}

watch(activeModule, () => {
  activeVersion.value = ''
  loadNotes()
})

watch(activeVersion, () => {
  loadNotes()
})

watch(activeFullDir, () => {
  loadNotes()
})
</script>

<template>
  <div class="card run-notes-card">
    <div class="card-header">
      <span>Run 备注 / 参数</span>
      <div class="notes-filters">
        <select v-model="activeModule">
          <option value="">选择模块</option>
          <option v-for="m in modules" :key="m" :value="m">{{ m }}</option>
        </select>
        <select v-model="activeVersion">
          <option value="">选择版本</option>
          <option v-for="v in versions" :key="v" :value="v">{{ v }}</option>
        </select>
        <select v-model="activeFullDir">
          <option value="">全部 full_dir</option>
          <option v-for="d in fullDirs" :key="d" :value="d">{{ d }}</option>
        </select>
        <button class="btn btn-sm" @click="loadNotes">刷新</button>
      </div>
    </div>
    <div class="card-body">
      <LoadingSpinner v-if="loading" text="加载备注..." />
      <div v-else-if="notes.length === 0" class="empty-state">
        暂无备注数据，请选择模块和版本后点击刷新
      </div>
      <div v-else class="notes-table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>模块</th>
              <th>版本</th>
              <th>full_dir</th>
              <th>备注</th>
              <th>参数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="n in filteredNotes" :key="n.id">
              <td>{{ n.module_name }}</td>
              <td>{{ n.version || n.tag }}</td>
              <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                {{ n.full_dir || '-' }}
              </td>
              <td>{{ n.comment || n.notes || '-' }}</td>
              <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                {{ n.params || '-' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.run-notes-card {
  margin-top: 12px;
}
.notes-filters {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
}
.notes-filters select {
  min-width: 120px;
}
.notes-table-wrap {
  max-height: 500px;
  overflow: auto;
}
</style>