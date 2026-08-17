import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTheme } from '@/composables/useTheme'

const storedTheme = () => JSON.parse(localStorage.getItem('qor_theme'))

describe('theme presets and migration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    document.documentElement.removeAttribute('style')
    document.documentElement.removeAttribute('data-theme')
    document.body.removeAttribute('data-theme')
  })

  it('exports exactly the dark and light presets', () => {
    const theme = useTheme()
    expect(Object.keys(theme.presets.value)).toEqual(['dark', 'light'])
    expect(theme.DEFAULT_THEME.name).toBe('dark')
  })

  it.each(['classic', 'slate', 'light'])('migrates legacy %s storage to light', name => {
    localStorage.setItem('qor_theme', JSON.stringify({ name, primary: '#ff00ff' }))
    const theme = useTheme()
    theme.initTheme()

    expect(theme.currentTheme.value).toEqual(theme.presets.value.light)
    expect(storedTheme()).toEqual(theme.presets.value.light)
    expect(document.body.dataset.theme).toBe('light')
    expect(document.documentElement.style.getPropertyValue('--color-primary')).toBe('#005fcc')
  })

  it.each(['neon', 'graphite', 'terminal', 'amber', 'custom', undefined])(
    'migrates legacy %s storage to dark',
    name => {
      localStorage.setItem(
        'qor_theme',
        JSON.stringify(
          name ? { name, background: '#ffffff', text: '#ffffff' } : { primary: '#fff' }
        )
      )
      const theme = useTheme()
      theme.initTheme()

      expect(theme.currentTheme.value).toEqual(theme.presets.value.dark)
      expect(storedTheme()).toEqual(theme.presets.value.dark)
      expect(document.documentElement.style.getPropertyValue('--color-background')).toBe('#0b1220')
    }
  )

  it('persists only canonical presets for names and objects', () => {
    const theme = useTheme()

    theme.saveThemeToStorage('light')
    expect(storedTheme()).toEqual(theme.presets.value.light)

    theme.saveThemeToStorage({ name: 'dark', primary: '#ffffff', text: '#ffffff' })
    expect(storedTheme()).toEqual(theme.presets.value.dark)
    expect(document.documentElement.style.getPropertyValue('--color-primary')).toBe('#6cb6ff')
  })

  it('sets color-scheme and readable on-primary colors for both presets', () => {
    const theme = useTheme()

    theme.saveThemeToStorage('dark')
    expect(document.documentElement.style.colorScheme).toBe('dark')
    expect(document.documentElement.style.getPropertyValue('--color-on-primary')).toBe('#071321')

    theme.saveThemeToStorage(theme.presets.value.light)
    expect(document.documentElement.style.colorScheme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(document.documentElement.style.getPropertyValue('--color-on-primary')).toBe('#ffffff')
    expect(document.documentElement.style.getPropertyValue('--color-disabled-text')).toBe('#4b5563')
  })

  it('persists and clamps the global table font size', () => {
    const theme = useTheme()

    theme.setTableFontSize(16)
    expect(theme.tableFontSize.value).toBe(16)
    expect(localStorage.getItem('qor_table_font_size')).toBe('16')
    expect(document.documentElement.style.getPropertyValue('--table-font-size')).toBe('16px')

    theme.setTableFontSize(99)
    expect(theme.tableFontSize.value).toBe(18)

    localStorage.setItem('qor_table_font_size', '14')
    theme.initTheme()
    expect(theme.tableFontSize.value).toBe(14)
  })
})
