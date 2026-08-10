<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '-' },
  icon: { type: String, default: '' },
  trend: { type: String, default: '' },
  color: { type: String, default: '' }
})
</script>

<template>
  <div class="stat-card card">
    <div class="stat-body">
      <div class="stat-label">{{ label }}</div>
      <div class="stat-value" :style="color ? { color } : {}">{{ value }}</div>
      <div v-if="trend" class="stat-trend" :class="trend.startsWith('+') ? 'up' : 'down'">
        {{ trend }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  margin-bottom: 0;
}
.stat-body {
  padding: 20px;
  text-align: center;
}
.stat-label {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}
.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: var(--color-primary);
}
.stat-trend {
  font-size: 13px;
  margin-top: 4px;
}
.stat-trend.up {
  color: #66bb6a;
}
.stat-trend.down {
  color: #ff5252;
}
</style>