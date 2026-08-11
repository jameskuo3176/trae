import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTheme } from '@/composables/useTheme'

describe('theme primary contrast', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.documentElement.removeAttribute('style')
  })

  it('uses light on-primary text for the classic blue preset', () => {
    const theme = useTheme()
    theme.applyTheme(theme.presets.value.classic)
    expect(document.documentElement.style.getPropertyValue('--color-on-primary')).toBe('#ffffff')
  })

  it('uses dark on-primary text for the neon cyan preset', () => {
    const theme = useTheme()
    theme.applyTheme(theme.presets.value.neon)
    expect(document.documentElement.style.getPropertyValue('--color-on-primary')).toBe('#071018')
  })
})
