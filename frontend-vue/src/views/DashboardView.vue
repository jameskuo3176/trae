<script setup>
import { computed, defineAsyncComponent, onMounted, provide, reactive, watch } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { useDashboardData } from '@/composables/useDashboardData'
import { useFilters } from '@/composables/useFilters'
import FilterBar from '@/components/filters/FilterBar.vue'
import DashboardConfigBar from '@/components/dashboard/DashboardConfigBar.vue'
import DashboardStats from '@/components/dashboard/DashboardStats.vue'
import ChartSettingsPanel from '@/components/dashboard/ChartSettingsPanel.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const AreaChart = defineAsyncComponent(() => import('@/components/charts/AreaChart.vue'))
const TimingChart = defineAsyncComponent(() => import('@/components/charts/TimingChart.vue'))
const PowerChart = defineAsyncComponent(() => import('@/components/charts/PowerChart.vue'))
const CellChart = defineAsyncComponent(() => import('@/components/charts/CellChart.vue'))
const PieChart = defineAsyncComponent(() => import('@/components/charts/PieChart.vue'))
const PhysicalMetricChart = defineAsyncComponent(
  () => import('@/components/charts/PhysicalMetricChart.vue')
)
const ViolationPanel = defineAsyncComponent(
  () => import('@/components/violations/ViolationPanel.vue')
)
const DcReportPanel = defineAsyncComponent(() => import('@/components/dashboard/DcReportPanel.vue'))
const CombinedTableView = defineAsyncComponent(
  () => import('@/components/dashboard/CombinedTableView.vue')
)
const TransposedTableView = defineAsyncComponent(
  () => import('@/components/dashboard/TransposedTableView.vue')
)
const DirAggregateView = defineAsyncComponent(
  () => import('@/components/dashboard/DirAggregateView.vue')
)
const DirModulesView = defineAsyncComponent(
  () => import('@/components/dashboard/DirModulesView.vue')
)
const RunNotesPanel = defineAsyncComponent(() => import('@/components/dashboard/RunNotesPanel.vue'))

const filters = useFiltersStore()
const dashboard = useDashboardStore()
const { loadProjects, loadModules, loadVersions, loadDashboardData } = useDashboardData()
const { onFilterChange } = useFilters()
const settings = reactive({
  orientation: 'vertical',
  height: 500,
  labelMode: 'both',
  chartType: 'bar',
  tableWidth: 0,
  activeView: 'charts'
})

onMounted(async () => {
  await loadProjects()
  await Promise.all([loadModules(), loadVersions()])
  await loadDashboardData()
})
onFilterChange(loadDashboardData)
watch(
  () => filters.projectId,
  async () => Promise.all([loadModules(), loadVersions()])
)

const stats = computed(() => ({
  total: dashboard.pagination?.total ?? dashboard.records.length,
  modules: new Set(dashboard.records.map(record => record.module_id).filter(Boolean)).size,
  projects: new Set(dashboard.records.map(record => record.project_id).filter(Boolean)).size,
  latest: dashboard.records.at(-1)?.version || '-'
}))

provide('chartSettings', {
  orientation: computed(() => settings.orientation),
  height: computed(() => settings.height),
  labelMode: computed(() => settings.labelMode),
  chartType: computed(() => settings.chartType),
  tableWidth: computed(() => settings.tableWidth)
})
</script>

<template>
  <main class="dashboard-page">
    <DashboardConfigBar
      :model-value="settings"
      @update:model-value="Object.assign(settings, $event)"
    />
    <FilterBar />
    <DashboardStats :stats="stats" />
    <LoadingSpinner
      v-if="dashboard.loading && !dashboard.records.length"
      text="Loading QoR records…"
    />
    <section v-else-if="dashboard.loadError" class="error-state" role="alert">
      <strong>Dashboard request failed</strong>
      <p>{{ dashboard.loadError }}</p>
      <button class="btn btn-sm" type="button" @click="loadDashboardData">Retry</button>
    </section>
    <section v-else-if="!dashboard.records.length" class="empty-state card">
      <strong>No records match the current scope.</strong>
      <p>Select a project or relax the module, version, and directory filters.</p>
    </section>
    <template v-else>
      <ChartSettingsPanel
        v-model:orientation="settings.orientation"
        v-model:height="settings.height"
        v-model:label-mode="settings.labelMode"
        v-model:chart-type="settings.chartType"
        v-model:table-width="settings.tableWidth"
        v-model:active-view="settings.activeView"
      />
      <DcReportPanel />
      <Suspense>
        <CombinedTableView v-if="settings.activeView === 'combined'" />
        <TransposedTableView v-else-if="settings.activeView === 'transposed'" />
        <DirAggregateView v-else-if="settings.activeView === 'aggregate'" />
        <DirModulesView v-else-if="settings.activeView === 'directory-modules'" />
        <div v-else class="charts-grid">
          <AreaChart /><TimingChart /><PowerChart /><CellChart />
          <PhysicalMetricChart
            metric="mbb_ratio"
            title="MBB merge ratio (%)"
            unit="%"
            :color-idx="5"
            :scale-to-percent="true"
          />
          <PhysicalMetricChart
            metric="clock_gating_ratio"
            title="Clock gating coverage (%)"
            unit="%"
            :color-idx="6"
            :scale-to-percent="true"
          />
          <PhysicalMetricChart
            metric="utilization"
            title="Placement utilization (%)"
            unit="%"
            :color-idx="7"
            :scale-to-percent="true"
          />
          <PhysicalMetricChart
            metric="congestion"
            title="Congestion index"
            :multi-metrics="[
              { key: 'congestion_h', label: 'Horizontal' },
              { key: 'congestion_v', label: 'Vertical' },
              { key: 'congestion_b', label: 'Combined' }
            ]"
          />
          <PieChart class="span-2" /><ViolationPanel class="span-2" /><RunNotesPanel
            class="span-2"
          />
        </div>
        <template #fallback><LoadingSpinner text="Loading visualization module…" /></template>
      </Suspense>
    </template>
  </main>
</template>

<style scoped>
.dashboard-page {
  padding: 8px 0 18px;
}
.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.span-2 {
  grid-column: span 2;
}
.error-state {
  padding: 24px;
  text-align: center;
  border: 1px solid #9c3434;
  background: var(--color-surface);
}
.error-state p,
.empty-state p {
  margin: 6px 0 12px;
  color: var(--color-text-secondary);
}
@media (max-width: 980px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
  .span-2 {
    grid-column: span 1;
  }
}
</style>
