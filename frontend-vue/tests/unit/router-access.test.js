import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

describe('owner route access', () => {
  beforeEach(async () => {
    window.scrollTo = vi.fn()
    setActivePinia(createPinia())
    await router.push('/login')
  })

  it('allows a normal owner to open review and hierarchy-hosting admin pages', async () => {
    useAuthStore().setUserFromSession({
      id: 1,
      username: 'user',
      is_admin: false,
      is_owner: true,
      is_viewer: false
    })

    await router.push('/review/group')
    expect(router.currentRoute.value.name).toBe('Review')

    await router.push('/admin')
    expect(router.currentRoute.value.name).toBe('Admin')
  })

  it('continues to deny viewer access to owner pages', async () => {
    useAuthStore().setUserFromSession({
      id: 2,
      username: 'viewer',
      is_admin: false,
      is_owner: false,
      is_viewer: true
    })

    await router.push('/review/group')
    expect(router.currentRoute.value.name).toBe('Dashboard')

    await router.push('/admin')
    expect(router.currentRoute.value.name).toBe('Dashboard')
  })
})
