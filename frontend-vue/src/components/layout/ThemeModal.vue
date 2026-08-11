<script setup>
import { useTheme } from '@/composables/useTheme'

const { THEME_FIELDS, currentTheme, presets, showModal, saveThemeToStorage, resetToDefault } =
  useTheme()
</script>

<template>
  <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
    <div class="modal-content">
      <div class="modal-header">
        <h3>主题设置</h3>
        <button class="close-btn" @click="showModal = false">×</button>
      </div>
      <div class="modal-body">
        <div class="preset-grid" role="group" aria-label="Theme presets">
          <button
            v-for="(preset, name) in presets"
            :key="name"
            type="button"
            :aria-pressed="currentTheme.name === name"
            @click="saveThemeToStorage(preset)"
          >
            <span :style="{ background: preset.primary }" />{{ name }}
          </button>
        </div>
        <div v-for="field in THEME_FIELDS" :key="field.key" class="theme-field">
          <label>{{ field.label }}</label>
          <div class="field-control">
            <input
              v-if="field.color"
              v-model="currentTheme[field.key]"
              type="color"
              @change="saveThemeToStorage(currentTheme)"
            />
            <input
              v-else
              v-model="currentTheme[field.key]"
              type="text"
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
.preset-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  margin-bottom: 18px;
}
.preset-grid button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--color-border);
  background: var(--color-background);
  color: var(--color-text);
  text-transform: capitalize;
}
.preset-grid button[aria-pressed='true'] {
  border-color: var(--color-primary);
}
.preset-grid span {
  width: 12px;
  height: 12px;
  border: 1px solid var(--color-border);
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
