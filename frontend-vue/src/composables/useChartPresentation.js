import { computed, inject } from 'vue'
import { useFiltersStore } from '@/stores/filters'

const fallbackSettings = {
  orientation: computed(() => 'vertical'),
  height: computed(() => null),
  labelMode: computed(() => 'both'),
  chartType: computed(() => 'bar'),
  tableWidth: computed(() => 0),
  tableFontSize: computed(() => 12)
}

/**
 * 生成运行记录标签。
 * context = { projectCount, moduleCount } 用于动态省略冗余维度：
 * - 仅选择一个项目时省略项目名称
 * - 仅选择一个模块时同时省略项目名称和模块名称，仅保留时间维度
 * 未传入 context（非仪表盘场景）时保持完整信息。
 */
export function formatRunLabel(record, mode = 'both', context) {
  const project = record?.project_name || ''
  const module = record?.module_name || record?.module || 'Module'
  const tag = record?.tag || record?.version || `#${record?.id ?? '-'}`
  const directory = record?.full_dir || record?.release_dir_effective || record?.release_dir || ''

  if (mode === 'module') return module
  if (mode === 'tag') return tag
  if (mode === 'module_tag_dir') {
    const compactDir = directory.length > 42 ? `…${directory.slice(-41)}` : directory
    return [module, tag, compactDir].filter(Boolean).join(' · ')
  }
  // 未传入上下文或筛选未明确指定（0/多选）时展示完整维度
  const showProject = !context || context.projectCount !== 1
  const showModule = !context || context.moduleCount !== 1
  const parts = []
  if (showProject) parts.push(project)
  if (showModule) parts.push(module)
  parts.push(tag)
  return parts.filter(Boolean).join(' · ')
}

/** 读取当前仪表盘筛选状态，生成随选择变化的动态运行标签。 */
export function useRunLabelContext() {
  const filters = useFiltersStore()
  const projectCount = computed(() => filters.projectIds.length)
  const moduleCount = computed(() => filters.moduleIds.length)
  const runLabel = (record, mode = 'both') =>
    formatRunLabel(record, mode, {
      projectCount: projectCount.value,
      moduleCount: moduleCount.value
    })
  return { projectCount, moduleCount, runLabel }
}

function clone(value) {
  if (Array.isArray(value)) return value.map(clone)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, nested]) => [key, clone(nested)]))
  }
  return value
}

function scalarAxis(axis) {
  return Array.isArray(axis) ? axis[0] || {} : axis || {}
}

export function useChartPresentation(props) {
  const settings = inject('chartSettings', fallbackSettings)
  const orientation = computed(() => settings.orientation?.value || 'vertical')
  const chartType = computed(() => settings.chartType?.value || 'bar')
  const labelMode = computed(() => settings.labelMode?.value || 'both')
  const tableWidth = computed(() => Number(settings.tableWidth?.value) || 0)
  const tableFontSize = computed(() => Number(settings.tableFontSize?.value) || 12)
  const { runLabel } = useRunLabelContext()
  const height = computed(() => {
    const configured = Number(settings.height?.value)
    if (configured) return `${configured}px`
    return typeof props.height === 'number' ? `${props.height}px` : props.height
  })

  const runLabels = computed(() =>
    (props.records || []).map(record => runLabel(record, labelMode.value))
  )

  const option = computed(() => {
    const next = clone(props.option || {})
    const series = (next.series || []).map(item => {
      if (item.type === 'pie') return item
      if (chartType.value === 'line') {
        return {
          ...item,
          type: 'line',
          showSymbol: true,
          symbolSize: item.symbolSize || 7,
          lineStyle: { width: 2, ...(item.lineStyle || {}) }
        }
      }
      return { ...item, type: 'bar' }
    })
    next.series = series

    const originalX = scalarAxis(next.xAxis)
    const originalY = scalarAxis(next.yAxis)
    const originalCategory = originalX.type === 'category' ? originalX : originalY
    const originalValue = originalX.type === 'value' ? originalX : originalY
    if (!originalCategory.type) return next

    const categories =
      runLabels.value.length === (originalCategory.data || []).length
        ? runLabels.value
        : originalCategory.data || []
    const horizontal = orientation.value === 'horizontal'
    const dense = categories.length > 6
    const categoryAxis = {
      ...originalCategory,
      type: 'category',
      data: categories,
      axisLabel: {
        ...(originalCategory.axisLabel || {}),
        rotate: !horizontal && dense ? 30 : 0,
        hideOverlap: true,
        overflow: 'truncate',
        ellipsis: '…',
        width: horizontal ? 220 : dense ? 110 : undefined
      }
    }
    const valueAxis = { ...originalValue, type: 'value' }
    next.grid = {
      ...(next.grid || {}),
      left: horizontal ? 18 : next.grid?.left,
      right: next.grid?.right ?? 24,
      containLabel: true
    }
    if (horizontal) {
      next.xAxis = valueAxis
      next.yAxis = categoryAxis
    } else {
      next.xAxis = categoryAxis
      next.yAxis = valueAxis
    }
    return next
  })

  const table = computed(() => {
    const presented = option.value
    const pie = (presented.series || []).find(series => series.type === 'pie')
    if (pie) {
      return {
        columns: ['Category', 'Value'],
        rows: (pie.data || []).map(item => ({
          category: item?.name ?? 'Metric',
          values: [item?.value ?? null]
        }))
      }
    }

    const xAxis = scalarAxis(presented.xAxis)
    const yAxis = scalarAxis(presented.yAxis)
    const categoryAxis = xAxis.type === 'category' ? xAxis : yAxis
    const series = (presented.series || []).filter(item => item.type !== 'pie')
    return {
      columns: ['Run', ...series.map((item, index) => item.name || `Series ${index + 1}`)],
      rows: (categoryAxis.data || []).map((category, index) => ({
        category,
        values: series.map(item => {
          const point = item.data?.[index]
          return point && typeof point === 'object' && 'value' in point ? point.value : point
        })
      }))
    }
  })

  return {
    chartType,
    height,
    labelMode,
    option,
    orientation,
    runLabels,
    table,
    tableWidth,
    tableFontSize
  }
}
