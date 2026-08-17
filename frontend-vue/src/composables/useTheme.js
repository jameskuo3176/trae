import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getItem, setItem } from '@/utils/storage'

const THEME_PRESETS = {
  dark: {
    name: 'dark',
    color_scheme: 'dark',
    primary: '#6cb6ff',
    primary_rgb: '108, 182, 255',
    primary_hover: '#92c9ff',
    on_primary: '#071321',
    background: '#0b1220',
    surface: '#111c2e',
    surface_elevated: '#18263b',
    surface_hover: '#20324b',
    surface_selected: '#173a61',
    surface_active: '#28425f',
    text: '#f4f7fb',
    text_secondary: '#c3cfdd',
    text_muted: '#9eafc2',
    text_on_hover: '#ffffff',
    text_on_selected: '#ffffff',
    border: '#3a4d65',
    border_strong: '#62758d',
    input_background: '#0d1727',
    input_text: '#f4f7fb',
    input_border: '#526780',
    placeholder: '#95a6ba',
    focus_ring: '#8bc4ff',
    overlay: 'rgba(2, 8, 18, 0.78)',
    shadow: 'rgba(0, 0, 0, 0.42)',
    success: '#75d59b',
    success_background: '#102c20',
    success_border: '#3f8f61',
    warning: '#ffd166',
    warning_background: '#33280d',
    warning_border: '#9f7b27',
    danger: '#ff9a9a',
    danger_background: '#351719',
    danger_border: '#a74c52',
    info: '#91caff',
    info_background: '#102943',
    info_border: '#3f78aa',
    disabled_background: '#1a2637',
    disabled_text: '#8493a5',
    scrollbar_thumb: '#526780',
    scrollbar_track: '#111c2e',
    table_stripe: '#152238',
    selection_background: '#245d94',
    selection_text: '#ffffff',
    navbar_text: '#c3cfdd',
    navbar_text_active: '#92c9ff'
  },
  light: {
    name: 'light',
    color_scheme: 'light',
    primary: '#005fcc',
    primary_rgb: '0, 95, 204',
    primary_hover: '#004ca6',
    on_primary: '#ffffff',
    background: '#eef2f6',
    surface: '#ffffff',
    surface_elevated: '#f7f9fc',
    surface_hover: '#e3ebf5',
    surface_selected: '#d4e6fb',
    surface_active: '#c7d9ed',
    text: '#111827',
    text_secondary: '#374151',
    text_muted: '#566579',
    text_on_hover: '#0b1220',
    text_on_selected: '#071321',
    border: '#b5c0cd',
    border_strong: '#77879a',
    input_background: '#ffffff',
    input_text: '#111827',
    input_border: '#7d8da0',
    placeholder: '#65758a',
    focus_ring: '#005fcc',
    overlay: 'rgba(15, 23, 42, 0.58)',
    shadow: 'rgba(15, 23, 42, 0.18)',
    success: '#166534',
    success_background: '#e7f6ec',
    success_border: '#5d9f72',
    warning: '#7a4b00',
    warning_background: '#fff4d6',
    warning_border: '#c18a2d',
    danger: '#a51d2d',
    danger_background: '#fdebed',
    danger_border: '#c96a74',
    info: '#075985',
    info_background: '#e4f3fb',
    info_border: '#5795b5',
    disabled_background: '#e1e6ec',
    disabled_text: '#4b5563',
    scrollbar_thumb: '#8796a8',
    scrollbar_track: '#e8edf3',
    table_stripe: '#f4f7fa',
    selection_background: '#b9dafc',
    selection_text: '#071321',
    navbar_text: '#374151',
    navbar_text_active: '#005fcc'
  }
}

const DEFAULT_THEME = THEME_PRESETS.dark
const LEGACY_LIGHT_THEMES = new Set(['classic', 'slate', 'light'])
const showModal = ref(false)
const currentTheme = ref({ ...DEFAULT_THEME })
const tableFontSize = ref(12)

function normalizeTableFontSize(value) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.min(18, Math.max(10, Math.round(numeric))) : 12
}

function normalizeTheme(theme) {
  const name = typeof theme === 'string' ? theme : theme?.name
  return LEGACY_LIGHT_THEMES.has(String(name || '').toLowerCase())
    ? { ...THEME_PRESETS.light }
    : { ...THEME_PRESETS.dark }
}

export function useTheme() {
  const presets = ref(THEME_PRESETS)

  function applyTheme(theme) {
    const canonicalTheme = normalizeTheme(theme)
    const root = document.documentElement
    Object.entries(canonicalTheme).forEach(([key, value]) => {
      if (key === 'name' || key === 'color_scheme') return
      root.style.setProperty(`--color-${key.replaceAll('_', '-')}`, value)
    })
    root.style.setProperty('--theme-name', canonicalTheme.name)
    root.style.colorScheme = canonicalTheme.color_scheme
    root.dataset.theme = canonicalTheme.name
    document.body.dataset.theme = canonicalTheme.name
    return canonicalTheme
  }

  function initTheme() {
    const canonicalTheme = normalizeTheme(getItem('theme'))
    currentTheme.value = canonicalTheme
    setItem('theme', canonicalTheme)
    applyTheme(canonicalTheme)
    setTableFontSize(getItem('table_font_size'))
  }

  function setTableFontSize(value) {
    const normalized = normalizeTableFontSize(value)
    tableFontSize.value = normalized
    setItem('table_font_size', normalized)
    document.documentElement.style.setProperty('--table-font-size', `${normalized}px`)
  }

  function saveThemeToStorage(theme) {
    const canonicalTheme = normalizeTheme(theme)
    setItem('theme', canonicalTheme)
    currentTheme.value = canonicalTheme
    applyTheme(canonicalTheme)
  }

  async function saveThemeToServer() {
    const auth = useAuthStore()
    try {
      await auth.saveTheme(currentTheme.value)
    } catch (e) {
      console.error('Failed to save theme:', e)
    }
  }

  function resetToDefault() {
    saveThemeToStorage({ ...DEFAULT_THEME })
  }

  return {
    DEFAULT_THEME,
    currentTheme,
    tableFontSize,
    presets,
    showModal,
    applyTheme,
    initTheme,
    saveThemeToStorage,
    saveThemeToServer,
    setTableFontSize,
    resetToDefault
  }
}
