<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi } from '@/api/projects'
import { reviewApi } from '@/api/review'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ReviewDetailDialog from '@/components/review/ReviewDetailDialog.vue'
import ReviewDisplayPicker from '@/components/review/ReviewDisplayPicker.vue'
import ReviewEditorDialog from '@/components/review/ReviewEditorDialog.vue'
import ReviewHistoryPanel from '@/components/review/ReviewHistoryPanel.vue'
import ReviewAggregateMatrix from '@/components/review/ReviewAggregateMatrix.vue'
import ReviewModuleDetail from '@/components/review/ReviewModuleDetail.vue'
import SourceFileLink from '@/components/common/SourceFileLink.vue'
import TableFontSizeControl from '@/components/common/TableFontSizeControl.vue'
import RiskRatingControl from '@/components/common/RiskRatingControl.vue'

const projects = ref([])
const route = useRoute()
const router = useRouter()
const projectId = ref('')
const activeTab = ref(route.meta.reviewType || 'group')
const activeGroupId = ref('')
const overview = ref(null)
const livePreview = ref(false)
const reviews = ref([])
const loading = ref(false)
const error = ref('')
const viewMode = ref('aggregate')
const detailModuleId = ref(null)
const displayConfig = ref({
  sectionIds: [],
  metricIds: [],
  timingTypes: [],
  pathGroupIds: [],
  showAllPathGroups: false
})
const pickerOpen = ref(false)
const pickerDraft = ref({
  sectionIds: [],
  metricIds: [],
  timingTypes: [],
  pathGroupIds: [],
  showAllPathGroups: false
})
const columnWidths = ref({})
const resizeState = ref(null)
const reviewEditorOpen = ref(false)
const editingReview = ref(null)
const reviewSubmitting = ref(false)
const reviewEditorError = ref('')
const reviewDetailOpen = ref(false)
const reviewDetail = ref(null)
const reviewDetailLoading = ref(false)
const reviewDetailError = ref('')
const reviewAction = ref('')
const reviewComment = ref('')
const reviewActionSubmitting = ref(false)
const reviewForm = ref({
  title: '',
  summary: '',
  verdict: '',
  findings: '',
  decisions: '',
  nextSteps: ''
})
const riskSavingKey = ref('')

const COLUMN_WIDTHS_KEY = 'qor-review-aggregate-column-widths-v1'

const groups = computed(() => overview.value?.groups || [])
const activeGroup = computed(() => {
  if (activeTab.value === 'project') return null
  return (
    groups.value.find(group => String(group.id) === String(activeGroupId.value)) || groups.value[0]
  )
})
const visibleGroups = computed(() =>
  activeTab.value === 'project' ? groups.value : activeGroup.value ? [activeGroup.value] : []
)
const canCreateReview = computed(() => {
  if (!overview.value || overview.value.input_mode !== 'frozen') return false
  if (activeTab.value === 'project') {
    return Boolean(overview.value.capabilities?.can_create_project_review)
  }
  return Boolean(activeGroup.value?.can_create_review)
})
const renderedGroups = computed(() => {
  if (viewMode.value !== 'detail' || detailModuleId.value === null) return visibleGroups.value
  return visibleGroups.value.filter(group =>
    group.modules.some(module => module.module_id === detailModuleId.value)
  )
})

const statusLabel = status =>
  ({ draft: '草稿', submitted: '已提交', approved: '已批准', rejected: '已驳回' })[status] || status

const periodLabel = period => ({ weekly: '周评审', monthly: '月评审' })[period] || period || '-'

function starSourceLabel(module) {
  return (
    {
      explicit_weekly_upload: '已指定为本周评审 Run',
      explicit_weekly_release: '已指定为本周评审 Run',
      explicit_carried_forward: 'Release owner 指定的无更新沿用版本',
      carried_forward_latest_upload: '本周无数据更新，沿用最近上传版本',
      implicit_weekly_upload: '尚未手动星标，暂用本周最后上传 Run',
      implicit_weekly_release: '尚未手动星标，暂用本周最后上传 Run',
      user_pick: '用户指定评审版本'
    }[module.star_source] || '尚未手动星标，暂用本周最后上传 Run'
  )
}

function apiErrorMessage(error, fallback) {
  const apiError = error.response?.data?.error
  return apiError?.message || apiError || error.response?.data?.detail || error.message || fallback
}

function formatUploadTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(date)
}

const qorSections = [
  {
    title: '版本信息',
    fields: [
      ['version', 'Version'],
      ['tag', 'Tag'],
      ['version_description', '版本说明'],
      ['comment', '备注'],
      ['recorded_at', '上传时间'],
      ['is_released', '已发布'],
      ['released_at', '发布时间'],
      ['released_by', '发布人'],
      ['owner_id', 'Owner ID'],
      ['source_file', 'Source File'],
      ['full_dir', '完整目录'],
      ['release_dir_effective', 'Release 目录']
    ]
  },
  {
    title: 'Timing',
    fields: [
      ['wns_setup', 'Setup WNS'],
      ['tns_setup', 'Setup TNS'],
      ['nvp_setup', 'Setup NVP'],
      ['wns_hold', 'Hold WNS'],
      ['tns_hold', 'Hold TNS'],
      ['nvp_hold', 'Hold NVP'],
      ['target_frequency', '目标频率'],
      ['achieved_frequency', '实现频率']
    ]
  },
  {
    title: 'Area / Count',
    fields: [
      ['area_total', 'Total Area'],
      ['area_combinational', 'Combinational Area'],
      ['area_sequential', 'Sequential Area'],
      ['area_black_box', 'Black Box Area'],
      ['area_macro', 'Macro Area'],
      ['cell_count', 'Cell Count'],
      ['instance_count', 'Instance Count'],
      ['net_count', 'Net Count'],
      ['sequential_cell_count', 'Sequential Cell'],
      ['ram_cell_count', 'RAM Cell'],
      ['macro_cell_count', 'Macro Cell'],
      ['register_count', 'Register Count']
    ]
  },
  {
    title: 'Power',
    fields: [
      ['power_internal', 'Internal Power'],
      ['power_switching', 'Switching Power'],
      ['power_leakage', 'Leakage Power'],
      ['power_total', 'Total Power']
    ]
  },
  {
    title: 'Physical',
    fields: [
      ['mbb_ratio', 'MBB Ratio'],
      ['clock_gating_ratio', 'Clock Gating'],
      ['utilization', 'Utilization'],
      ['congestion', 'Congestion'],
      ['congestion_h', 'Congestion H'],
      ['congestion_v', 'Congestion V'],
      ['congestion_b', 'Congestion B']
    ]
  }
]
const displaySectionOptions = [...qorSections.map(section => section.title), 'Extra Fields']
const aggregateMetricOptions = [
  { id: 'wns', label: 'WNS', section: 'Timing' },
  { id: 'tns', label: 'TNS', section: 'Timing' },
  { id: 'nvp', label: 'NVP', section: 'Timing' },
  { id: 'period', label: 'Clk Period', section: 'Timing' },
  { id: 'lol', label: 'LoL', section: 'Timing' },
  { id: 'area_total', label: 'Total Area', section: 'Area / Count' },
  { id: 'cell_count', label: 'Cell Count', section: 'Area / Count' },
  { id: 'utilization', label: 'Utilization', section: 'Physical' },
  { id: 'power_total', label: 'Total Power', section: 'Power' }
]
const allAggregateMetricIds = aggregateMetricOptions.map(metric => metric.id)

const numericQorKeys = new Set(
  qorSections.slice(1).flatMap(section => section.fields.map(([key]) => key))
)

function formatMetricValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : value
}

function formatQorValue(record, key) {
  const value = record?.[key]
  if (value === null || value === undefined || value === '') return '-'
  if (numericQorKeys.has(key)) return formatMetricValue(value)
  if (key === 'recorded_at' || key === 'released_at') return formatUploadTime(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value)
  return value
}

function isSourcePathKey(key, value) {
  return (
    /^(source|source_file|full_dir|release_dir_effective)$/i.test(key) && typeof value === 'string'
  )
}

function extraQorFields(record) {
  return Object.entries(record?.extra_fields || {}).filter(
    ([key]) => !['scenarios', 'path_groups', 'timing_sections'].includes(key)
  )
}

