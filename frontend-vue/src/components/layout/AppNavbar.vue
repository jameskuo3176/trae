<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import ChangePasswordModal from './ChangePasswordModal.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { showModal: showThemeModal, tableFontSize, setTableFontSize } = useTheme()

const showDropdown = ref(false)
const showChangePassword = ref(false)

const navItems = computed(() => {
  const items = [{ path: '/dashboard', label: 'Dashboard', icon: 'dashboard' }]
  if (!auth.isViewer) {
    items.push({ path: '/review', label: '评审', icon: 'review' })
  }
  if (auth.isAdmin || auth.isOwner) {
    items.push({ path: '/admin', label: '管理', icon: 'admin' })
  }
  return items
})

function isActive(path) {
  return route.path.startsWith(path)
}

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
}

function closeDropdown() {
  showDropdown.value = false
}
function openTheme() {
  showThemeModal.value = true
  closeDropdown()
}
function openChangePassword() {
  showChangePassword.value = true
  closeDropdown()
}
function onFontSizeInput(event) {
  setTableFontSize(Number(event.target.value))
}
</script>

<template>
  <nav class="navbar">
    <div class="navbar-brand">
      <router-link to="/dashboard" class="brand-link">
        <span class="brand-text">QoR Recorder</span>
      </router-link>
    </div>
    <div class="navbar-links">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        :class="['nav-link', { active: isActive(item.path) }]"
      >
        {{ item.label }}
      </router-link>
    </div>
    <div class="navbar-actions">
      <div class="user-dropdown">
        <button class="user-btn" type="button" @click.stop="toggleDropdown">
          <span class="user-avatar">{{
            auth.user?.username?.charAt(0)?.toUpperCase() || 'U'
          }}</span>
          <span class="user-name">{{ auth.user?.username }}</span>
          <span class="dropdown-icon">▼</span>
        </button>
        <div v-if="showDropdown" class="dropdown-menu">
          <button class="dropdown-item" type="button" @click.stop="openTheme">🎨 Theme</button>
          <div class="dropdown-item font-size-row" @click.stop>
            <span class="font-size-label">🔤 字体大小</span>
            <div class="font-size-controls">
              <input
                type="range"
                min="10"
                max="18"
                step="1"
                :value="tableFontSize"
                @input="onFontSizeInput"
              />
              <span class="font-size-value">{{ tableFontSize }}px</span>
            </div>
          </div>
          <button class="dropdown-item" type="button" @click.stop="openChangePassword">
            🔑 Change Password
          </button>
          <div class="dropdown-divider"></div>
          <button class="dropdown-item logout-item" type="button" @click.stop="handleLogout">
            🚪 Logout
          </button>
        </div>
      </div>
    </div>
  </nav>

  <ChangePasswordModal v-model="showChangePassword" />
</template>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  padding: 0 24px;
  height: 56px;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  box-shadow: 0 1px 4px var(--color-shadow);
  position: relative;
  z-index: 1000;
}
.navbar-brand {
  margin-right: 32px;
}
.brand-link {
  text-decoration: none;
}
.brand-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-primary);
}
.navbar-links {
  display: flex;
  gap: 4px;
  flex: 1;
}
.nav-link {
  padding: 8px 16px;
  color: var(--color-navbar-text);
  text-decoration: none;
  border-radius: 4px;
  font-size: 14px;
  transition: all 0.2s;
}
.nav-link:hover {
  color: var(--color-text-on-hover);
  background: var(--color-surface-hover);
}
.nav-link.active {
  color: var(--color-navbar-text-active);
  background: var(--color-surface-selected);
}
.navbar-actions {
  display: flex;
  align-items: center;
}

/* User Dropdown */
.user-dropdown {
  position: relative;
}
.user-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.user-btn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.user-btn:hover :is(.user-name, .dropdown-icon) {
  color: inherit;
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}
.user-name {
  font-size: 14px;
  color: var(--color-text);
}
.dropdown-icon {
  font-size: 10px;
  color: var(--color-text-secondary);
}

.dropdown-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  min-width: 180px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 4px 12px var(--color-shadow);
  padding: 4px 0;
  z-index: 1001;
}
.dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 16px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text);
  text-align: left;
  transition: background 0.15s;
}
.dropdown-item:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.dropdown-divider {
  height: 1px;
  background: var(--color-border);
  margin: 4px 0;
}
.font-size-row {
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}
.font-size-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.font-size-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.font-size-controls input[type='range'] {
  flex: 1;
  min-width: 90px;
  accent-color: var(--color-primary);
  cursor: pointer;
}
.font-size-value {
  min-width: 36px;
  text-align: right;
  font:
    600 12px Consolas,
    monospace;
  color: var(--color-text);
}
.logout-item {
  color: var(--color-danger);
}
.logout-item:hover {
  background: var(--color-danger-background);
  color: var(--color-danger);
}
</style>
