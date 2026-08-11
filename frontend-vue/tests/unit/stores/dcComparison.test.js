import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDcComparisonStore } from '@/stores/dcComparison'

describe('DC comparison store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('keeps picker edits as drafts until Apply', () => {
    const store = useDcComparisonStore()
    store.open(['record-a'])
    store.draft.runIds.push('record-b')
    store.draft.sortMetric = 'TNS'
    store.draft.showChange = false
    store.draft.vsMode = true
    store.cancel()
    expect(store.preferences.runIds).toEqual([])
    expect(store.preferences.sortMetric).toBe('WNS')
    expect(store.preferences.showChange).toBe(true)
    expect(store.preferences.vsMode).toBe(false)
  })

  it('applies picker draft and closes the dialog', () => {
    const store = useDcComparisonStore()
    store.open(['record-a'])
    store.draft.metricIds = ['timing.WNS']
    store.draft.sortMetric = 'NVP'
    store.draft.showChange = false
    store.draft.vsMode = true
    store.apply()
    expect(store.preferences.runIds).toEqual(['record-a'])
    expect(store.preferences.metricIds).toEqual(['timing.WNS'])
    expect(store.preferences.sortMetric).toBe('NVP')
    expect(store.preferences.showChange).toBe(false)
    expect(store.preferences.vsMode).toBe(true)
    expect(store.pickerOpen).toBe(false)
  })
})