function timingPathGroups(record) {
  const extra = record?.extra_fields || {}
  const groups = []
  const seen = new Set()
  const appendGroups = (timingType, scenario, source) => {
    if (!source || typeof source !== 'object') return
    const pathGroups = source.path_groups || source
    Object.entries(pathGroups).forEach(([name, metrics]) => {
      if (!metrics || typeof metrics !== 'object') return
      const hasMetric = ['WNS', 'wns', 'TNS', 'tns', 'NVP', 'nvp', 'period', 'Clk_Period'].some(
        key => Object.prototype.hasOwnProperty.call(metrics, key)
      )
      if (!hasMetric) return
      const group = {
        timingType,
        scenario,
        name,
        wns: metrics.WNS ?? metrics.wns,
        tns: metrics.TNS ?? metrics.tns,
        nvp: metrics.NVP ?? metrics.nvp,
        period: metrics.Clk_Period ?? metrics.clk_period ?? metrics.period,
        lol: metrics.LoL ?? metrics.lol
      }
      const id = pathGroupId(group)
      if (!seen.has(id)) {
        seen.add(id)
        groups.push(group)
      }
    })
  }

  const timingSections = record?.timing_sections || extra.timing_sections
  Object.entries(timingSections || {}).forEach(([timingType, scenarios]) => {
    if (!scenarios || typeof scenarios !== 'object') return
    Object.entries(scenarios).forEach(([scenario, source]) => {
      appendGroups(timingType, scenario, source)
    })
  })
  Object.entries(extra.scenarios || {}).forEach(([scenario, source]) =>
    appendGroups('default', scenario, source)
  )
  if (extra.path_groups) appendGroups('default', '', extra.path_groups)
  return groups
}

function pathGroupId(group) {
  return `${group.timingType || 'default'}::${group.scenario || ''}::${group.name}`
}

const availableTimingTypes = computed(() => {
  const types = []
  visibleGroups.value.forEach(group => {
    group.modules.forEach(module => {
      timingPathGroups(module.star).forEach(pathGroup => {
        if (!types.includes(pathGroup.timingType)) types.push(pathGroup.timingType)
      })
    })
  })
  return types
})

const allPathGroupOptions = computed(() => {
  const options = new Map()
  visibleGroups.value.forEach(group => {
    group.modules.forEach(module => {
      timingPathGroups(module.star).forEach(pathGroup => {
        const id = pathGroupId(pathGroup)
        if (!options.has(id)) options.set(id, { ...pathGroup, id })
      })
    })
  })
  return [...options.values()]
})

const hasTimingData = computed(
  () => availableTimingTypes.value.length > 0 && allPathGroupOptions.value.length > 0
)

function defaultTimingTypes(types) {
  if (types.includes('final')) return ['final']
  if (types.includes('default')) return ['default']
  return types.length ? [types[types.length - 1]] : []
}

function resetDisplayConfig() {
  const timingTypes = defaultTimingTypes(availableTimingTypes.value)
  displayConfig.value = {
    sectionIds: [...displaySectionOptions],
    metricIds: [...allAggregateMetricIds],
    timingTypes,
    pathGroupIds: allPathGroupOptions.value.map(option => option.id),
    showAllPathGroups: false
  }
}

function visibleQorSections() {
  return qorSections.filter(section => displayConfig.value.sectionIds.includes(section.title))
}

function isSectionVisible(title) {
  return displayConfig.value.sectionIds.includes(title)
}

function showExtraFields() {
  return displayConfig.value.sectionIds.includes('Extra Fields')
}

function visibleTimingPathGroups(module) {
  if (!isSectionVisible('Timing')) return []
  return timingPathGroups(module.star).filter(group => {
    if (!displayConfig.value.timingTypes.includes(group.timingType)) return false
    if (!displayConfig.value.pathGroupIds.includes(pathGroupId(group))) return false
    if (displayConfig.value.showAllPathGroups) return true
    const wns = Number(group.wns)
    return Number.isFinite(wns) && wns < 0
  })
}

const aggregateColumns = computed(() => {
  const columns = [
    {
      key: 'module',
      label: 'Module',
      group: 'Identity',
      className: 'sticky-module',
      width: 190,
      min: 130
    },
    {
      key: 'version',
      label: '评审版本',
      group: 'Identity',
      className: 'version-header',
      width: 220,
      min: 150
    }
  ]
  if (isSectionVisible('Timing')) {
    columns.push({
      key: 'path_group',
      label: hasTimingData.value ? 'Timing Type / Path Group' : 'Timing Status',
      group: 'Timing / Path Groups',
      className: 'timing-column',
      width: hasTimingData.value ? 210 : 190,
      min: 150
    })
    if (hasTimingData.value) {
      aggregateMetricOptions
        .filter(
          metric => metric.section === 'Timing' && displayConfig.value.metricIds.includes(metric.id)
        )
        .forEach(metric =>
          columns.push({
            key: metric.id,
            label: metric.label,
            group: 'Timing / Path Groups',
            className: 'metric-column',
            width: 96,
            min: 72
          })
        )
    }
  }
  aggregateMetricOptions
    .filter(
      metric =>
        metric.section !== 'Timing' &&
        isSectionVisible(metric.section) &&
        displayConfig.value.metricIds.includes(metric.id)
    )
    .forEach(metric =>
      columns.push({
        key: metric.id,
        label: metric.label,
        group: 'Implementation QoR',
        className: 'metric-column',
        width: 110,
        min: 80
      })
    )
  columns.push(
    { key: 'risk', label: '风险', group: 'Review Status / Actions', width: 230, min: 180 },
    { key: 'upload', label: '上传时间', group: 'Review Status / Actions', width: 150, min: 120 },
    { key: 'actions', label: '操作', group: 'Review Status / Actions', width: 126, min: 108 }
  )
  return columns
})

const aggregateColumnGroups = computed(() => {
  const groups = []
  aggregateColumns.value.forEach(column => {
    const current = groups[groups.length - 1]
    if (current?.label === column.group) current.count += 1
    else groups.push({ label: column.group, count: 1 })
  })
  return groups
})

const timingMetricColumns = computed(() =>
  aggregateColumns.value.filter(column =>
    ['wns', 'tns', 'nvp', 'period', 'lol'].includes(column.key)
  )
)
const implementationColumns = computed(() =>
  aggregateColumns.value.filter(column =>
    ['area_total', 'cell_count', 'utilization', 'power_total'].includes(column.key)
  )
)
const aggregateTableWidth = computed(() =>
  aggregateColumns.value.reduce((total, column) => total + columnWidth(column), 0)
)

function columnWidth(column) {
  return columnWidths.value[column.key] || column.width
}

function loadColumnWidths() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLUMN_WIDTHS_KEY) || '{}')
    if (!saved || typeof saved !== 'object') return
    columnWidths.value = Object.fromEntries(
      Object.entries(saved).filter(
        ([, value]) => Number.isFinite(value) && value >= 60 && value <= 800
      )
    )
  } catch {
    columnWidths.value = {}
  }
}

function saveColumnWidths() {
  try {
    localStorage.setItem(COLUMN_WIDTHS_KEY, JSON.stringify(columnWidths.value))
  } catch {
    // Storage can be disabled without affecting resizing.
  }
}

function beginResize(event, column) {
  if (event.button !== undefined && event.button !== 0) return
  event.preventDefault()
  resizeState.value = {
    key: column.key,
    startX: event.clientX,
    startWidth: columnWidth(column),
    min: column.min || 72
  }
  document.body.classList.add('is-resizing-review-table')
  document.addEventListener('pointermove', resizeColumn)
  document.addEventListener('pointerup', endResize)
}

function resizeColumn(event) {
  if (!resizeState.value) return
  const width = Math.max(
    resizeState.value.min,
    Math.min(800, resizeState.value.startWidth + event.clientX - resizeState.value.startX)
  )
  columnWidths.value = { ...columnWidths.value, [resizeState.value.key]: Math.round(width) }
}

function endResize() {
  if (!resizeState.value) return
  resizeState.value = null
  document.body.classList.remove('is-resizing-review-table')
  document.removeEventListener('pointermove', resizeColumn)
  document.removeEventListener('pointerup', endResize)
  saveColumnWidths()
}

