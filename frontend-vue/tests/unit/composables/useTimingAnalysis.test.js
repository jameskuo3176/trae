import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useTimingAnalysis } from '@/composables/useTimingAnalysis'

const timingRecord = {
  id: 'run-1',
  raw_dc_report: {
    timing: {
      final: {
        scenarios: {
          slow: {
            path_groups: {
              SCUCLK: {
                SCUCLK_WNS: -10,
                SCUCLK_TNS: -30,
                recovery_tns: 12
              },
              FUNCclk: {
                FUNCclk_WNS: '-20',
                FUNCclk_TNS: -40
              }
            }
          },
          fast: {
            path_groups: {
              IOCLK: {
                IOCLK_WNS: -2,
                IOCLK_TNS: -3,
                removal_tns: 8
              }
            }
          }
        }
      }
    }
  }
}

describe('useTimingAnalysis', () => {
  it('takes the minimum suffixed WNS and sums only negative suffixed TNS values', () => {
    const records = ref([timingRecord])
    const analysis = useTimingAnalysis(() => records.value)

    expect(analysis.computedMetrics.value[0].wns).toBe(-20)
    expect(analysis.computedMetrics.value[0].tns).toBe(-73)
    expect(analysis.availableScenarios.value).toEqual(['fast', 'slow'])
    expect(analysis.availablePathGroups.value).toEqual(['FUNCclk', 'IOCLK', 'SCUCLK'])
  })

  it('recomputes within selected scenario and path-group scopes', () => {
    const analysis = useTimingAnalysis(() => [timingRecord])

    analysis.selectedScenarios.value = ['slow']
    expect(analysis.computedMetrics.value[0].wns).toBe(-20)
    expect(analysis.computedMetrics.value[0].tns).toBe(-70)

    analysis.selectedPathGroups.value = ['SCUCLK']
    expect(analysis.computedMetrics.value[0].wns).toBe(-10)
    expect(analysis.computedMetrics.value[0].tns).toBe(-30)
  })

  it('does not double-count legacy scenarios and clocks mirrored by timing sections', () => {
    const groups = {
      CORECLK: { wns: -15.75, tns: -220.5 },
      BUSCLK: { wns: -6.2, tns: -44.8 }
    }
    const analysis = useTimingAnalysis(() => [
      {
        id: 'converted-run',
        extra_fields: {
          timing_sections: { default: { slow: groups } },
          scenarios: { slow: groups },
          clocks: groups
        }
      }
    ])

    expect(analysis.computedMetrics.value[0].tns).toBeCloseTo(-265.3)
    expect(analysis.availableScenarios.value).toEqual(['slow'])
  })

  it('uses default timing as the aggregate source while retaining other analyses as details', () => {
    const analysis = useTimingAnalysis(() => [
      {
        id: 'multi-analysis',
        raw_dc_report: {
          timing: {
            default: {
              scenarios: {
                slow: {
                  path_group: {
                    CORECLK: { WNS: -10, TNS: -30, NVP: 3 },
                    BUSCLK: { WNS: -4, TNS: -7, NVP: 1 }
                  }
                }
              }
            },
            final: {
              scenarios: {
                slow: {
                  group_path: {
                    CORECLK: { WNS: -2, TNS: -5, NVP: 1 }
                  }
                }
              }
            }
          }
        }
      }
    ])

    expect(analysis.computedMetrics.value[0]).toMatchObject({
      wns: -10,
      tns: -37,
      nvp: 4,
      aggregateAnalyses: ['default']
    })
    expect(analysis.groupDetails.value[0].groups).toHaveLength(3)
  })

  it('deduplicates mirrored sections and returns null aggregates when filters match no groups', () => {
    const groups = { CORECLK: { wns: -5, tns: -9 } }
    const analysis = useTimingAnalysis(() => [
      {
        id: 'mirrored',
        timing_sections: {
          default: { slow: groups },
          mirror: { slow: groups }
        }
      }
    ])

    expect(analysis.groupDetails.value[0].groups).toHaveLength(1)
    expect(analysis.computedMetrics.value[0].tns).toBe(-9)

    analysis.selectedPathGroups.value = ['MISSING']
    expect(analysis.computedMetrics.value[0].wns).toBeNull()
    expect(analysis.computedMetrics.value[0].tns).toBeNull()
    expect(analysis.groupDetails.value[0].groups).toEqual([])
  })
})
