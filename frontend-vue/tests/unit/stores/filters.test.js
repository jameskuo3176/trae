import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useFiltersStore } from '@/stores/filters'

describe('Filters Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initial state has empty filters', () => {
    const filters = useFiltersStore()
    expect(filters.projectId).toBeNull()
    expect(filters.moduleIds).toEqual([])
    expect(filters.versionIds).toEqual([])
    expect(filters.dirPrefix).toBe('')
  })

  it('fingerprint changes when filters change', () => {
    const filters = useFiltersStore()
    const fp1 = filters.fingerprint
    filters.projectId = '1'
    const fp2 = filters.fingerprint
    expect(fp1).not.toBe(fp2)
  })

  it('fingerprint is stable for same filter values', () => {
    const filters = useFiltersStore()
    filters.projectId = '1'
    filters.moduleIds = ['3', '5']
    const fp1 = filters.fingerprint
    filters.moduleIds = ['5', '3']
    const fp2 = filters.fingerprint
    expect(fp1).toBe(fp2)
  })

  it('stores global module IDs without project prefixes', () => {
    const filters = useFiltersStore()
    filters.moduleIds = ['8', '42']
    expect(filters.moduleIds).toEqual(['8', '42'])
    expect(filters.moduleIds.some(value => value.includes(':'))).toBe(false)
  })

  it('reset clears all filters', () => {
    const filters = useFiltersStore()
    filters.projectId = '1'
    filters.moduleIds = ['3']
    filters.versionIds = ['v1']
    filters.dirPrefix = 'dir'
    filters.reset()
    expect(filters.projectId).toBeNull()
    expect(filters.moduleIds).toEqual([])
    expect(filters.versionIds).toEqual([])
    expect(filters.dirPrefix).toBe('')
  })
})
