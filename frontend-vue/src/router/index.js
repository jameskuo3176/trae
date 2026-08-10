import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { guest: true }
  },
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/compare',
    name: 'Compare',
    component: () => import('@/views/CompareView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/AdminView.vue'),
    meta: { requiresAuth: true, roles: ['admin', 'owner', 'release'] }
  },
  {
    path: '/review',
    name: 'Review',
    component: () => import('@/views/ReviewView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/record/:id',
    name: 'RecordDetail',
    component: () => import('@/views/RecordDetailView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/source-files',
    name: 'SourceFilesCheck',
    component: () => import('@/views/SourceFilesCheckView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFoundView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  if (to.meta.guest && auth.isAuthenticated) {
    return next({ name: 'Dashboard' })
  }

  if (to.meta.roles && !to.meta.roles.some(r => auth.hasRole(r))) {
    return next({ name: 'Dashboard' })
  }

  next()
})

export default router