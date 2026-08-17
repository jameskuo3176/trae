import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import AppNavbar from '@/components/layout/AppNavbar.vue'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'

function createTestRouter() {
  return createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/dashboard', component: { template: '<div>Dashboard</div>' } },
      { path: '/admin', component: { template: '<div>Admin</div>' } },
      { path: '/review', component: { template: '<div>Review</div>' } },
      { path: '/login', component: { template: '<div>Login</div>' } }
    ]
  })
}

describe('AppNavbar', () => {
  let router

  beforeEach(async () => {
    setActivePinia(createPinia())
    useTheme().showModal.value = false
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
    expect(wrapper.text()).not.toContain('对比')
    expect(wrapper.text()).not.toContain('源文件')
  })

  it('shows admin link for admin users', () => {
    const auth = useAuthStore()
    auth.setUserFromSession({ id: 1, username: 'admin', is_admin: true })
    const wrapper = mount(AppNavbar, {
      global: { plugins: [router] }
    })
    expect(wrapper.text()).toContain('管理')
  })

  it('shows review and hierarchy-hosting admin links for owner users', () => {
    const auth = useAuthStore()
    auth.setUserFromSession({
      id: 2,
      username: 'user',
      is_admin: false,
      is_owner: true,
      is_viewer: false
    })
    const wrapper = mount(AppNavbar, {
      global: { plugins: [router] }
    })
    expect(wrapper.text()).toContain('评审')
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

  it('closes the user dropdown when opening the theme modal', async () => {
    const auth = useAuthStore()
    auth.setUserFromSession({ id: 1, username: 'admin', is_admin: true })
    const wrapper = mount(AppNavbar, {
      global: { plugins: [router] }
    })

    await wrapper.get('.user-btn').trigger('click')
    expect(wrapper.find('.dropdown-menu').exists()).toBe(true)

    await wrapper.get('.dropdown-item').trigger('click')
    expect(useTheme().showModal.value).toBe(true)
    expect(wrapper.find('.dropdown-menu').exists()).toBe(false)
  })
})
