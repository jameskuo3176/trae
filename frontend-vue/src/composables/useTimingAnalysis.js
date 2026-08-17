import { computed, ref } from 'vue'
import { normalizeTimingSections, summarizeTimingMetrics } from '@/utils/timing'

/**
 * 时序指标分析工具
 *
 * WNS(最差负时序裕量): 取所有路径组 WNS 值中的最小值。
 *   例如 SCUCLK_wns=-10、FUNCclk_WNS=-20 → 整体 WNS = -20。
 *
 * TNS(总负时序裕量): 对所有名称以 '_tns' 结尾的时序指标中取值为负的数值进行累加求和。
 *   取值 >= 0 的指标不纳入计算。即使不同路径组正负抵消后总和为正值，仍表示存在时序违例。
 *
 * 支持通过 scenario 和 path_group 筛选控制计算范围。
 *
 * @param {Function} getRecords - 返回当前选中记录数组的 getter 函数
 * @param {Object} selections - 可选的外部 scenario/path-group 响应式选择
 */
export function useTimingAnalysis(getRecords, selections = {}) {
  const selectedScenarios = selections.selectedScenarios || ref([])
  const selectedPathGroups = selections.selectedPathGroups || ref([])

  /** 归一化每条记录的时序数据: analysis → scenario → path_group → metrics */
  const normalized = computed(() => {
    const recs = getRecords() || []
    return recs.map(record => {
      const sections = normalizeTimingSections(record)
      return { record, sections }
    })
  })

  /** 所有可用的 scenario */
  const availableScenarios = computed(() => {
    const set = new Set()
    normalized.value.forEach(({ sections }) => {
      Object.values(sections).forEach(analysisData => {
        Object.keys(analysisData).forEach(s => set.add(s))
      })
    })
    return Array.from(set).sort()
  })

  /** 所有可用的 path_group */
  const availablePathGroups = computed(() => {
    const set = new Set()
    normalized.value.forEach(({ sections }) => {
      Object.values(sections).forEach(analysisData => {
        Object.values(analysisData).forEach(groups => {
          Object.keys(groups).forEach(g => set.add(g))
        })
      })
    })
    return Array.from(set).sort()
  })

  /** 判断某个 path_group 是否在当前筛选范围内 */
  function isGroupIncluded(scenario, pathGroup) {
    const scenarioMatch =
      selectedScenarios.value.length === 0 || selectedScenarios.value.includes(scenario)
    const groupMatch =
      selectedPathGroups.value.length === 0 || selectedPathGroups.value.includes(pathGroup)
    return scenarioMatch && groupMatch
  }

  function aggregateAnalysisNames(sections) {
    const names = Object.keys(sections)
    if (names.includes('default')) return ['default']
    if (names.includes('setup')) return ['setup']
    return names
  }

  function fingerprint(scenario, pathGroup, metrics) {
    return JSON.stringify([
      scenario,
      pathGroup,
      Object.entries(metrics).sort(([left], [right]) => left.localeCompare(right))
    ])
  }

  /** 遍历归一并筛选后的组；完全镜像的 timing section 只计一次。 */
  function* iterFilteredMetrics(normalizedEntry, analysisNames = Object.keys(normalizedEntry.sections)) {
    const seen = new Set()
    for (const analysis of analysisNames) {
      const analysisData = normalizedEntry.sections[analysis] || {}
      for (const [scenario, groups] of Object.entries(analysisData)) {
        for (const [pathGroup, metrics] of Object.entries(groups)) {
          if (!isGroupIncluded(scenario, pathGroup)) continue
          const key = fingerprint(scenario, pathGroup, metrics)
          if (seen.has(key)) continue
          seen.add(key)
          yield { analysis, scenario, pathGroup, metrics }
        }
      }
    }
  }

  /** 计算单条记录的 WNS: 所有路径组 WNS 中的最小值 */
  function computeWns(normalizedEntry) {
    let minWns = null
    const analyses = aggregateAnalysisNames(normalizedEntry.sections)
    for (const { metrics } of iterFilteredMetrics(normalizedEntry, analyses)) {
      for (const [key, value] of Object.entries(metrics)) {
        if (key !== 'wns' && !key.endsWith('_wns')) continue
        const wns = Number(value)
        if (Number.isFinite(wns) && (minWns === null || wns < minWns)) {
          minWns = wns
        }
      }
    }
    return minWns
  }

  /** 计算单条记录的 TNS: 累加所有以 _tns 结尾且值为负的指标 */
  function computeTns(normalizedEntry) {
    let total = 0
    let found = false
    const analyses = aggregateAnalysisNames(normalizedEntry.sections)
    for (const { metrics } of iterFilteredMetrics(normalizedEntry, analyses)) {
      for (const [key, value] of Object.entries(metrics)) {
        if (key !== 'tns' && !key.endsWith('_tns')) continue
        const tns = Number(value)
        if (!Number.isFinite(tns)) continue
        found = true
        if (tns < 0) total += tns
      }
    }
    return found ? total : null
  }

  function computeNvp(normalizedEntry) {
    let total = 0
    let found = false
    const analyses = aggregateAnalysisNames(normalizedEntry.sections)
    for (const { metrics } of iterFilteredMetrics(normalizedEntry, analyses)) {
      for (const [key, value] of Object.entries(metrics)) {
        if (key !== 'nvp' && !key.endsWith('_nvp')) continue
        const nvp = Number(value)
        if (!Number.isFinite(nvp)) continue
        found = true
        total += nvp
      }
    }
    return found ? total : null
  }

  /** 每条记录的计算结果 */
  const computedMetrics = computed(() => {
    return normalized.value.map(entry => ({
      record: entry.record,
      wns: computeWns(entry),
      tns: computeTns(entry),
      nvp: computeNvp(entry),
      aggregateAnalyses: aggregateAnalysisNames(entry.sections)
    }))
  })

  const groupDetails = computed(() =>
    normalized.value.map(entry => ({
      record: entry.record,
      groups: [...iterFilteredMetrics(entry)].map(group => ({
        ...group,
        summary: summarizeTimingMetrics(group.metrics)
      }))
    }))
  )

  /** 是否有可用的时序分层数据 */
  const hasTimingSections = computed(() => {
    return normalized.value.some(entry => Object.keys(entry.sections).length > 0)
  })

  function selectAllScenarios() {
    selectedScenarios.value = [...availableScenarios.value]
  }
  function clearScenarios() {
    selectedScenarios.value = []
  }
  function selectAllPathGroups() {
    selectedPathGroups.value = [...availablePathGroups.value]
  }
  function clearPathGroups() {
    selectedPathGroups.value = []
  }

  return {
    selectedScenarios,
    selectedPathGroups,
    availableScenarios,
    availablePathGroups,
    computedMetrics,
    groupDetails,
    hasTimingSections,
    selectAllScenarios,
    clearScenarios,
    selectAllPathGroups,
    clearPathGroups
  }
}