function resizeColumnByKeyboard(event, column) {
  if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
  event.preventDefault()
  const direction = event.key === 'ArrowRight' ? 1 : -1
  columnWidths.value = {
    ...columnWidths.value,
    [column.key]: Math.max(column.min || 72, columnWidth(column) + direction * 10)
  }
  saveColumnWidths()
}

const aggregateModulesByGroup = computed(() => {
  const prepared = new Map()
  renderedGroups.value.forEach(group => {
    prepared.set(
      group.id,
      group.modules.map((module, moduleIndex) => {
        const pathGroups = visibleTimingPathGroups(module)
        return {
          module,
          isAlternate: moduleIndex % 2 === 1,
          pathGroupCount: pathGroups.length,
          pathGroups: pathGroups.length ? pathGroups : [null]
        }
      })
    )
  })
  return prepared
})

function aggregateModules(group) {
  return aggregateModulesByGroup.value.get(group.id) || []
}

function timingMetricClass(value) {
  if (value === null || value === undefined || value === '') return ''
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return number < 0 ? 'metric-negative' : 'metric-positive'
}

function openDisplayPicker() {
  pickerDraft.value = {
    sectionIds: [...displayConfig.value.sectionIds],
    metricIds: [...displayConfig.value.metricIds],
    timingTypes: [...displayConfig.value.timingTypes],
    pathGroupIds: [...displayConfig.value.pathGroupIds],
    showAllPathGroups: displayConfig.value.showAllPathGroups
  }
  pickerOpen.value = true
}

function closeDisplayPicker() {
  pickerOpen.value = false
}

function applyDisplayPicker() {
  displayConfig.value = {
    sectionIds: [...pickerDraft.value.sectionIds],
    metricIds: [...pickerDraft.value.metricIds],
    timingTypes: [...pickerDraft.value.timingTypes],
    pathGroupIds: [...pickerDraft.value.pathGroupIds],
    showAllPathGroups: pickerDraft.value.showAllPathGroups
  }
  closeDisplayPicker()
}

function setAllPickerOptions(key, values) {
  pickerDraft.value[key] = [...values]
}

onMounted(async () => {
  loadColumnWidths()
  projects.value = (await projectsApi.list()) || []
  if (projects.value.length) projectId.value = String(projects.value[0].id)
})

onBeforeUnmount(() => {
  endResize()
})

watch(projectId, () => {
  livePreview.value = false
  viewMode.value = 'aggregate'
  detailModuleId.value = null
  loadReviewData()
})
watch(activeTab, () => {
  detailModuleId.value = null
  viewMode.value = 'aggregate'
  if (overview.value) resetDisplayConfig()
  loadReviews()
})
watch(activeGroupId, () => {
  detailModuleId.value = null
  viewMode.value = 'aggregate'
  if (overview.value) resetDisplayConfig()
  if (activeTab.value === 'group') loadReviews()
})
watch(
  () => route.meta.reviewType,
  value => {
    if (value) activeTab.value = value
  }
)
watch(groups, value => {
  if (value.length && !value.some(group => String(group.id) === String(activeGroupId.value))) {
    activeGroupId.value = String(value[0].id)
  }
})

async function loadReviewData() {
  if (!projectId.value) return
  loading.value = true
  error.value = ''
  try {
    overview.value = await reviewApi.weekly({
      project_id: projectId.value,
      live_preview: livePreview.value || undefined
    })
    resetDisplayConfig()
    await loadReviews()
  } catch (e) {
    error.value = e.message || '评审数据加载失败'
  } finally {
    loading.value = false
  }
}

async function loadReviews() {
  if (!projectId.value) return
  const type = activeTab.value === 'project' ? 'project' : 'group'
  try {
    const params = { project_id: projectId.value }
    if (type === 'group' && activeGroup.value) params.group_name = activeGroup.value.name
    reviews.value = await reviewApi.list(type, params)
  } catch (e) {
    error.value = e.message || '评审列表加载失败'
  }
}

function setTab(tab) {
  router.push(tab === 'project' ? '/review/project' : '/review/group')
}

function showAggregate() {
  viewMode.value = 'aggregate'
  detailModuleId.value = null
}

function showModuleDetail(module) {
  detailModuleId.value = module.module_id
  viewMode.value = 'detail'
}

function showAllDetails() {
  detailModuleId.value = null
  viewMode.value = 'detail'
}

function detailModules(group) {
  if (detailModuleId.value === null) return group.modules
  return group.modules.filter(module => module.module_id === detailModuleId.value)
}

async function chooseStar(module, recordId) {
  if (overview.value?.is_frozen) {
    error.value = '该周评审输入已冻结，官方星标不可再修改'
    return
  }
  try {
    await reviewApi.selectStar({
      project_id: Number(projectId.value),
      module_id: module.module_id,
      record_id: String(recordId),
      week_start: overview.value.week_start
    })
    await loadReviewData()
  } catch (e) {
    error.value = e.message || '星标设置失败'
  }
}

async function toggleStar(module) {
  if (!module.star || !module.can_select_star) return
  if (!module.star_explicit) {
    await chooseStar(module, module.star.id)
    return
  }
  try {
    await reviewApi.clearStar({
      project_id: Number(projectId.value),
      module_id: module.module_id,
      record_id: String(module.star.id),
      week_start: overview.value.week_start
    })
    await loadReviewData()
  } catch (e) {
    error.value = apiErrorMessage(e, '取消星标失败')
  }
}

async function updateModuleRisk(module, rating) {
  if (!module.star || !module.risk?.can_edit) return
  const key = `${projectId.value}:${module.star.id}`
  riskSavingKey.value = key
  error.value = ''
  try {
    module.risk = rating
      ? await reviewApi.setRisk(projectId.value, module.star.id, rating)
      : await reviewApi.clearRisk(projectId.value, module.star.id)
  } catch (e) {
    error.value = apiErrorMessage(e, '风险等级保存失败')
  } finally {
    riskSavingKey.value = ''
  }
}

function visibleReviewModules() {
  return visibleGroups.value.flatMap(group => group.modules)
}

function buildReviewSuggestions() {
  const modules = visibleReviewModules()
  const riskModules = modules.filter(module =>
    ['high', 'medium'].includes(String(module.risk?.rating || '').toLowerCase())
  )
  const negativeGroups = modules.flatMap(module =>
    visibleTimingPathGroups(module)
      .filter(group => Number(group.wns) < 0)
      .map(
        group =>
          `${module.module_name} / ${group.timingType} / ${group.name} (${formatMetricValue(group.wns)})`
      )
  )
  const scope =
    activeTab.value === 'group' && activeGroup.value ? `${activeGroup.value.name} Group` : 'Project'

  return {
    title: `${overview.value?.week_start || ''} ${scope} 周评审`.trim(),
    summary: riskModules.length
      ? `本周 ${scope} 需重点关注 ${riskModules.map(module => module.module_name).join('、')} 的 QoR 风险。`
      : `本周 ${scope} QoR 数据已完成聚合检查，暂未发现中高风险模块。`,
    findings: [
      ...riskModules.map(module => `${module.module_name}：风险等级 ${module.risk.rating}`),
      ...negativeGroups.map(group => `负 WNS：${group}`)
    ].join('\n'),
    decisions: negativeGroups.length ? '优先推进负 WNS Path Group 的 timing closure。' : '',
    nextSteps: negativeGroups.length
      ? '跟踪相关模块 timing closure 进展。\n下次周评审复核 WNS/TNS 收敛情况。'
      : '持续监控下周 QoR 变化。',
    verdict: negativeGroups.length ? '建议聚焦负 WNS 路径并持续收敛' : ''
  }
}

function openReviewEditor(review = null) {
  reviewEditorError.value = ''
  editingReview.value = review
  reviewForm.value = review
    ? {
        title: review.title || '',
        summary: review.summary || '',
        verdict: review.verdict || '',
        findings: (review.findings || []).join('\n'),
        decisions: (review.decisions || []).join('\n'),
        nextSteps: (review.next_steps || []).join('\n')
      }
    : buildReviewSuggestions()
  reviewEditorOpen.value = true
}

function closeReviewEditor() {
  if (reviewSubmitting.value) return
  reviewEditorOpen.value = false
  editingReview.value = null
  reviewEditorError.value = ''
}

