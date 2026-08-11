import { describe, expect, it } from 'vitest'
import { useTableSort } from '@/composables/useTableSort'

describe('useTableSort', () => {
  it('cycles ascending, descending, and original order', () => {
    const sort = useTableSort()
    const rows = [
      { id: 'a', value: 2 },
      { id: 'b', value: 1 }
    ]
    sort.sortBy('value')
    expect(sort.computeSorted(rows).map(row => row.id)).toEqual(['b', 'a'])
    sort.sortBy('value')
    expect(sort.computeSorted(rows).map(row => row.id)).toEqual(['a', 'b'])
    sort.sortBy('value')
    expect(sort.sortOrder.value).toBe('original')
    expect(sort.computeSorted(rows)).toBe(rows)
  })

  it('keeps null values at the end when ascending', () => {
    const sort = useTableSort()
    sort.sortBy('value')
    expect(
      sort.computeSorted([{ value: null }, { value: 2 }, { value: 1 }]).map(row => row.value)
    ).toEqual([1, 2, null])
  })
})
