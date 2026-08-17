import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './styles/global.css'

const app = createApp(App)

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

app.use(pinia)

async function bootstrap() {
  // /auth/me restores the server session and asks Django to refresh the
  // readable CSRF cookie before routed views can issue unsafe requests.
  await useAuthStore().fetchUser()
  app.use(router)
  app.mount('#app')
}

bootstrap()
