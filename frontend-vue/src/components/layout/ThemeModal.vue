<script setup>
import { useTheme } from '@/composables/useTheme'

const { THEME_FIELDS, currentTheme, showModal, saveThemeToStorage, resetToDefault } = useTheme()
</script>

<template>
  <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
    <div class="modal-content">
      <div class="modal-header">
        <h3>主题设置</h3>
        <button class="close-btn" @click="showModal = false">×</button>
      </div>
      <div class="modal-body">
        <div v-for="field in THEME_FIELDS" :key="field.key" class="theme-field">
          <label>{{ field.label }}</label>
          <div class="field-control">
            <input
              v-if="field.color"
              type="color"
              v-model="currentTheme[field.key]"
              @change="saveThemeToStorage(currentTheme)"
            />
            <input
              v-else
              type="text"
              v-model="currentTheme[field.key]"
              @change="saveThemeToStorage(currentTheme)"
            />
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-default" @click="resetToDefault">恢复默认</button>
        <button class="btn" @click="showModal = false">关闭</button>
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
.modal-content {
  background: var(--color-surface);
  border-radius: 12px;
  width: 480px;
  max-width: 90vw;
  max-height: 80vh;
  overflow-y: auto;
  border: 1px solid var(--color-border);
}
.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-header h3 {
  font-size: 16px;
}
.close-btn {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.modal-body {
  padding: 20px;
}
.theme-field {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.theme-field label {
  font-size: 14px;
}
.field-control input[type='color'] {
  width: 40px;
  height: 32px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  cursor: pointer;
  padding: 2px;
}
.field-control input[type='text'] {
  width: 200px;
}
.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>