function linesToArray(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
}

async function saveReview() {
  if (!reviewForm.value.title.trim()) {
    reviewEditorError.value = '请输入评审标题'
    return
  }
  reviewSubmitting.value = true
  reviewEditorError.value = ''
  try {
    const payload = {
      project_id: Number(projectId.value),
      week_start: overview.value.week_start,
      period: 'weekly',
      title: reviewForm.value.title.trim(),
      summary: reviewForm.value.summary.trim(),
      verdict: reviewForm.value.verdict.trim(),
      findings: linesToArray(reviewForm.value.findings),
      decisions: linesToArray(reviewForm.value.decisions),
      next_steps: linesToArray(reviewForm.value.nextSteps)
    }
    if (activeTab.value === 'group') payload.group_name = activeGroup.value?.name
    const type = activeTab.value === 'project' ? 'project' : 'group'
    if (editingReview.value) {
      await reviewApi.update(
        editingReview.value.review_type || type,
        editingReview.value.id,
        editingReview.value.project_id,
        payload
      )
    } else {
      await reviewApi.create(type, payload)
    }
    reviewEditorOpen.value = false
    await loadReviews()
  } catch (e) {
    reviewEditorError.value = apiErrorMessage(e, '保存评审失败')
  } finally {
    reviewSubmitting.value = false
  }
}

async function createSnapshot() {
  try {
    await reviewApi.createSnapshot({
      project_id: Number(projectId.value),
      week_start: overview.value.week_start
    })
    livePreview.value = false
    await loadReviewData()
    alert('本周评审快照已冻结')
  } catch (e) {
    error.value = e.message || '快照创建失败'
  }
}

async function toggleLivePreview() {
  livePreview.value = !livePreview.value
  await loadReviewData()
}

async function openReviewDetail(review) {
  reviewDetailOpen.value = true
  reviewDetailLoading.value = true
  reviewDetailError.value = ''
  reviewAction.value = ''
  reviewComment.value = ''
  reviewDetail.value = null
  const type = review.review_type || (activeTab.value === 'project' ? 'project' : 'group')
  try {
    reviewDetail.value = await reviewApi.detail(type, review.id, review.project_id)
  } catch (e) {
    reviewDetailError.value = apiErrorMessage(e, '评审详情加载失败')
  } finally {
    reviewDetailLoading.value = false
  }
}

function closeReviewDetail() {
  if (reviewActionSubmitting.value) return
  reviewDetailOpen.value = false
  reviewDetail.value = null
  reviewDetailError.value = ''
  reviewAction.value = ''
}

function beginReviewAction(action) {
  reviewAction.value = action
  reviewDetailError.value = ''
}

async function submitDraft(review) {
  if (!review.can_submit) return
  const type = review.review_type || (activeTab.value === 'project' ? 'project' : 'group')
  try {
    await reviewApi.submit(type, review.id, review.project_id)
    await loadReviews()
  } catch (e) {
    error.value = apiErrorMessage(e, '评审提交失败')
  }
}

async function removeReview(review) {
  if (!review.can_delete) return
  if (!window.confirm(`确认删除草稿“${review.title}”？此操作不可撤销。`)) return
  const type = review.review_type || (activeTab.value === 'project' ? 'project' : 'group')
  try {
    await reviewApi.remove(type, review.id, review.project_id)
    await loadReviews()
  } catch (e) {
    error.value = apiErrorMessage(e, '评审删除失败')
  }
}

async function confirmReviewAction() {
  const review = reviewDetail.value
  if (!review || !reviewAction.value || reviewActionSubmitting.value) return
  reviewActionSubmitting.value = true
  reviewDetailError.value = ''
  const type = review.review_type || (activeTab.value === 'project' ? 'project' : 'group')
  try {
    await reviewApi.decide(
      type,
      review.id,
      review.project_id,
      reviewAction.value,
      reviewComment.value.trim()
    )
    reviewDetail.value = await reviewApi.detail(type, review.id, review.project_id)
    reviewAction.value = ''
    reviewComment.value = ''
    await loadReviews()
  } catch (e) {
    reviewDetailError.value = apiErrorMessage(e, '评审操作失败')
  } finally {
    reviewActionSubmitting.value = false
  }
}
</script>

