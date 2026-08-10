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

  it('parseModuleValue handles composite IDs', () => {
    const filters = useFiltersStore()
    const result = filters.parseModuleValue('1:8')
    expect(result.projectId).toBe('1')
    expect(result.moduleId).toBe('8')
  })

  it('parseModuleValue handles plain IDs', () => {
    const filters = useFiltersStore()
    const result = filters.parseModuleValue('42')
    expect(result.projectId).toBeNull()
    expect(result.moduleId).toBe('42')
  })

  it('resolveProjectIdsForModules extracts project IDs', () => {
    const filters = useFiltersStore()
    const ids = filters.resolveProjectIdsForModules(['1:8', '1:10', '2:5'])
    expect(ids).toContain('1')
    expect(ids).toContain('2')
    expect(ids).toHaveLength(2)
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