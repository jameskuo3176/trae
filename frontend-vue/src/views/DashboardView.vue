<script setup>
import { ref, computed, onMounted, watch, provide } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { useDashboardData } from '@/composables/useDashboardData'
import { useFilters } from '@/composables/useFilters'
import FilterBar from '@/components/filters/FilterBar.vue'
import AreaChart from '@/components/charts/AreaChart.vue'
import TimingChart from '@/components/charts/TimingChart.vue'
import PowerChart from '@/components/charts/PowerChart.vue'
import CellChart from '@/components/charts/CellChart.vue'
import PieChart from '@/components/charts/PieChart.vue'
import PhysicalMetricChart from '@/components/charts/PhysicalMetricChart.vue'
import StatCard from '@/components/common/StatCard.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ViolationPanel from '@/components/violations/ViolationPanel.vue'
import DcReportPanel from '@/components/dashboard/DcReportPanel.vue'
import ChartSettingsPanel from '@/components/dashboard/ChartSettingsPanel.vue'
import CombinedTableView from '@/components/dashboard/CombinedTableView.vue'
import TransposedTableView from '@/components/dashboard/TransposedTableView.vue'
import DirAggregateView from '@/components/dashboard/DirAggregateView.vue'
import DirModulesView from '@/components/dashboard/DirModulesView.vue'
import RunNotesPanel from '@/components/dashboard/RunNotesPanel.vue'

const filters = useFiltersStore()
const dashboard = useDashboardStore()
const { loadProjects, loadModules, loadVersions, loadDashboardData } = useDashboardData()
const { onFilterChange } = useFilters()

const error = ref(null)

// 图表设置
const chartOrientation = ref('vertical')
const chartHeight = ref(500)
const chartLabelMode = ref('both')
const chartType = ref('bar')
const globalTableWidth = ref(0)

// 视图切换
const showCombinedTable = ref(false)
const showTransposedTable = ref(false)
const showDirAggregate = ref(false)
const showDirModules = ref(false)

onMounted(async () => {
  await loadProjects()
  await loadModules()
  await loadVersions()
  await loadDashboardData()
})

onFilterChange(() => {
  loadDashboardData()
})

watch(
  () => [filters.projectId, filters.moduleIds],
  () => {
    if (filters.projectId) loadModules()
    loadVersions()
  },
  { deep: true }
)

const stats = computed(() => {
  const records = dashboard.records
  return {
    total: records.length,
    modules: new Set(records.map(r => r.module_name).filter(Boolean)).size,
    projects: new Set(records.map(r => r.module_id).filter(Boolean)).size,
    latest: records.length > 0 ? records[records.length - 1].version : '-'
  }
})

// 提供图表设置给子组件
provide('chartSettings', {
  orientation: chartOrientation,
  height: chartHeight,
  labelMode: chartLabelMode,
  chartType,
  tableWidth: globalTableWidth
})
</script>

<template>
  <div class="dashboard-page">
    <FilterBar />
    <div class="grid-3 dashboard-stats">
      <StatCard label="记录总数" :value="stats.total" icon="trending-up" />
      <StatCard label="模块数" :value="stats.modules" icon="layers" />
      <StatCard label="项目数" :value="stats.projects" icon="folder" />
      <StatCard label="最新版本" :value="stats.latest" icon="tag" />
    </div>
    <LoadingSpinner v-if="dashboard.loading" text="正在加载数据..." />
    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button class="btn" @click="loadDashboardData">重试</button>
    </div>
    <template v-else>
      <!-- 图表设置面板 -->
      <ChartSettingsPanel
        v-model:orientation="chartOrientation"
        v-model:height="chartHeight"
        v-model:label-mode="chartLabelMode"
        v-model:chart-type="chartType"
        v-model:table-width="globalTableWidth"
        v-model:show-combined="showCombinedTable"
        v-model:show-transposed="showTransposedTable"
        v-model:show-dir-aggregate="showDirAggregate"
        v-model:show-dir-modules="showDirModules"
      />

      <!-- DC 报告数据对比导航 -->
      <DcReportPanel />

      <!-- 视图区域 -->
      <CombinedTableView v-if="showCombinedTable" />
      <TransposedTableView v-else-if="showTransposedTable" />
      <DirAggregateView v-else-if="showDirAggregate" />
      <DirModulesView v-else-if="showDirModules" />

      <!-- 图表区域 -->
      <template v-if="!showCombinedTable && !showTransposedTable && !showDirAggregate && !showDirModules">
        <div class="grid-2">
          <AreaChart />
          <TimingChart />
        </div>
        <div class="grid-2">
          <PowerChart />
          <CellChart />
        </div>
        <div class="grid-2">
          <PhysicalMetricChart
            metric="mbb_ratio"
            title="MBB 合并率 (%)"
            unit="%"
            :color-idx="5"
            :scale-to-percent="true"
          />
          <PhysicalMetricChart
            metric="clock_gating_ratio"
            title="时钟门控覆盖率 (%)"
            unit="%"
            :color-idx="6"
            :scale-to-percent="true"
          />
        </div>
        <div class="grid-2">
          <PhysicalMetricChart
            metric="utilization"
            title="布局利用率 (%)"
            unit="%"
            :color-idx="7"
            :scale-to-percent="true"
          />
          <PhysicalMetricChart
            metric="congestion"
            title="拥塞指数"
            :multi-metrics="[
              { key: 'congestion_h', label: '水平 (H)' },
              { key: 'congestion_v', label: '垂直 (V)' },
              { key: 'congestion_b', label: '综合 (B)' }
            ]"
            :color-idx="0"
          />
        </div>
        <PieChart />
        <ViolationPanel />
        <RunNotesPanel />
      </template>
    </template>
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: 16px 0;
}
.dashboard-stats {
  margin-bottom: 24px;
}
.error-state {
  text-align: center;
  padding: 40px;
  color: var(--color-text-secondary);
}
</style>