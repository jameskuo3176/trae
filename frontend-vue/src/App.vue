<script setup>
import { ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useDashboardStore } from '@/stores/dashboard'
import { useDashboardConfigsStore } from '@/stores/dashboardConfigs'
import { useFiltersStore } from '@/stores/filters'
import AppNavbar from '@/components/layout/AppNavbar.vue'
import ThemeModal from '@/components/layout/ThemeModal.vue'
import ChangePasswordModal from '@/components/layout/ChangePasswordModal.vue'
import { useTheme } from '@/composables/useTheme'

const auth = useAuthStore()
const dashboard = useDashboardStore()
const dashboardConfigs = useDashboardConfigsStore()
const filters = useFiltersStore()
const { initTheme } = useTheme()
const changePwModalRef = ref(null)

initTheme()
watch(
  () => auth.user?.id ?? null,
  (userId, previousUserId) => {
    if (userId == null || userId === previousUserId) return
    filters.reset()
    dashboard.reset()
    dashboardConfigs.reset()
  }
)
</script>

<template>
  <div class="app-root">
    <AppNavbar v-if="auth.isAuthenticated" />
    <main class="app-main">
      <router-view />
    </main>
    <ThemeModal v-if="auth.isAuthenticated" />
    <ChangePasswordModal
      v-if="auth.isAuthenticated"
      ref="changePwModalRef"
      :must-change="auth.mustChangePassword"
    />
  </div>
</template>

<style scoped>
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.app-main {
  flex: 1;
  padding: 24px;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}
</style>
