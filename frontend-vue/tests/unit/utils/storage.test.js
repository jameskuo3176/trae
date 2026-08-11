import { beforeEach, describe, it, expect } from 'vitest'
import { getItem, setItem, removeItem, getSessionItem, setSessionItem } from '@/utils/storage'

describe('Storage Utils', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  describe('localStorage', () => {
    it('setItem and getItem roundtrip', () => {
      setItem('test', { name: 'value' })
      expect(getItem('test')).toEqual({ name: 'value' })
    })

    it('getItem returns null for missing key', () => {
      expect(getItem('missing')).toBeNull()
    })

    it('removeItem deletes key', () => {
      setItem('test', { a: 1 })
      removeItem('test')
      expect(getItem('test')).toBeNull()
    })

    it('uses qor_ prefix', () => {
      setItem('key', 'val')
      expect(localStorage.getItem('qor_key')).toBeTruthy()
    })
  })

  describe('sessionStorage', () => {
    it('setSessionItem and getSessionItem roundtrip', () => {
      setSessionItem('session_key', { data: 123 })
      expect(getSessionItem('session_key')).toEqual({ data: 123 })
    })

    it('getSessionItem returns null for missing key', () => {
      expect(getSessionItem('missing')).toBeNull()
    })
  })
})
