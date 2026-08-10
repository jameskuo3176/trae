<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'

const dashboard = useDashboardStore()
const baseDirInput = ref('')

const filteredRecords = computed(() => {
  if (!baseDirInput.value.trim()) return []
  return dashboard.records.filter(r => {
    const fullDir = r.full_dir || ''
    return fullDir.startsWith(baseDirInput.value)
  })
})

const modules = computed(() => {
  const map = new Map()
  filteredRecords.value.forEach(r => {
    const key = `${r.project_id || ''}|${r.module_id || ''}`
    if (!map.has(key)) {
      map.set(key, {
        projectId: r.project_id,
        moduleId: r.module_id,
        projectName: r.project_name,
        moduleName: r.module_name,
        records: []
      })
    }
    map.get(key).records.push(r)
  })
  return Array.from(map.values())
})

const metrics = ['area_total', 'power_total', 'wns', 'tns', 'cell_count']
</script>

<template>
  <div class="card">
    <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
      <span>目录模块聚合</span>
      <div style="display:flex; gap:8px; align-items:center;">
        <input
          v-model="baseDirInput"
          type="text"
          placeholder="输入 base_dir 路径 (如 /project/Syn/week2/main)"
          style="min-width:320px; font-size:12px;"
        >
        <span v-if="baseDirInput" style="color:#888; font-size:11px;">
          找到 {{ filteredRecords.length }} 条记录，{{ modules.length }} 个模块
        </span>
      </div>
    </div>
    <div class="card-body" style="padding:0;">
      <div v-if="!baseDirInput" style="padding:40px; text-align:center; color:var(--color-text-secondary);">
        请在上方输入 base_dir 路径进行查询
      </div>
      <div v-else style="max-height:60vh; overflow:auto;">
        <table style="width:100%; border-collapse: collapse; font-size:12px;">
          <thead>
            <tr style="background:var(--color-bg-secondary);">
              <th style="position:sticky; left:0; background:var(--color-bg-secondary); z-index:10; padding:8px; border:1px solid var(--color-border);">项目</th>
              <th style="position:sticky; left:0; background:var(--color-bg-secondary); z-index:10; padding:8px; border:1px solid var(--color-border);">模块</th>
              <th style="padding:8px; border:1px solid var(--color-border);">记录数</th>
              <th style="padding:8px; border:1px solid var(--color-border);">最新版本</th>
              <th style="padding:8px; border:1px solid var(--color-border);">总面积</th>
              <th style="padding:8px; border:1px solid var(--color-border);">总功耗</th>
              <th style="padding:8px; border:1px solid var(--color-border);">WNS</th>
              <th style="padding:8px; border:1px solid var(--color-border);">TNS</th>
              <th style="padding:8px; border:1px solid var(--color-border);">单元数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in modules" :key="`${m.projectId}-${m.moduleId}`">
              <td style="position:sticky; left:0; background:var(--color-bg); z-index:10; padding:8px; border:1px solid var(--color-border);">{{ m.projectName }}</td>
              <td style="position:sticky; left:0; background:var(--color-bg); z-index:10; padding:8px; border:1px solid var(--color-border);">{{ m.moduleName }}</td>
              <td style="padding:8px; border:1px solid var(--color-border); text-align:center;">{{ m.records.length }}</td>
              <td style="padding:8px; border:1px solid var(--color-border); text-align:center;">{{ m.records[m.records.length - 1]?.tag || m.records[m.records.length - 1]?.version }}</td>
              <td v-for="metric in metrics" :key="metric" style="padding:8px; border:1px solid var(--color-border); text-align:right;">
                {{ m.records[m.records.length - 1]?.[metric] ?? '-' }}
              </td>
            </tr>
            <tr v-if="!modules.length && baseDirInput">
              <td colspan="9" style="padding:40px; text-align:center; color:var(--color-text-secondary);">未找到匹配的记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
