<script setup>
defineProps({
  risk: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
  busy: { type: Boolean, default: false }
})
const emit = defineEmits(['change'])
</script>

<template>
  <label class="risk-rating-control">
    <span :class="['risk-badge', `risk-${risk.rating}`]">{{ risk.rating }}</span>
    <select
      :value="risk.manual_rating || ''"
      :disabled="disabled || busy"
      aria-label="修改风险等级"
      @change="emit('change', $event.target.value || null)"
    >
      <option value="">自动（{{ risk.auto_rating }}）</option>
      <option value="low">Low</option>
      <option value="medium">Medium</option>
      <option value="high">High</option>
    </select>
    <small v-if="risk.source === 'user_guardrail'">遵循前版人工判断</small>
    <small v-else-if="risk.source === 'manual'">人工设置</small>
  </label>
</template>

<style scoped>
.risk-rating-control {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.risk-rating-control select {
  min-width: 128px;
  padding: 4px 6px;
}
.risk-rating-control small {
  color: var(--color-text-secondary);
  font-size: 10px;
}
.risk-badge {
  min-width: 52px;
  padding: 2px 7px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  text-align: center;
  text-transform: uppercase;
}
.risk-low {
  background: var(--color-success-background);
  color: var(--color-success);
}
.risk-medium {
  background: var(--color-warning-background);
  color: var(--color-warning);
}
.risk-high {
  background: var(--color-danger-background);
  color: var(--color-danger);
}
.risk-unrated {
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
}
</style>
