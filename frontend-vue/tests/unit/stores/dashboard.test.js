import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDashboardStore } from '@/stores/dashboard'

describe('Dashboard Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initial state has empty records', () => {
    const store = useDashboardStore()
    expect(store.records).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.selectedIds.size).toBe(0)
  })

  it('setRecords updates records', () => {
    const store = useDashboardStore()
    store.setRecords([
      { id: 1, name: 'r1' },
      { id: 2, name: 'r2' }
    ])
    expect(store.records).toHaveLength(2)
  })

  it('toggleSelect adds and removes', () => {
    const store = useDashboardStore()
    store.setRecords([{ id: 1 }, { id: 2 }])
    store.toggleSelect(1)
    expect(store.selectedIds.has('1')).toBe(true)
    store.toggleSelect(1)
    expect(store.selectedIds.has('1')).toBe(false)
  })

  it('selectAll selects all records', () => {
    const store = useDashboardStore()
    store.setRecords([{ id: 1 }, { id: 2 }, { id: 3 }])
    store.selectAll()
    expect(store.selectedIds.size).toBe(3)
  })

  it('clearSelection clears all', () => {
    const store = useDashboardStore()
    store.setRecords([{ id: 1 }, { id: 2 }])
    store.selectAll()
    store.clearSelection()
    expect(store.selectedIds.size).toBe(0)
    expect(store.baselineId).toBeNull()
  })

  it('selectFirstN selects first N records', () => {
    const store = useDashboardStore()
    store.setRecords([{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }])
    store.selectFirstN(3)
    expect(store.selectedIds.size).toBe(3)
    expect(store.selectedIds.has('1')).toBe(true)
    expect(store.selectedIds.has('2')).toBe(true)
    expect(store.selectedIds.has('3')).toBe(true)
    expect(store.selectedIds.has('4')).toBe(false)
  })

  it('startRequest returns seq and signal', () => {
    const store = useDashboardStore()
    const { seq, signal } = store.startRequest()
    expect(seq).toBe(1)
    expect(signal).toBeInstanceOf(AbortSignal)
  })

  it('isRequestValid checks seq', () => {
    const store = useDashboardStore()
    const { seq } = store.startRequest()
    expect(store.isRequestValid(seq)).toBe(true)
    store.startRequest()
    expect(store.isRequestValid(seq)).toBe(false)
  })

  it('selectedRecords computed property', () => {
    const store = useDashboardStore()
    store.setRecords([
      { id: 1, name: 'a' },
      { id: 2, name: 'b' }
    ])
    store.toggleSelect(1)
    expect(store.selectedRecords).toHaveLength(1)
    expect(store.selectedRecords[0].name).toBe('a')
  })

  it('keeps duplicate backend ids independently selectable across projects', () => {
    const store = useDashboardStore()
    store.setRecords([
      { id: 1, project_id: 'alpha', name: 'alpha run' },
      { id: 1, project_id: 'beta', name: 'beta run' }
    ])
    store.toggleSelect(store.selectionKey(store.records[0]))
    expect(store.selectedRecords.map(record => record.name)).toEqual(['alpha run'])
    expect(store.selectedIds.size).toBe(1)
  })
})
