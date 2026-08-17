<script setup>
import { useTheme } from '@/composables/useTheme'

const { tableFontSize, setTableFontSize } = useTheme()
</script>

<template>
  <label class="table-font-control">
    <span>表格字号</span>
    <input
      type="range"
      min="10"
      max="18"
      step="1"
      aria-label="表格字号"
      :value="tableFontSize"
      @input="setTableFontSize($event.target.value)"
    />
    <output>{{ tableFontSize }}px</output>
  </label>
</template>

<style scoped>
.table-font-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: 11px;
  white-space: nowrap;
}
.table-font-control input {
  width: 88px;
}
.table-font-control output {
  min-width: 30px;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}
</style>
