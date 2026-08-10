<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import ChangePasswordModal from './ChangePasswordModal.vue'
import ThemeModal from './ThemeModal.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { showModal: showThemeModal } = useTheme()

const showDropdown = ref(false)
const showChangePassword = ref(false)

const navItems = computed(() => {
  const items = [
    { path: '/dashboard', label: 'Dashboard', icon: 'dashboard' },
    { path: '/compare', label: '对比', icon: 'compare' },
    { path: '/review', label: '评审', icon: 'review' },
    { path: '/source-files', label: '源文件', icon: 'source' }
  ]
  if (auth.isAdmin || auth.isRelease) {
    items.push({ path: '/admin', label: '管理', icon: 'admin' })
  }
  return items
})

function isActive(path) {
  return route.path.startsWith(path)
}

function handleLogout() {
  auth.logout()
  router.push('/login')
}

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
}

function closeDropdown() {
  showDropdown.value = false
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
      <div class="user-dropdown" @click="toggleDropdown">
        <button class="user-btn">
          <span class="user-avatar">{{ auth.user?.username?.charAt(0)?.toUpperCase() || 'U' }}</span>
          <span class="user-name">{{ auth.user?.username }}</span>
          <span class="dropdown-icon">▼</span>
        </button>
        <div v-if="showDropdown" class="dropdown-menu">
          <button class="dropdown-item" @click="showThemeModal = true; closeDropdown()">
            🎨 Theme
          </button>
          <button class="dropdown-item" @click="showChangePassword = true; closeDropdown()">
            🔑 Change Password
          </button>
          <div class="dropdown-divider"></div>
          <button class="dropdown-item logout-item" @click="handleLogout">
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
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
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
  text-shadow: var(--glow-primary);
}
.navbar-links {
  display: flex;
  gap: 4px;
  flex: 1;
}
.nav-link {
  padding: 8px 16px;
  color: var(--color-text-secondary);
  text-decoration: none;
  border-radius: 4px;
  font-size: 14px;
  transition: all 0.2s;
}
.nav-link:hover {
  color: var(--color-text);
  background: var(--color-surface-hover);
}
.nav-link.active {
  color: var(--color-primary);
  background: rgba(0, 212, 255, 0.1);
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
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary);
  color: white;
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
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
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
}
.dropdown-divider {
  height: 1px;
  background: var(--color-border);
  margin: 4px 0;
}
.logout-item {
  color: var(--color-error);
}
.logout-item:hover {
  background: rgba(244, 67, 54, 0.1);
}
</style>