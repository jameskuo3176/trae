<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const error = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await auth.login(username.value, password.value)
    const redirect = route.query.redirect || '/dashboard'
    router.push(redirect)
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">QoR Recorder</h1>
      <p class="login-subtitle">Quality of Results 数据管理平台</p>
      <div class="login-form">
        <div class="form-group">
          <label>用户名</label>
          <input
            v-model="username"
            type="text"
            placeholder="请输入用户名"
            :disabled="loading"
            @keyup.enter="handleLogin"
          />
        </div>
        <div class="form-group">
          <label>密码</label>
          <div class="password-wrapper">
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              placeholder="请输入密码"
              :disabled="loading"
              @keyup.enter="handleLogin"
            />
            <button class="toggle-password" type="button" @click="showPassword = !showPassword">
              {{ showPassword ? '隐藏' : '显示' }}
            </button>
          </div>
        </div>
        <p v-if="error" class="error-text">{{ error }}</p>
        <button class="btn login-btn" :disabled="loading" @click="handleLogin">
          {{ loading ? '正在登录...' : '登录' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-background);
}
.login-card {
  background: var(--color-surface);
  padding: 40px;
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
  width: 400px;
  max-width: 90vw;
  border: 1px solid var(--color-border);
}
.login-title {
  text-align: center;
  font-size: 28px;
  color: var(--color-primary);
  text-shadow: var(--glow-primary);
  margin-bottom: 8px;
}
.login-subtitle {
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 14px;
  margin-bottom: 32px;
}
.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.password-wrapper {
  position: relative;
}
.password-wrapper input {
  width: 100%;
  padding-right: 60px;
}
.toggle-password {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--color-primary);
  font-size: 13px;
  padding: 4px 8px;
}
.error-text {
  color: var(--color-danger);
  font-size: 14px;
  text-align: center;
}
.login-btn {
  width: 100%;
  padding: 12px;
  font-size: 16px;
  margin-top: 8px;
}
.login-btn:disabled {
  border-color: var(--color-border);
  background: var(--color-disabled-background);
  color: var(--color-disabled-text);
  opacity: 1;
  cursor: not-allowed;
}
</style>