<template>
  <div class="review-page">
    <div class="page-heading">
      <div>
        <h1>周评审中心</h1>
        <p v-if="overview" class="muted">
          {{ overview.week_start }} 至 {{ overview.week_end }} · {{ overview.timezone }}
        </p>
        <p v-if="overview?.is_frozen" class="frozen-notice">
          已冻结 · Snapshot {{ overview.snapshot.id }} ·
          {{ overview.snapshot.checksum.slice(0, 12) }}
        </p>
        <p v-else-if="overview?.frozen_snapshot" class="preview-notice">
          实时预览（不会修改已冻结的评审输入）
        </p>
      </div>
      <div class="heading-actions">
        <TableFontSizeControl />
        <select v-model="projectId">
          <option v-for="project in projects" :key="project.id" :value="String(project.id)">
            {{ project.name }}
          </option>
        </select>
        <button v-if="overview?.capabilities?.can_freeze" class="btn" @click="createSnapshot">
          冻结本周快照
        </button>
        <button
          v-if="overview?.is_frozen && overview.can_live_preview"
          class="btn"
          @click="toggleLivePreview"
        >
          查看实时预览
        </button>
        <button v-else-if="overview?.frozen_snapshot" class="btn" @click="toggleLivePreview">
          返回冻结输入
        </button>
        <button v-if="canCreateReview" class="btn btn-primary" @click="openReviewEditor()">
          创建评审
        </button>
      </div>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>
    <LoadingSpinner v-if="loading" text="加载本周 QoR..." />

    <template v-else-if="overview">
      <div class="tabs">
        <button :class="['tab-btn', { active: activeTab === 'group' }]" @click="setTab('group')">
          Group 评审
        </button>
        <button
          :class="['tab-btn', { active: activeTab === 'project' }]"
          @click="setTab('project')"
        >
          Project 评审
        </button>
      </div>

      <label v-if="activeTab === 'group'" class="group-filter">
        <span>Group 名称</span>
        <select v-model="activeGroupId" class="group-select">
          <option v-for="group in groups" :key="group.id" :value="String(group.id)">
            {{ group.name }}
          </option>
        </select>
      </label>

      <div class="review-view-controls">
        <button
          type="button"
          :class="['tab-btn', { active: viewMode === 'aggregate' }]"
          @click="showAggregate"
        >
          聚合视图
        </button>
        <button
          type="button"
          :class="['tab-btn', { active: viewMode === 'detail' && detailModuleId === null }]"
          @click="showAllDetails"
        >
          全部详情
        </button>
        <button
          type="button"
          class="display-picker-button global-picker-button"
          :disabled="!visibleGroups.length"
          @click="openDisplayPicker"
        >
          <span aria-hidden="true">#</span> pick 显示配置
        </button>
        <span v-if="viewMode === 'detail' && detailModuleId !== null" class="muted">
          当前仅显示所选 Module，点击“聚合视图”返回
        </span>
      </div>

      <ReviewAggregateMatrix
        v-for="group in renderedGroups"
        :key="group.id"
        class="group-section"
        :group-name="group.name"
        :owner-name="group.owner_username"
      >
        <div v-if="viewMode === 'aggregate'" class="aggregate-table-wrap">
          <table class="aggregate-table" :style="{ width: `${aggregateTableWidth}px` }">
            <colgroup>
              <col
                v-for="column in aggregateColumns"
                :key="column.key"
                :style="{ width: `${columnWidth(column)}px` }"
              />
            </colgroup>
            <thead>
              <tr class="header-groups">
                <th
                  v-for="columnGroup in aggregateColumnGroups"
                  :key="columnGroup.label"
                  :class="{
                    'identity-header': columnGroup.label === 'Identity',
                    'timing-header': columnGroup.label === 'Timing / Path Groups',
                    'implementation-header': columnGroup.label === 'Implementation QoR',
                    'review-header': columnGroup.label === 'Review Status / Actions'
                  }"
                  :colspan="columnGroup.count"
                  scope="colgroup"
                >
                  {{ columnGroup.label }}
                </th>
              </tr>
              <tr class="header-columns">
                <th
                  v-for="column in aggregateColumns"
                  :key="column.key"
                  :class="column.className"
                  scope="col"
                >
                  {{ column.label }}
                  <span
                    class="column-resize-handle"
                    role="separator"
                    tabindex="0"
                    :aria-label="`调整 ${column.label} 列宽`"
                    aria-orientation="vertical"
                    @pointerdown="beginResize($event, column)"
                    @keydown="resizeColumnByKeyboard($event, column)"
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              <template
                v-for="{ module, isAlternate, pathGroupCount, pathGroups } in aggregateModules(
                  group
                )"
                :key="module.module_id"
              >
                <tr
                  v-for="(pathGroup, pathIndex) in pathGroups"
                  :key="pathGroup ? pathGroupId(pathGroup) : 'empty'"
                  :class="[
                    'module-band-row',
                    {
                      'module-band-alt': isAlternate,
                      'module-band-start': pathIndex === 0
                    }
                  ]"
                >
                  <th
                    v-if="pathIndex === 0"
                    class="module-cell sticky-module"
                    scope="rowgroup"
                    :rowspan="pathGroups.length"
                    :title="module.module_name"
                  >
                    <strong>{{ module.module_name }}</strong>
                    <span v-if="pathGroupCount">
                      {{ pathGroupCount }} path group{{ pathGroupCount === 1 ? '' : 's' }}
                    </span>
                  </th>
                  <td v-if="pathIndex === 0" class="version-cell" :rowspan="pathGroups.length">
                    <div v-if="module.candidates.length" class="aggregate-version-control">
                      <button
                        type="button"
                        class="aggregate-star-button"
                        :disabled="!module.can_select_star"
                        :aria-label="
                          module.star_explicit ? '取消本周评审星标' : '设为本周评审星标'
                        "
                        :title="
                          module.star_explicit ? '点击取消本周评审星标' : '点击确认本周评审 Run'
                        "
                        @click="toggleStar(module)"
                      >
                        <span :class="['aggregate-star', { implicit: !module.star_explicit }]">
                          ★
                        </span>
                      </button>
                      <select
                        class="aggregate-version-select"
                        aria-label="评审版本"
                        :value="module.star?.id"
                        :disabled="!module.can_select_star"
                        :title="
                          String(module.star?.tag || module.star?.version || module.star?.id || '')
                        "
                        @change="chooseStar(module, $event.target.value)"
                      >
                        <option v-for="run in module.candidates" :key="run.id" :value="run.id">
                          {{ String(run.id) === String(module.star?.id) ? '★' : '☆' }}
                          {{ run.tag || run.version || run.id }}
                        </option>
                      </select>
                    </div>
                    <span v-else>-</span>
                  </td>
                  <td v-if="isSectionVisible('Timing')" class="path-group-cell">
                    <span v-if="!hasTimingData" class="timing-empty-state">
                      无 Timing / Path Group 数据
                    </span>
                    <strong v-else-if="pathGroup">{{ pathGroup.name }}</strong>
                    <span v-else class="timing-filter-empty">无匹配 Path Group</span>
                    <small v-if="pathGroup">
                      <b>{{ pathGroup.timingType }}</b>
                      <template v-if="pathGroup.scenario"> · {{ pathGroup.scenario }}</template>
                    </small>
                  </td>
                  <td
                    v-for="column in timingMetricColumns"
                    :key="column.key"
                    :class="['metric-cell', timingMetricClass(pathGroup?.[column.key])]"
                  >
                    {{ formatMetricValue(pathGroup?.[column.key]) }}
                  </td>
                  <td v-for="column in implementationColumns" :key="column.key" class="metric-cell">
                    {{ formatMetricValue(module.star?.[column.key]) }}
                  </td>
                  <td v-if="pathIndex === 0" class="risk-cell" :rowspan="pathGroups.length">
                    <RiskRatingControl
                      :risk="module.risk"
                      :disabled="!module.risk.can_edit"
                      :busy="riskSavingKey === `${projectId}:${module.star?.id}`"
                      @change="updateModuleRisk(module, $event)"
                    />
                  </td>
                  <td v-if="pathIndex === 0" class="upload-cell" :rowspan="pathGroups.length">
                    {{ formatUploadTime(module.upload_time) }}
                  </td>
                  <td v-if="pathIndex === 0" class="actions-cell" :rowspan="pathGroups.length">
                    <div class="aggregate-actions">
                      <button type="button" class="btn btn-sm" @click="showModuleDetail(module)">
                        详情
                      </button>
                    </div>
                  </td>
                </tr>
              </template>
              <tr v-if="!group.modules.length">
                <td class="aggregate-empty" :colspan="aggregateColumns.length">
                  当前 Group 暂无可评审 Module
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else class="module-grid">
          <ReviewModuleDetail
            v-for="module in detailModules(group)"
            :key="module.module_id"
            :module-name="module.module_name"
            :risk="module.risk.rating"
          >
            <div v-if="module.star" class="star-row">
              <span :class="['star', { implicit: !module.star_explicit }]">★</span>
              <div>
                <strong>{{ module.star.tag || module.star.version || module.star.id }}</strong>
                <div class="muted">
                  {{ starSourceLabel(module) }}
                </div>
                <div class="upload-time">上传时间：{{ formatUploadTime(module.upload_time) }}</div>
              </div>
            </div>
            <p v-else class="muted">暂无可用于评审的上传数据</p>

            <label v-if="module.candidates.length" class="star-picker version-control">
              <span>评审版本</span>
              <select
                :value="module.star?.id"
                :disabled="!module.can_select_star"
                @change="chooseStar(module, $event.target.value)"
              >
                <option v-for="run in module.candidates" :key="run.id" :value="run.id">
                  {{ String(run.id) === String(module.star?.id) ? '★' : '☆' }}
                  {{ run.tag || run.version || run.id }} · {{ formatUploadTime(run.recorded_at) }}
                  {{ run.is_released ? '· 已发布' : '· 未发布' }}
                </option>
              </select>
              <small v-if="module.candidate_limit_reached" class="muted">
                显示最近 100 个上传版本
              </small>
              <button
                v-if="module.can_select_star"
                type="button"
                class="btn btn-sm"
                @click="toggleStar(module)"
              >
                {{ module.star_explicit ? '★ 取消本周评审星标' : '★ 确认为本周评审 Run' }}
              </button>
            </label>

            <div v-if="module.star" class="qor-sections">
              <section
                v-for="section in visibleQorSections(module)"
                :key="section.title"
                class="qor-section"
              >
                <h3>{{ section.title }}</h3>
                <dl class="qor-data-grid">
                  <div v-for="[key, label] in section.fields" :key="key" class="qor-field">
                    <dt>{{ label }}</dt>
                    <dd
                      :title="
                        isSourcePathKey(key, module.star?.[key])
                          ? String(module.star[key])
                          : String(formatQorValue(module.star, key))
                      "
                    >
                      <SourceFileLink
                        v-if="isSourcePathKey(key, module.star?.[key])"
                        :path="module.star[key]"
                      />
                      <template v-else>{{ formatQorValue(module.star, key) }}</template>
                    </dd>
                  </div>
                </dl>
                <div
                  v-if="section.title === 'Timing' && visibleTimingPathGroups(module).length"
                  class="path-groups"
                >
                  <h4>Path Groups</h4>
                  <article
                    v-for="pathGroup in visibleTimingPathGroups(module)"
                    :key="`${pathGroup.scenario}:${pathGroup.name}`"
                    class="path-group-card"
                  >
                    <header>
                      <strong>{{ pathGroup.name }}</strong>
                      <span>
                        {{ pathGroup.timingType }}
                        <template v-if="pathGroup.scenario"> · {{ pathGroup.scenario }}</template>
                      </span>
                    </header>
                    <dl class="path-group-metrics">
                      <div>
                        <dt>WNS</dt>
                        <dd>{{ formatMetricValue(pathGroup.wns) }}</dd>
                      </div>
                      <div>
                        <dt>TNS</dt>
                        <dd>{{ formatMetricValue(pathGroup.tns) }}</dd>
                      </div>
                      <div>
                        <dt>NVP</dt>
                        <dd>{{ formatMetricValue(pathGroup.nvp) }}</dd>
                      </div>
                      <div>
                        <dt>Clk Period</dt>
                        <dd>{{ formatMetricValue(pathGroup.period) }}</dd>
                      </div>
                      <div>
                        <dt>LoL</dt>
                        <dd>{{ formatMetricValue(pathGroup.lol) }}</dd>
                      </div>
                    </dl>
                  </article>
                </div>
              </section>
              <section
                v-if="showExtraFields(module) && extraQorFields(module.star).length"
                class="qor-section"
              >
                <h3>Extra Fields</h3>
                <dl class="qor-data-grid">
                  <div
                    v-for="[key, value] in extraQorFields(module.star)"
                    :key="key"
                    class="qor-field"
                  >
                    <dt>{{ key }}</dt>
                    <dd :title="typeof value === 'object' ? JSON.stringify(value) : String(value)">
                      <SourceFileLink v-if="isSourcePathKey(key, value)" :path="value" />
                      <template v-else>{{
                        typeof value === 'object' ? JSON.stringify(value) : value
                      }}</template>
                    </dd>
                  </div>
                </dl>
              </section>
            </div>

            <ul v-if="module.risk.details?.length" class="risk-details">
              <li
                v-for="detail in module.risk.details"
                :key="`${detail.timing_type}:${detail.scenario}:${detail.path_group}`"
              >
                {{ detail.path_group }}: {{ detail.reason }}
              </li>
            </ul>
            <RiskRatingControl
              v-if="module.star"
              :risk="module.risk"
              :disabled="!module.risk.can_edit"
              :busy="riskSavingKey === `${projectId}:${module.star.id}`"
              @change="updateModuleRisk(module, $event)"
            />
          </ReviewModuleDetail>
        </div>
      </ReviewAggregateMatrix>

      <ReviewHistoryPanel
        :reviews="reviews"
        :review-type="activeTab"
        :status-label="statusLabel"
        @submit="submitDraft"
        @open="openReviewDetail"
        @edit="openReviewEditor"
        @remove="removeReview"
      />
    </template>

    <ReviewDisplayPicker
      :open="pickerOpen"
      :draft="pickerDraft"
      :sections="displaySectionOptions"
      :metrics="aggregateMetricOptions"
      :timing-types="availableTimingTypes"
      :path-groups="allPathGroupOptions"
      @close="closeDisplayPicker"
      @apply="applyDisplayPicker"
      @set-all="setAllPickerOptions"
    />

    <ReviewDetailDialog
      :open="reviewDetailOpen"
      :review="reviewDetail"
      :loading="reviewDetailLoading"
      :error="reviewDetailError"
      :action="reviewAction"
      :comment="reviewComment"
      :submitting="reviewActionSubmitting"
      :status-label="statusLabel"
      :period-label="periodLabel"
      :format-time="formatUploadTime"
      @close="closeReviewDetail"
      @begin-action="beginReviewAction"
      @cancel-action="reviewAction = ''"
      @confirm="confirmReviewAction"
      @update:comment="reviewComment = $event"
    />

    <ReviewEditorDialog
      :open="reviewEditorOpen"
      :form="reviewForm"
      :submitting="reviewSubmitting"
      :error="reviewEditorError"
      :scope="activeTab === 'project' ? 'Project' : activeGroup?.name || 'Group'"
      :week-start="overview?.week_start"
      :editing="Boolean(editingReview)"
      @close="closeReviewEditor"
      @submit="saveReview"
    />
  </div>
