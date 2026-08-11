import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getItem, setItem } from '@/utils/storage'

const THEME_FIELDS = [
  { key: 'primary', label: '主色', color: true },
  { key: 'primary_gradient_end', label: '主色(渐变终点)', color: true },
  { key: 'background', label: '页面背景', color: true },
  { key: 'surface', label: '卡片背景', color: true },
  { key: 'surface_hover', label: '卡片悬停', color: true },
  { key: 'text', label: '主文字', color: true },
  { key: 'text_secondary', label: '次要文字', color: true },
  { key: 'border', label: '边框', color: true },
  { key: 'navbar_text', label: '导航文字', color: false },
  { key: 'navbar_text_active', label: '导航激活文字', color: false }
]

const DEFAULT_THEME = {
  primary: '#00d4ff',
  primary_gradient_end: '#7b2ff7',
  background: '#0a0e1a',
  surface: '#131829',
  surface_hover: '#1a2138',
  text: '#e6f1ff',
  text_secondary: '#8b9bb4',
  border: '#1f2a44',
  navbar_text: 'rgba(230, 241, 255, 0.75)',
  navbar_text_active: '#00d4ff',
  name: 'neon'
}

const THEME_PRESETS = {
  neon: DEFAULT_THEME,
  classic: {
    primary: '#1769aa',
    primary_gradient_end: '#0d47a1',
    background: '#f3f6f9',
    surface: '#ffffff',
    surface_hover: '#e8f0f7',
    text: '#18212b',
    text_secondary: '#52606d',
    border: '#b8c4ce',
    navbar_text: '#334e68',
    navbar_text_active: '#0d47a1',
    name: 'classic'
  },
  graphite: {
    primary: '#66b3ff',
    primary_gradient_end: '#3584c9',
    background: '#111417',
    surface: '#1b2025',
    surface_hover: '#252c33',
    text: '#edf2f7',
    text_secondary: '#a8b3bd',
    border: '#38434d',
    navbar_text: '#c4cdd5',
    navbar_text_active: '#66b3ff',
    name: 'graphite'
  },
  terminal: {
    primary: '#42f57b',
    primary_gradient_end: '#18a84b',
    background: '#050a06',
    surface: '#0b130d',
    surface_hover: '#122219',
    text: '#d7ffe2',
    text_secondary: '#88c89b',
    border: '#1f5330',
    navbar_text: '#a8dab7',
    navbar_text_active: '#42f57b',
    name: 'terminal'
  },
  amber: {
    primary: '#ffc247',
    primary_gradient_end: '#d58a00',
    background: '#171109',
    surface: '#241a0d',
    surface_hover: '#332615',
    text: '#fff4d6',
    text_secondary: '#d6bc83',
    border: '#5a4320',
    navbar_text: '#ead2a1',
    navbar_text_active: '#ffc247',
    name: 'amber'
  },
  slate: {
    primary: '#63b3ed',
    primary_gradient_end: '#4c7ad9',
    background: '#eef2f6',
    surface: '#fdfefe',
    surface_hover: '#e4ebf2',
    text: '#1f2933',
    text_secondary: '#52616f',
    border: '#adbac7',
    navbar_text: '#3e4c59',
    navbar_text_active: '#1769aa',
    name: 'slate'
  }
}

const showModal = ref(false)

export function useTheme() {
  const currentTheme = ref({ ...DEFAULT_THEME })
  const presets = ref(THEME_PRESETS)

  function applyTheme(theme) {
    const root = document.documentElement
    const fields = THEME_FIELDS.map(f => f.key)
    fields.forEach(key => {
      if (theme[key]) {
        root.style.setProperty(`--color-${key}`, theme[key])
      }
    })
    root.style.setProperty('--theme-name', theme.name || 'custom')
    const primary = theme.primary || DEFAULT_THEME.primary
    const rgb = primary.match(/\w\w/g)?.map(value => parseInt(value, 16))
    if (rgb) {
      const luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
      root.style.setProperty('--color-on-primary', luminance > 0.58 ? '#071018' : '#ffffff')
    }
    document.body.dataset.theme = theme.name || 'custom'
  }

  function initTheme() {
    const saved = getItem('theme')
    if (saved) {
      currentTheme.value = saved
      applyTheme(saved)
    }
  }

  function saveThemeToStorage(theme) {
    setItem('theme', theme)
    currentTheme.value = { ...theme }
    applyTheme(theme)
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
    THEME_FIELDS,
    DEFAULT_THEME,
    currentTheme,
    presets,
    showModal,
    applyTheme,
    initTheme,
    saveThemeToStorage,
    saveThemeToServer,
    resetToDefault
  }
}
