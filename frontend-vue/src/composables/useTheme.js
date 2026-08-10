import { ref, watch } from 'vue'
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

const showModal = ref(false)

export function useTheme() {
  const currentTheme = ref({ ...DEFAULT_THEME })
  const presets = ref({})

  function applyTheme(theme) {
    const root = document.documentElement
    const fields = THEME_FIELDS.map(f => f.key)
    fields.forEach(key => {
      if (theme[key]) {
        root.style.setProperty(`--color-${key}`, theme[key])
      }
    })
    root.style.setProperty('--theme-name', theme.name || 'custom')
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