</template>

<style>
.review-page h1 {
  margin: 0;
  font-size: 24px;
}
.page-heading,
.heading-actions,
.tabs,
.module-card header,
.star-row,
.review-row,
.review-actions {
  display: flex;
  align-items: center;
}
.page-heading,
.module-card header,
.review-row {
  justify-content: space-between;
}
.page-heading {
  margin-bottom: 18px;
  gap: 16px;
}
.heading-actions,
.tabs,
.review-actions {
  gap: 8px;
}
.tabs {
  margin-bottom: 20px;
}
.tab-btn {
  padding: 9px 16px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
}
.tab-btn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.tab-btn.active {
  border-color: var(--color-primary);
  background: var(--color-surface-selected);
  color: var(--color-text-on-selected);
}
.group-select {
  min-width: 180px;
}
.group-filter {
  display: flex;
  align-items: center;
  gap: 10px;
  width: fit-content;
  margin: -8px 0 20px;
  font-size: 13px;
  font-weight: 600;
}
.group-filter .group-select {
  min-width: 240px;
  padding: 7px 10px;
}
.review-view-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
}
.group-section {
  margin-bottom: 24px;
}
.group-section h2 {
  margin-bottom: 2px;
}
.muted {
  color: var(--color-text-secondary);
  font-size: 12px;
}
.frozen-notice,
.preview-notice {
  margin: 5px 0 0;
  font-size: 12px;
  font-weight: 700;
}
.frozen-notice {
  color: var(--color-success);
}
.preview-notice {
  color: var(--color-warning);
}
.provenance-chip {
  display: inline-flex;
  margin-left: 8px;
  padding: 2px 7px;
  border: 1px solid color-mix(in srgb, var(--color-success) 55%, var(--color-border));
  border-radius: 4px;
  color: var(--color-success);
  font-size: 10px;
  font-weight: 700;
}
.provenance-chip.legacy {
  border-color: var(--color-warning);
  color: var(--color-warning);
}
.snapshot-provenance {
  padding: 14px;
  border-left: 4px solid var(--color-success);
  background: color-mix(in srgb, var(--color-success) 8%, var(--color-surface));
}
.snapshot-provenance.legacy {
  border-left-color: var(--color-warning);
  background: color-mix(in srgb, var(--color-warning) 8%, var(--color-surface));
}
.snapshot-provenance code {
  display: block;
  margin: 6px 0;
  overflow-wrap: anywhere;
  color: var(--color-text-secondary);
}
.aggregate-table-wrap {
  position: relative;
  isolation: isolate;
  margin-top: 12px;
  max-height: min(70vh, 760px);
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  box-shadow: 0 4px 14px color-mix(in srgb, var(--color-primary) 10%, transparent);
  scrollbar-color: var(--color-border) var(--color-surface-hover);
}
.aggregate-table {
  width: 100%;
  min-width: 100%;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  background: var(--color-surface);
  font-size: var(--table-font-size, 12px);
}
.aggregate-table th,
.aggregate-table td {
  box-sizing: border-box;
  height: 38px;
  padding: 7px 10px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  white-space: nowrap;
}
.aggregate-table thead th {
  position: sticky;
  z-index: 3;
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
  font-weight: 700;
}
.aggregate-table .header-groups th {
  top: 0;
  height: 32px;
  padding-block: 6px;
  border-top: 3px solid color-mix(in srgb, var(--color-primary) 62%, var(--color-border));
  border-bottom-color: color-mix(in srgb, var(--color-primary) 30%, var(--color-border));
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-primary));
  color: var(--color-text);
  font-size: 0.85em;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.aggregate-table .header-columns th {
  top: 32px;
  height: 38px;
  font-size: 0.92em;
  letter-spacing: 0.025em;
}
.aggregate-table .identity-header {
  left: 0;
  z-index: 14;
  border-top-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-surface) 91%, var(--color-primary));
}
.aggregate-table .timing-header,
.aggregate-table .timing-column {
  border-left: 3px solid color-mix(in srgb, var(--color-primary) 65%, var(--color-border));
}
.aggregate-table .timing-header {
  border-top-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-surface) 88%, var(--color-primary));
}
.aggregate-table .implementation-header,
.aggregate-table .review-header {
  background: color-mix(in srgb, var(--color-surface) 96%, var(--color-primary));
}
.aggregate-table .header-groups th:not(:last-child),
.aggregate-table .header-columns th:not(:last-child) {
  border-right: 1px solid var(--color-border);
}
.aggregate-table .sticky-module {
  position: sticky;
  left: 0;
  z-index: 10;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
  box-shadow: 8px 0 12px -12px var(--color-text);
}
.aggregate-table thead .sticky-module {
  z-index: 12;
  background: color-mix(in srgb, var(--color-surface) 91%, var(--color-primary));
}
.module-band-row > * {
  background: color-mix(in srgb, var(--color-surface) 98%, var(--color-primary));
}
.module-band-row.module-band-alt > * {
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-primary));
}
.module-band-row:hover > * {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.module-band-row:hover .sticky-module {
  background: var(--color-surface-hover);
}
.module-band-row:hover :is(.module-cell span, .path-group-cell small, .upload-cell) {
  color: var(--color-text-on-hover);
}
.module-band-row:hover .metric-negative {
  color: var(--color-danger);
}
.module-band-row:hover .metric-positive {
  color: var(--color-success);
}
.module-band-start > * {
  border-top: 2px solid color-mix(in srgb, var(--color-primary) 36%, var(--color-border));
}
.module-cell {
  vertical-align: top;
  color: var(--color-text);
}
.module-cell strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
}
.module-cell span {
  display: block;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.02em;
}
.version-cell,
.risk-cell,
.upload-cell,
.actions-cell {
  vertical-align: middle;
}
.version-header,
.version-cell {
  overflow: hidden;
}
.version-cell {
  position: relative;
  z-index: 0;
  overflow: hidden;
}
.path-group-cell {
  border-left: 3px solid color-mix(in srgb, var(--color-primary) 34%, var(--color-border));
}
.path-group-cell strong {
  display: block;
  color: var(--color-text);
  font-size: 11px;
}
.path-group-cell small {
  display: block;
  margin-top: 2px;
  color: var(--color-text-secondary);
  font-size: 9px;
  letter-spacing: 0.04em;
}
.timing-empty-state,
.timing-filter-empty {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.timing-empty-state::before {
  width: 5px;
  height: 5px;
  margin-right: 7px;
  border: 1px solid var(--color-primary);
  content: '';
}
.metric-column,
.metric-cell {
  text-align: right !important;
}
.metric-cell {
  color: var(--color-text);
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-variant-numeric: tabular-nums;
}
.metric-negative {
  color: var(--color-danger);
  font-weight: 700;
}
.metric-positive {
  color: var(--color-success);
  font-weight: 700;
}
.upload-cell {
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 10px;
}
.aggregate-empty {
  height: 96px !important;
  color: var(--color-text-secondary);
  text-align: center !important;
}
.aggregate-table :is(button, select):focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.aggregate-table .header-columns th {
  overflow: visible;
}
.column-resize-handle {
  position: absolute;
  z-index: 20;
  top: 0;
  right: -4px;
  bottom: 0;
  width: 9px;
  cursor: col-resize;
  touch-action: none;
}
.column-resize-handle::after {
  position: absolute;
  top: 25%;
  right: 3px;
  width: 2px;
  height: 50%;
  background: var(--color-primary);
  content: '';
  opacity: 0;
  transition: opacity 0.15s ease;
}
.header-columns th:hover .column-resize-handle::after,
.column-resize-handle:focus-visible::after {
  opacity: 0.8;
}
.column-resize-handle:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
}
:global(body.is-resizing-review-table) {
  cursor: col-resize;
  user-select: none;
}
.aggregate-version-select {
  display: block;
  width: 100%;
  max-width: 198px;
  padding: 5px 24px 5px 7px;
}
.aggregate-version-control {
  display: flex;
  align-items: center;
  gap: 6px;
}
.aggregate-star-button {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  padding: 2px;
  border: 0;
  background: transparent;
}
.aggregate-star-button:not(:disabled) {
  cursor: pointer;
}
.aggregate-star-button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.aggregate-star {
  flex: 0 0 auto;
  color: #2eea7a;
  font-size: 18px;
  line-height: 1;
  text-shadow: 0 0 8px color-mix(in srgb, #2eea7a 60%, transparent);
}
.aggregate-star.implicit {
  color: var(--color-text-muted);
}
.aggregate-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}
.module-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  margin-top: 12px;
}
.module-card {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 14px;
  background: var(--color-surface);
}
.risk {
  text-transform: uppercase;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
}
.risk-low {
  border: 1px solid var(--color-success-border);
  background: var(--color-success-background);
  color: var(--color-success);
}
.risk-medium {
  border: 1px solid var(--color-warning-border);
  background: var(--color-warning-background);
  color: var(--color-warning);
}
.risk-high {
  border: 1px solid var(--color-danger-border);
  background: var(--color-danger-background);
  color: var(--color-danger);
}
.risk-unrated {
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
}
.module-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.display-picker-button {
  padding: 4px 10px;
  border: 1px solid var(--color-primary);
  border-radius: 5px;
  background: transparent;
  color: var(--color-primary);
  font-weight: 700;
  cursor: pointer;
}
.display-picker-button:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.display-picker-button:disabled {
  opacity: 1;
  cursor: not-allowed;
}
.global-picker-button {
  margin-left: 6px;
  padding: 8px 12px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-primary));
}
.global-picker-button span {
  margin-right: 2px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.star-row {
  gap: 9px;
  margin: 14px 0;
}
.star {
  color: #2eea7a;
  font-size: 24px;
  text-shadow: 0 0 8px color-mix(in srgb, #2eea7a 60%, transparent);
}
.star.implicit {
  color: var(--color-text-muted);
}
.upload-time {
  margin-top: 3px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.star-picker {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.version-control {
  margin: 12px 0 18px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-hover);
  font-weight: 600;
}
.version-control select {
  width: 100%;
  padding: 8px 10px;
}
.qor-sections {
  display: grid;
  gap: 16px;
}
.qor-section {
  padding-top: 12px;
  border-top: 1px solid var(--color-border);
}
.qor-section h3 {
  margin: 0 0 10px;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.qor-data-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-border);
}
.qor-field {
  min-width: 0;
  padding: 8px 10px;
  background: var(--color-surface);
}
.qor-field dt {
  margin-bottom: 3px;
  color: var(--color-text-secondary);
  font-size: 11px;
}
.qor-field dd {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--color-text);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}
.path-groups {
  margin-top: 14px;
}
.path-groups h4 {
  margin: 0 0 8px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.path-group-card {
  margin-top: 8px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 6px;
}
.path-group-card header {
  justify-content: flex-start;
  gap: 10px;
  padding: 8px 10px;
  background: var(--color-surface-hover);
}
.path-group-card header span {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.path-group-metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 0;
}
.path-group-metrics > div {
  padding: 9px 10px;
  border-right: 1px solid var(--color-border);
}
.path-group-metrics > div:last-child {
  border-right: 0;
}
.path-group-metrics dt {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.path-group-metrics dd {
  margin: 3px 0 0;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 13px;
}
.display-picker-mask {
  position: fixed;
  z-index: 1200;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: var(--color-overlay);
}
.display-picker {
  width: min(980px, 100%);
  max-height: min(720px, 90vh);
  overflow: auto;
  border: 1px solid color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
  border-top: 4px solid var(--color-primary);
  border-radius: 4px;
  background: var(--color-surface);
  box-shadow: 0 18px 48px var(--color-shadow);
}
.display-picker > header,
.display-picker > footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
}
.display-picker > header {
  border-bottom: 1px solid var(--color-border);
}
.display-picker > header h2 {
  margin: 0;
  font-size: 18px;
}
.display-picker > header p {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.picker-close {
  border: 0;
  background: transparent;
  color: var(--color-text);
  font-size: 24px;
  cursor: pointer;
}
.display-picker-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  padding: 18px;
}
.display-picker fieldset {
  display: grid;
  align-content: start;
  gap: 8px;
  min-width: 0;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 7px;
}
.display-picker legend {
  padding: 0 5px;
  font-weight: 700;
}
.display-picker fieldset label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.display-picker fieldset label:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.display-picker fieldset label:hover small {
  color: inherit;
}
.display-picker fieldset small {
  margin-left: 5px;
  color: var(--color-text-secondary);
}
.dialog-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.16em;
}
.picker-subsection {
  display: grid;
  gap: 7px;
  margin-top: 7px;
  padding-top: 10px;
  border-top: 1px solid var(--color-border);
}
.picker-subsection > strong {
  color: var(--color-text-secondary);
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.path-group-filter-setting label {
  align-items: flex-start !important;
}
.path-group-options {
  max-height: 410px;
  overflow: auto;
}
.picker-mini-actions {
  display: flex;
  gap: 6px;
  margin-bottom: 3px;
}
.picker-mini-actions button {
  padding: 3px 9px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface-hover);
  color: var(--color-text);
  cursor: pointer;
}
.picker-mini-actions button:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-active);
  color: var(--color-text-on-hover);
}
.display-picker > footer {
  border-top: 1px solid var(--color-border);
}
.display-picker > footer > div {
  display: flex;
  gap: 8px;
}
.review-editor {
  width: min(920px, 100%);
  max-height: min(860px, 92vh);
  overflow: auto;
  border: 1px solid color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
  border-top: 4px solid var(--color-primary);
  border-radius: 4px;
  background: var(--color-surface);
  box-shadow: 0 20px 54px var(--color-shadow);
}
.review-editor > header,
.review-editor > footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
}
.review-editor > header {
  border-bottom: 1px solid var(--color-border);
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-primary));
}
.review-editor > header h2 {
  margin: 0;
  font-size: 20px;
}
.review-editor > header p {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.review-editor-body {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
  padding: 20px;
}
.editor-field {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: var(--color-text);
  font-size: 12px;
  font-weight: 700;
}
.editor-field-wide {
  grid-column: 1 / -1;
}
.editor-field span {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.editor-field span b {
  color: var(--color-danger);
}
.editor-field span small {
  color: var(--color-text-secondary);
  font-weight: 500;
}
.editor-field :is(input, textarea) {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--color-input-border);
  border-radius: 3px;
  background: var(--color-input-background);
  color: var(--color-input-text);
  font: inherit;
  font-weight: 400;
}
.editor-field input {
  height: 38px;
  padding: 8px 10px;
}
.editor-field textarea {
  min-height: 96px;
  padding: 9px 10px;
  line-height: 1.5;
  resize: vertical;
}
.editor-field :is(input, textarea):focus-visible {
  border-color: var(--color-focus-ring);
  outline: 2px solid var(--color-focus-ring);
  outline-offset: 1px;
}
.editor-error {
  grid-column: 1 / -1;
  margin: 0;
  padding: 9px 10px;
  border-left: 3px solid var(--color-danger-border);
  background: var(--color-danger-background);
  color: var(--color-danger);
  font-size: 12px;
}
.review-editor > footer {
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-hover);
}
.review-editor > footer > div {
  display: flex;
  gap: 8px;
}
.editor-scope {
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
}
.risk-details {
  padding-left: 18px;
  font-size: 11px;
  color: var(--color-text-secondary);
}
.review-list {
  margin-top: 20px;
}
.review-row {
  min-height: 44px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border);
  gap: 12px;
}
.review-row strong {
  margin-right: 8px;
}
.status {
  font-size: 12px;
}
.review-waiting {
  max-width: 190px;
  color: var(--color-text-secondary);
  font-size: 11px;
  text-align: right;
}
.review-detail-button {
  border: 1px solid var(--color-primary);
  background: transparent;
  color: var(--color-primary);
  font-weight: 700;
}
.review-detail-button:hover {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--color-primary);
  border-color: var(--color-primary);
}
.btn-success {
  background: var(--color-success);
  color: var(--color-success-background);
}
.btn-danger {
  background: var(--color-danger);
  color: var(--color-danger-background);
}
.review-detail-dialog {
  width: min(920px, 100%);
  max-height: min(880px, 94vh);
  overflow: auto;
  border: 1px solid color-mix(in srgb, var(--color-primary) 55%, var(--color-border));
  border-top: 4px solid var(--color-primary);
  border-radius: 4px;
  background: var(--color-surface);
  box-shadow: 0 22px 60px var(--color-shadow);
}
.review-detail-dialog > header,
.review-detail-dialog > footer {
  position: sticky;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  background: var(--color-surface);
}
.review-detail-dialog > header {
  top: 0;
  border-bottom: 1px solid var(--color-border);
}
.review-detail-dialog > footer {
  bottom: 0;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-hover);
}
.review-detail-dialog > footer > div {
  display: flex;
  gap: 8px;
}
.review-detail-dialog > header h2 {
  margin: 0;
  font-size: 20px;
}
.review-detail-dialog > header p {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.review-detail-body {
  display: grid;
  gap: 18px;
  padding: 20px;
}
.review-detail-meta {
  border-left: 4px solid var(--color-primary);
  background: color-mix(in srgb, var(--color-surface) 94%, var(--color-primary));
}
.review-detail-meta dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
}
.review-detail-meta dl > div {
  min-width: 0;
  padding: 12px 14px;
  border-right: 1px solid var(--color-border);
}
.review-detail-meta dt,
.review-timeline time {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.review-detail-meta dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
  font-size: 13px;
  font-weight: 700;
}
.review-evidence-section,
.review-timeline-section,
.review-outcome {
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
}
.review-detail-body h3 {
  margin: 0 0 9px;
  color: var(--color-text-secondary);
  font-size: 11px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.review-evidence-section p {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.65;
}
.review-evidence-section ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.review-evidence-section li {
  display: grid;
  grid-template-columns: minmax(110px, 0.25fr) minmax(0, 1fr);
  gap: 12px;
  padding: 8px 10px;
  border-left: 2px solid var(--color-border-strong);
  background: var(--color-surface-hover);
  line-height: 1.5;
}
.review-evidence-section li > span {
  overflow-wrap: anywhere;
}
.review-verdict {
  padding: 14px;
  border: 1px solid var(--color-primary);
  background: color-mix(in srgb, var(--color-surface) 95%, var(--color-primary));
}
.review-timeline {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
  padding: 0;
  list-style: none;
}
.review-timeline li {
  position: relative;
  min-width: 0;
  padding: 0 12px 0 18px;
}
.review-timeline li::before {
  position: absolute;
  top: 6px;
  right: 50%;
  left: 0;
  height: 1px;
  background: var(--color-border);
  content: '';
}
.review-timeline li:first-child::before {
  display: none;
}
.timeline-marker {
  position: absolute;
  z-index: 1;
  top: 2px;
  left: 0;
  width: 9px;
  height: 9px;
  border: 2px solid var(--color-border-strong);
  background: var(--color-surface);
}
.review-timeline li.complete .timeline-marker {
  border-color: var(--color-primary);
  background: var(--color-primary);
}
.review-timeline strong,
.review-timeline time {
  display: block;
}
.review-timeline time {
  margin-top: 4px;
  overflow-wrap: anywhere;
}
.review-outcome p {
  margin: 0;
}
.review-outcome blockquote {
  margin: 10px 0 0;
  padding: 10px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--color-surface-hover);
  white-space: pre-wrap;
}
.review-waiting-panel {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-left: 4px solid var(--color-warning);
  background: var(--color-warning-background);
  color: var(--color-warning);
}
.review-decision-form {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface-hover);
}
.review-decision-form label {
  display: grid;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
}
.review-decision-form label span {
  display: flex;
  justify-content: space-between;
}
.review-decision-form textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--color-input-border);
  background: var(--color-input-background);
  color: var(--color-input-text);
  resize: vertical;
}
.review-decision-form > div {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.review-detail-load-error {
  margin: 28px;
  padding: 14px;
  border-left: 3px solid var(--color-danger);
  background: var(--color-danger-background);
  color: var(--color-danger);
}
@media (max-width: 720px) {
  .page-heading {
    align-items: stretch;
    flex-direction: column;
  }
  .heading-actions,
  .tabs {
    flex-wrap: wrap;
  }
  .qor-data-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .path-group-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .display-picker-grid {
    grid-template-columns: 1fr;
  }
  .column-resize-handle {
    visibility: hidden;
    pointer-events: none;
  }
  .review-editor-body {
    grid-template-columns: 1fr;
  }
  .editor-field-wide {
    grid-column: auto;
  }
  .review-editor > footer {
    align-items: stretch;
    flex-direction: column;
  }
  .review-row,
  .review-actions,
  .review-detail-dialog > footer {
    align-items: stretch;
    flex-direction: column;
  }
  .review-actions {
    width: 100%;
  }
  .review-waiting {
    max-width: none;
    text-align: left;
  }
  .review-detail-meta dl,
  .review-timeline {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .review-evidence-section li {
    grid-template-columns: 1fr;
    gap: 3px;
  }
}
</style>
