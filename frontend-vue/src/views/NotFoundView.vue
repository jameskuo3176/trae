<script setup>
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <div class="not-found">
    <h1>404</h1>
    <p>页面不存在</p>
    <button class="btn" @click="router.push('/dashboard')">返回首页</button>
  </div>
</template>

<style scoped>
.not-found {
  text-align: center;
  padding: 80px 20px;
}
.not-found h1 {
  font-size: 64px;
  color: var(--color-primary);
  text-shadow: var(--glow-primary);
  margin-bottom: 16px;
}
.not-found p {
  font-size: 18px;
  color: var(--color-text-secondary);
  margin-bottom: 24px;
}
</style>
