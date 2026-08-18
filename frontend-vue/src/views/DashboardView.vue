<script setup>
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  provide,
  reactive,
  ref,
  watch
} from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { useDashboardData } from '@/composables/useDashboardData'
import { useFilters } from '@/composables/useFilters'
import { useTheme } from '@/composables/useTheme'
import FilterBar from '@/components/filters/FilterBar.vue'
import DashboardConfigBar from '@/components/dashboard/DashboardConfigBar.vue'
import DashboardStats from '@/components/dashboard/DashboardStats.vue'
import RiskOverviewPanel from '@/components/dashboard/RiskOverviewPanel.vue'
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
const { tableFontSize, setTableFontSize } = useTheme()
const settings = reactive({
  orientation: 'vertical',
  height: 500,
  labelMode: 'both',
  chartType: 'bar',
  tableWidth: 0,
  tableFontSize: tableFontSize.value,
  activeView: 'charts'
})

onMounted(async () => {
  await loadProjects()
  await Promise.all([loadModules(), loadVersions()])
  await loadDashboardData()
  window.addEventListener('scroll', onWindowScroll, { passive: true })
  updateActiveSection()
})
onBeforeUnmount(() => {
  window.removeEventListener('scroll', onWindowScroll)
})
onFilterChange(loadDashboardData)
watch(
  () => [...filters.projectIds],
  async () => Promise.all([loadModules(), loadVersions()])
)
watch(
  () => settings.tableFontSize,
  value => setTableFontSize(value)
)
watch(tableFontSize, value => {
  if (settings.tableFontSize !== value) settings.tableFontSize = value
})

const stats = computed(() => ({
  total: dashboard.pagination?.total ?? dashboard.records.length,
  modules: new Set(dashboard.records.map(record => record.module_id).filter(Boolean)).size,
  projects: new Set(dashboard.records.map(record => record.project_id).filter(Boolean)).size,
  latest: dashboard.records.at(-1)?.version || '-'
}))

// 左侧目录：随当前视图（activeView）动态生成可跳转的内容区块
const sections = computed(() => {
  const list = [
    { id: 'section-stats', label: '统计概览' },
    { id: 'section-risk', label: '版本风险' },
    { id: 'section-dc', label: 'DC 报告' }
  ]
  if (settings.activeView === 'charts') {
    list.push(
      { id: 'section-chart-area', label: '面积' },
      { id: 'section-chart-timing', label: '时序分析' },
      { id: 'section-chart-power', label: '功耗' },
      { id: 'section-chart-cell', label: '单元数' },
      { id: 'section-chart-mbb', label: '合并率' },
      { id: 'section-chart-ccg', label: '门控覆盖' },
      { id: 'section-chart-util', label: '利用率' },
      { id: 'section-chart-cong', label: '拥塞' },
      { id: 'section-chart-pie', label: '分布饼图' },
      { id: 'section-chart-violations', label: '违例' }
    )
  } else {
    list.push({ id: 'section-view', label: '数据视图' })
  }
  list.push({ id: 'section-notes', label: '运行备注' })
  return list
})

const activeSection = ref('')
const hasScrolled = ref(false)

function scrollToSection(id) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  activeSection.value = id
  // 异步图表/备注可能延迟渲染导致首次定位偏移，稍后校正一次
  setTimeout(() => {
    const target = document.getElementById(id)
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 350)
}

function updateActiveSection() {
  let current = ''
  for (const section of sections.value) {
    const el = document.getElementById(section.id)
    if (el && el.getBoundingClientRect().top <= 150) current = section.id
  }
  activeSection.value = current || sections.value[0]?.id || ''
}

function onWindowScroll() {
  hasScrolled.value = true
  updateActiveSection()
}

watch(
  () => sections.value.map(section => section.id).join(','),
  () => {
    if (!hasScrolled.value) updateActiveSection()
    else queueMicrotask(updateActiveSection)
  }
)

provide('chartSettings', {
  orientation: computed(() => settings.orientation),
  height: computed(() => settings.height),
  labelMode: computed(() => settings.labelMode),
  chartType: computed(() => settings.chartType),
  tableWidth: computed(() => settings.tableWidth),
  tableFontSize: computed(() => settings.tableFontSize)
})
</script>

