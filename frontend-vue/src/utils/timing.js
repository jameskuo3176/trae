const asObject = value => {
  if (!value) return {}
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
}

const metricName = name =>
  String(name)
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[-\s]+/g, '_')
    .replace(/_+/g, '_')
    .toLowerCase()

const GROUP_KEYS = ['path_groups', 'path_group', 'group_paths', 'group_path']

function timingGroups(value) {
  const source = asObject(value)
  for (const key of GROUP_KEYS) {
    const groups = asObject(source[key])
    if (Object.keys(groups).length) return groups
  }
  return source
}

function mergeGroup(result, analysis, scenario, group, values) {
  const metrics = Object.fromEntries(
    Object.entries(asObject(values))
      .filter(
        ([key, value]) =>
          !['source', 'path', 'scenarios', ...GROUP_KEYS].includes(key) &&
          typeof value !== 'object'
      )
      .map(([key, value]) => [metricName(key === 'period' ? 'clk_period' : key), value])
  )
  if (!Object.keys(metrics).length) return
  result[analysis] ||= {}
  result[analysis][scenario] ||= {}
  result[analysis][scenario][group] = { ...metrics, ...(result[analysis][scenario][group] || {}) }
}

function consumeAnalysis(result, analysis, source) {
  const value = asObject(source)
  const scenarios = asObject(value.scenarios)
  const entries = Object.keys(scenarios).length ? scenarios : value
  Object.entries(entries).forEach(([scenario, scenarioValue]) => {
    if (['source', 'status', 'metadata', 'warnings'].includes(scenario)) return
    const scenarioData = asObject(scenarioValue)
    const groups = timingGroups(scenarioData)
    Object.entries(groups).forEach(([group, metrics]) => {
      if (metrics && typeof metrics === 'object')
        mergeGroup(result, analysis, scenario, group, metrics)
    })
  })
}

export function normalizeTimingSections(record = {}) {
  const extra = asObject(record.extra_fields)
  const raw = asObject(record.raw_dc_report)
  const result = {}
  ;[record.timing_sections, extra.timing_sections].forEach(source =>
    Object.entries(asObject(source)).forEach(([analysis, value]) =>
      consumeAnalysis(result, analysis, value)
    )
  )
  Object.entries(asObject(raw.timing)).forEach(([analysis, value]) =>
    consumeAnalysis(result, analysis, value)
  )
  if (extra.timing_final) consumeAnalysis(result, 'final', extra.timing_final)
  if (!result.default) {
    if (extra.scenarios) consumeAnalysis(result, 'default', extra.scenarios)
  }
  const defaultGroups = new Set(
    Object.values(result.default || {}).flatMap(groups => Object.keys(groups))
  )
  ;[extra.path_groups, extra.clocks].forEach(source =>
    Object.entries(asObject(source)).forEach(([group, metrics]) => {
      if (defaultGroups.has(group)) return
      mergeGroup(result, 'default', 'default', group, metrics)
      defaultGroups.add(group)
    })
  )
  return result
}

export function summarizeTimingMetrics(metrics = {}) {
  const values = Object.entries(asObject(metrics))
  const wnsValues = values
    .filter(([key]) => key === 'wns' || key.endsWith('_wns'))
    .map(([, value]) => Number(value))
    .filter(Number.isFinite)
  const tnsValues = values
    .filter(([key]) => key === 'tns' || key.endsWith('_tns'))
    .map(([, value]) => Number(value))
    .filter(Number.isFinite)
  const nvpValues = values
    .filter(([key]) => key === 'nvp' || key.endsWith('_nvp'))
    .map(([, value]) => Number(value))
    .filter(Number.isFinite)
  return {
    wns: wnsValues.length ? Math.min(...wnsValues) : null,
    tns: tnsValues.length ? tnsValues.filter(value => value < 0).reduce((a, b) => a + b, 0) : null,
    nvp: nvpValues.length ? nvpValues.reduce((a, b) => a + b, 0) : null
  }
}

export const timingMetricLabel = key =>
  ({
    wns: 'WNS',
    tns: 'TNS',
    nvp: 'NVP',
    clk_period: 'Clk Period',
    lol: 'LoL'
  })[key] || key.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
