<script setup>
import { useGvim } from '@/composables/useGvim'

defineProps({
  path: { type: String, default: '' },
  line: { type: [String, Number], default: null },
  label: { type: String, default: '' }
})

const { href, copy, copied } = useGvim()
</script>

<template>
  <span v-if="path" class="source-file-link">
    <a
      v-if="href(path, line)"
      :href="href(path, line)"
      :title="`使用 gVim 打开 ${path}`"
      class="gvim-link"
    >
      {{ label || path }}
    </a>
    <span v-else>{{ label || path }}</span>
    <button type="button" class="copy-button" :title="`复制路径 ${path}`" @click.stop="copy(path)">
      {{ copied ? '已复制' : '复制' }}
    </button>
  </span>
  <span v-else>-</span>
</template>

<style scoped>
.source-file-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
}
.gvim-link {
  color: var(--color-primary);
  overflow-wrap: anywhere;
  text-decoration: none;
}
.gvim-link:hover,
.gvim-link:focus-visible {
  text-decoration: underline;
}
.copy-button {
  flex: none;
  padding: 1px 5px;
  border: 1px solid var(--color-border);
  border-radius: 3px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 10px;
  cursor: pointer;
}
.copy-button:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
}
</style>
