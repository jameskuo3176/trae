<script setup>
import { computed } from 'vue'
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  show: { type: Boolean, default: undefined },
  title: { type: String, default: '确认操作' },
  message: { type: String, default: '确定要执行此操作吗？' },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  loading: { type: Boolean, default: false },
  isDanger: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])
const visible = computed(() => props.show ?? props.modelValue)
function cancel() {
  emit('update:modelValue', false)
  emit('cancel')
}
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="emit('update:modelValue', false)">
    <div class="dialog">
      <div class="dialog-header">{{ title }}</div>
      <div class="dialog-body">{{ message }}</div>
      <div class="dialog-footer">
        <button class="btn btn-default" :disabled="loading" @click="cancel">
          {{ cancelText }}
        </button>
        <button
          class="btn"
          :class="props.isDanger ? 'btn-danger' : 'btn-primary'"
          :disabled="loading"
          @click="emit('confirm')"
        >
          {{ loading ? '处理中...' : confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.dialog {
  background: var(--color-surface);
  border-radius: 12px;
  width: 380px;
  max-width: 90vw;
  border: 1px solid var(--color-border);
}
.dialog-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  font-size: 16px;
  font-weight: 600;
}
.dialog-body {
  padding: 20px;
  font-size: 14px;
  color: var(--color-text-secondary);
}
.dialog-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
