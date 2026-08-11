<script setup>
defineProps({
  text: { type: String, default: '加载中...' },
  size: { type: String, default: '40px' }
})
</script>

<template>
  <div class="loading-container">
    <div class="spinner" :style="{ width: size, height: size }" />
    <p class="loading-text">{{ text }}</p>
  </div>
</template>

<style scoped>
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 16px;
}
.spinner {
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.loading-text {
  color: var(--color-text-secondary);
  font-size: 14px;
}
</style>
