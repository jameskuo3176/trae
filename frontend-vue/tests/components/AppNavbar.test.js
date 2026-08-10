import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import AppNavbar from '@/components/layout/AppNavbar.vue'
import { useAuthStore } from '@/stores/auth'

function createTestRouter() {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/dashboard', component: { template: '<div>Dashboard</div>' } },
      { path: '/admin', component: { template: '<div>Admin</div>' } },
      { path: '/login', component: { template: '<div>Login</div>' } }
    ]
  })
}

describe('AppNavbar', () => {
  let router

  beforeEach(async () => {
    setActivePinia(createPinia())
    router = createTestRouter()
    router.push('/dashboard')
    await router.isReady()
  })

  it('renders brand name', () => {
    const auth = useAuthStore()
    auth.setUserFromSession({ id: 1, username: 'admin', is_admin: true })
    const wrapper = mount(AppNavbar, {
      global: { plugins: [router] }
    })
    expect(wrapper.text()).toContain('QoR Recorder')
  })

  it('shows admin link for admin users', () => {
    const auth = useAuthStore()
    auth.setUserFromSession({ id: 1, username: 'admin', is_admin: true })
    const wrapper = mount(AppNavbar, {
      global: { plugins: [router] }
    })
    expect(wrapper.text()).toContain('管理')
  })

  it('hides admin link for viewer users', () => {
    const auth = useAuthStore()
    auth.setUserFromSession({ id: 1, username: 'viewer', is_viewer: true })
    const wrapper = mount(AppNavbar, {
      global: { plugins: [router] }
    })
    expect(wrapper.text()).not.toContain('管理')
  })

  it('displays username', () => {
    const auth = useAuthStore()
    auth.setUserFromSession({ id: 1, username: 'testuser', is_admin: false })
    const wrapper = mount(AppNavbar, {
      global: { plugins: [router] }
    })
    expect(wrapper.text()).toContain('testuser')
  })
})