<template>
  <main class="dashboard-page">
    <aside
      v-if="dashboard.records.length && !dashboard.loading"
      class="dashboard-toc"
      aria-label="页面导航"
    >
      <strong class="toc-title">目录</strong>
      <ul>
        <li v-for="section in sections" :key="section.id">
          <button
            type="button"
            :class="['toc-item', { active: activeSection === section.id }]"
            @click="scrollToSection(section.id)"
          >
            {{ section.label }}
          </button>
        </li>
      </ul>
    </aside>
    <div class="dashboard-content">
      <DashboardConfigBar
        :model-value="settings"
        @update:model-value="Object.assign(settings, $event)"
      />
      <FilterBar />
      <section v-if="dashboard.diagnostics.length" class="diagnostic-state" role="status">
        <strong>Module mapping diagnostics</strong>
        <p>
          {{ dashboard.diagnostics.length }} module mapping issue(s) were detected. Records with
          unresolved GlobalModule identities are not silently matched by name.
        </p>
        <details>
          <summary>Show details</summary>
          <pre>{{ JSON.stringify(dashboard.diagnostics, null, 2) }}</pre>
        </details>
      </section>
      <section id="section-stats" class="anchor-target">
        <DashboardStats :stats="stats" />
      </section>
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
        <section id="section-risk" class="anchor-target">
          <RiskOverviewPanel />
        </section>
        <ChartSettingsPanel
          v-model:orientation="settings.orientation"
          v-model:height="settings.height"
          v-model:label-mode="settings.labelMode"
          v-model:chart-type="settings.chartType"
          v-model:table-width="settings.tableWidth"
          v-model:table-font-size="settings.tableFontSize"
          v-model:active-view="settings.activeView"
        />
        <section id="section-dc" class="anchor-target">
          <DcReportPanel />
        </section>
        <Suspense>
          <div v-if="settings.activeView === 'combined'" id="section-view" class="anchor-target">
            <CombinedTableView />
          </div>
          <div
            v-else-if="settings.activeView === 'transposed'"
            id="section-view"
            class="anchor-target"
          >
            <TransposedTableView />
          </div>
          <div v-else-if="settings.activeView === 'aggregate'" id="section-view" class="anchor-target">
            <DirAggregateView />
          </div>
          <div
            v-else-if="settings.activeView === 'directory-modules'"
            id="section-view"
            class="anchor-target"
          >
            <DirModulesView />
          </div>
          <div v-else class="charts-grid">
            <section id="section-chart-area" class="chart-block anchor-target"><AreaChart /></section>
            <section id="section-chart-timing" class="chart-block anchor-target">
              <TimingChart />
            </section>
            <section id="section-chart-power" class="chart-block anchor-target">
              <PowerChart />
            </section>
            <section id="section-chart-cell" class="chart-block anchor-target"><CellChart /></section>
            <section id="section-chart-mbb" class="chart-block anchor-target">
              <PhysicalMetricChart
                metric="mbb_ratio"
                title="MBB merge ratio (%)"
                unit="%"
                :color-idx="5"
                :scale-to-percent="true"
              />
            </section>
            <section id="section-chart-ccg" class="chart-block anchor-target">
              <PhysicalMetricChart
                metric="clock_gating_ratio"
                title="Clock gating coverage (%)"
                unit="%"
                :color-idx="6"
                :scale-to-percent="true"
              />
            </section>
            <section id="section-chart-util" class="chart-block anchor-target">
              <PhysicalMetricChart
                metric="utilization"
                title="Placement utilization (%)"
                unit="%"
                :color-idx="7"
                :scale-to-percent="true"
              />
            </section>
            <section id="section-chart-cong" class="chart-block anchor-target">
              <PhysicalMetricChart
                metric="congestion"
                title="Congestion index"
                :multi-metrics="[
                  { key: 'congestion_h', label: 'Horizontal' },
                  { key: 'congestion_v', label: 'Vertical' },
                  { key: 'congestion_b', label: 'Combined' }
                ]"
              />
            </section>
            <section id="section-chart-pie" class="chart-block anchor-target"><PieChart /></section>
            <section id="section-chart-violations" class="chart-block anchor-target">
              <ViolationPanel />
            </section>
          </div>
          <template #fallback><LoadingSpinner text="Loading visualization module…" /></template>
        </Suspense>
        <Suspense>
          <section id="section-notes" class="anchor-target">
            <RunNotesPanel />
          </section>
          <template #fallback><LoadingSpinner text="Loading annotation evidence…" /></template>
        </Suspense>
      </template>
    </div>
  </main>
</template>

<style scoped>
.dashboard-page {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  padding: 8px 0 18px;
}
.dashboard-content {
  flex: 1;
  min-width: 0;
}
.dashboard-toc {
  position: sticky;
  top: 8px;
  flex-shrink: 0;
  width: 140px;
  max-height: calc(100vh - 16px);
  overflow-y: auto;
  padding: 10px 8px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}
.toc-title {
  display: block;
  padding: 2px 8px 8px;
  color: var(--color-text-secondary);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.dashboard-toc ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.toc-item {
  width: 100%;
  padding: 5px 8px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}
.toc-item:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.toc-item.active {
  background: var(--color-surface-selected);
  color: var(--color-navbar-text-active);
  font-weight: 600;
}
.anchor-target {
  scroll-margin-top: 12px;
}
.charts-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}
@media (max-width: 1100px) {
  .dashboard-toc {
    display: none;
  }
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
</style>
