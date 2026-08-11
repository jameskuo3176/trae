<script setup>
import { computed, ref } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import DataTable from '@/components/common/DataTable.vue'

const dashboard = useDashboardStore()
const baseDirInput = ref('')
const filteredRecords = computed(() => {
  const prefix = baseDirInput.value.trim()
  return prefix
    ? dashboard.records.filter(record => (record.full_dir || '').startsWith(prefix))
    : []
})
const rows = computed(() => {
  const groups = new Map()
  filteredRecords.value.forEach(record => {
    const key = `${record.project_id || ''}|${record.module_id || ''}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(record)
  })
  return [...groups].map(([key, records]) => {
    const latest = records.at(-1)
    return {
      key,
      project_name: latest.project_name,
      module_name: latest.module_name,
      count: records.length,
      version: latest.version || latest.tag,
      area_total: latest.area_total,
      power_total: latest.power_total,
      wns: latest.wns,
      tns: latest.tns,
      cell_count: latest.cell_count
    }
  })
})
const columns = [
  { key: 'project_name', label: '项目' },
  { key: 'module_name', label: '模块' },
  { key: 'count', label: '记录数', numeric: true },
  { key: 'version', label: '最新版本' },
  { key: 'area_total', label: '总面积', numeric: true },
  { key: 'power_total', label: '总功耗', numeric: true },
  { key: 'wns', label: 'WNS', numeric: true },
  { key: 'tns', label: 'TNS', numeric: true },
  { key: 'cell_count', label: '单元数', numeric: true }
]
</script>

<template>
  <section class="card">
    <header class="card-header">
      <span>目录模块聚合</span>
      <div class="directory-query">
        <input v-model="baseDirInput" type="text" placeholder="输入 base_dir 路径" />
        <span v-if="baseDirInput"
          >{{ filteredRecords.length }} 条记录，{{ rows.length }} 个模块</span
        >
      </div>
    </header>
    <DataTable
      :rows="rows"
      :columns="columns"
      row-key="key"
      filename="qor-directory-modules.csv"
      :empty-text="baseDirInput ? '未找到匹配的记录' : '请在上方输入 base_dir 路径进行查询'"
      copy-on-click
    />
  </section>
</template>

<style scoped>
.directory-query {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
  color: var(--color-text-secondary);
}
.directory-query input {
  min-width: 320px;
  font:
    11px Consolas,
    monospace;
}
</style>
