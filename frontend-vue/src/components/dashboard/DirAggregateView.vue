<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useFiltersStore } from '@/stores/filters'

const dashboard = useDashboardStore()
const filters = useFiltersStore()
const groupBy = ref('run')
const statMethod = ref('avg')
const showBestWorst = ref(true)

const aggregated = computed(() => {
  const records = dashboard.records
  if (!records.length) return []

  const groups = new Map()
  records.forEach(r => {
    let key = ''
    if (groupBy.value === 'run') {
      key = `${r.full_dir || ''}|${r.id}`
    } else if (groupBy.value === 'base_dir') {
      const dir = r.full_dir || ''
      const idx = dir.lastIndexOf('/')
      key = idx > 0 ? dir.substring(0, idx) : dir
    } else if (groupBy.value === 'module') {
      key = `${r.project_name || ''}|${r.module_name || ''}`
    }

    if (!groups.has(key)) {
      groups.set(key, { key, items: [] })
    }
    groups.get(key).items.push(r)
  })

  const metrics = ['area_total', 'power_total', 'wns', 'tns', 'cell_count']

  return Array.from(groups.values()).map(g => {
    const result = { key: g.key, count: g.items.length }
    metrics.forEach(m => {
      const vals = g.items.map(x => parseFloat(x[m])).filter(x => !isNaN(x))
      if (!vals.length) {
        result[m] = null
        return
      }
      if (statMethod.value === 'avg') {
        result[m] = vals.reduce((a, b) => a + b, 0) / vals.length
      } else if (statMethod.value === 'min') {
        result[m] = Math.min(...vals)
      } else if (statMethod.value === 'max') {
        result[m] = Math.max(...vals)
      } else if (statMethod.value === 'median') {
        vals.sort((a, b) => a - b)
        const mid = Math.floor(vals.length / 2)
        result[m] = vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2
      }
    })
    return result
  })
})

const bestWorst = computed(() => {
  const result = { best: {}, worst: {} }
  const metrics = ['area_total', 'power_total', 'wns', 'tns', 'cell_count']
  metrics.forEach(m => {
    const valid = aggregated.value.filter(x => x[m] != null)
    if (!valid.length) return
    const sorted = [...valid].sort((a, b) => a[m] - b[m])
    if (['wns', 'tns'].includes(m)) {
      result.worst[m] = sorted[0]?.key
      result.best[m] = sorted[sorted.length - 1]?.key
    } else {
      result.best[m] = sorted[0]?.key
      result.worst[m] = sorted[sorted.length - 1]?.key
    }
  })
  return result
})

function formatValue(v) {
  if (v == null) return '-'
  return typeof v === 'number' ? v.toFixed(3) : String(v)
}
</script>

<template>
  <div class="card">
    <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
      <span>目录聚合视图</span>
      <div style="display:flex; gap:8px; align-items:center;">
        <label>聚合维度:</label>
        <select v-model="groupBy" style="font-size:12px;">
          <option value="run">按 Run</option>
          <option value="base_dir">按 Base Dir</option>
          <option value="module">按 Module</option>
        </select>
        <label>聚合方法:</label>
        <select v-model="statMethod" style="font-size:12px;">
          <option value="avg">平均 (avg)</option>
          <option value="min">最小 (min)</option>
          <option value="max">最大 (max)</option>
          <option value="median">中位数 (median)</option>
        </select>
        <label style="display:flex; gap:4px; align-items:center;">
          <input type="checkbox" v-model="showBestWorst"> 标注最佳/最差
        </label>
        <span style="color:#888; font-size:11px; display:flex; gap:8px; align-items:center;">
          <span style="display:inline-block; width:10px; height:10px; background:#d9f7be; border:1px solid #52c41a;"></span> 最佳
          <span style="display:inline-block; width:10px; height:10px; background:#fde2e1; border:1px solid #f5222d;"></span> 最差
        </span>
      </div>
    </div>
    <div class="card-body" style="padding:0;">
      <div style="max-height: 60vh; overflow:auto;">
        <table style="width:100%; border-collapse: collapse; font-size:12px;">
          <thead>
            <tr style="background:var(--color-bg-secondary);">
              <th style="position:sticky; left:0; background:var(--color-bg-secondary); z-index:10; padding:8px; border:1px solid var(--color-border);">分组 ({{ aggregated.length }})</th>
              <th style="padding:8px; border:1px solid var(--color-border);">数量</th>
              <th style="padding:8px; border:1px solid var(--color-border);">总面积</th>
              <th style="padding:8px; border:1px solid var(--color-border);">总功耗</th>
              <th style="padding:8px; border:1px solid var(--color-border);">WNS</th>
              <th style="padding:8px; border:1px solid var(--color-border);">TNS</th>
              <th style="padding:8px; border:1px solid var(--color-border);">单元数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="g in aggregated" :key="g.key">
              <td style="position:sticky; left:0; background:var(--color-bg); z-index:10; padding:8px; border:1px solid var(--color-border); font-size:11px; max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                {{ g.key }}
              </td>
              <td style="padding:8px; border:1px solid var(--color-border); text-align:center;">{{ g.count }}</td>
              <td
                v-for="m in ['area_total', 'power_total', 'wns', 'tns', 'cell_count']"
                :key="m"
                :class="showBestWorst && g.key === bestWorst.best[m] ? 'color-good' : (showBestWorst && g.key === bestWorst.worst[m] ? 'color-bad' : '')"
                style="padding:8px; border:1px solid var(--color-border); text-align:right;"
              >
                {{ formatValue(g[m]) }}
              </td>
            </tr>
            <tr v-if="!aggregated.length">
              <td colspan="7" style="padding:40px; text-align:center; color:var(--color-text-secondary);">无数据</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.color-bad {
  background-color: #fde2e1;
}
.color-good {
  background-color: #d9f7be;
}
</style>
