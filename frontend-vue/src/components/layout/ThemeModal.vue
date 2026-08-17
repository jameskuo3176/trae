<script setup>
import { useTheme } from '@/composables/useTheme'
import TableFontSizeControl from '@/components/common/TableFontSizeControl.vue'

const { currentTheme, presets, showModal, saveThemeToStorage } = useTheme()

const labels = {
  dark: { title: 'Dark', helper: '深海军蓝工程工作台' },
  light: { title: 'Light', helper: '冷白高对比技术工作区' }
}
</script>

<template>
  <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
    <section
      class="modal-content"
      role="dialog"
      aria-modal="true"
      aria-labelledby="theme-modal-title"
    >
      <div class="modal-header">
        <div>
          <h3 id="theme-modal-title">主题设置</h3>
          <p>选择清晰、稳定的工作界面</p>
        </div>
        <button
          class="close-btn"
          type="button"
          aria-label="关闭主题设置"
          @click="showModal = false"
        >
          ×
        </button>
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
            <span
              class="theme-preview"
              :style="{ background: preset.background, borderColor: preset.border_strong }"
              aria-hidden="true"
            >
              <i :style="{ background: preset.surface }" />
              <b :style="{ background: preset.primary }" />
            </span>
            <span class="theme-copy">
              <strong>{{ labels[name].title }}</strong>
              <small>{{ labels[name].helper }}</small>
            </span>
            <span class="selection-mark" aria-hidden="true">✓</span>
          </button>
        </div>
        <div class="display-settings">
          <strong>表格显示</strong>
          <TableFontSizeControl />
          <small>统一应用于 Dashboard、评审和管理页面。</small>
        </div>
      </div>
      <div class="modal-footer">
        <span>设置会保存在此浏览器中</span>
        <button class="btn" type="button" @click="showModal = false">完成</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--color-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1200;
}
.modal-content {
  background: var(--color-surface-elevated);
  color: var(--color-text);
  border-radius: 8px;
  width: 520px;
  max-width: 90vw;
  max-height: 80vh;
  overflow-y: auto;
  border: 1px solid var(--color-border-strong);
  box-shadow: 0 18px 52px var(--color-shadow);
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
.modal-header p {
  margin-top: 3px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.close-btn {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.close-btn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.modal-body {
  padding: 20px;
}
.preset-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.preset-grid button {
  position: relative;
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) 20px;
  align-items: center;
  gap: 12px;
  min-height: 82px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  color: var(--color-text);
  text-align: left;
}
.preset-grid button:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.preset-grid button[aria-pressed='true'] {
  border-color: var(--color-primary);
  background: var(--color-surface-selected);
  color: var(--color-text-on-selected);
}
.theme-preview {
  position: relative;
  width: 52px;
  height: 44px;
  overflow: hidden;
  border: 1px solid;
  border-radius: 4px;
}
.theme-preview i {
  position: absolute;
  inset: 8px 6px 6px;
  border-radius: 2px;
}
.theme-preview b {
  position: absolute;
  right: 10px;
  bottom: 11px;
  width: 16px;
  height: 4px;
}
.theme-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;
}
.theme-copy strong {
  font-size: 14px;
}
.theme-copy small {
  color: var(--color-text-secondary);
  font-size: 11px;
  line-height: 1.35;
}
.preset-grid button:hover .theme-copy small,
.preset-grid button[aria-pressed='true'] .theme-copy small {
  color: inherit;
}
.selection-mark {
  visibility: hidden;
  color: var(--color-primary);
  font-weight: 800;
}
.display-settings {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border);
}
.display-settings small {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.preset-grid button[aria-pressed='true'] .selection-mark {
  visibility: visible;
}
.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
}
.modal-footer > span {
  margin-right: auto;
  color: var(--color-text-secondary);
  font-size: 11px;
}
@media (max-width: 560px) {
  .preset-grid {
    grid-template-columns: 1fr;
  }
  .modal-footer > span {
    display: none;
  }
}
</style>
