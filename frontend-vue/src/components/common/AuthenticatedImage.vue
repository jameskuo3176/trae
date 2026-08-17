<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { annotationsApi } from '@/api/annotations'

const props = defineProps({
  image: { type: Object, required: true },
  alt: { type: String, default: '' }
})
const emit = defineEmits(['preview'])
const src = ref('')
const failed = ref(false)
let controller

function cleanup() {
  controller?.abort()
  if (src.value) URL.revokeObjectURL(src.value)
  src.value = ''
}

async function load() {
  cleanup()
  failed.value = false
  controller = new AbortController()
  try {
    const blob = await annotationsApi.image(props.image.url, controller.signal)
    src.value = URL.createObjectURL(blob)
  } catch (error) {
    if (error.code !== 'ERR_CANCELED') failed.value = true
  }
}

function openPreview(event) {
  emit('preview', {
    src: src.value,
    alt: props.alt || props.image.filename,
    trigger: event.currentTarget
  })
}

watch(() => props.image.url, load, { immediate: true })
onBeforeUnmount(cleanup)
</script>

<template>
  <button
    type="button"
    class="authenticated-image"
    :disabled="!src"
    :aria-label="`Preview ${image.filename}`"
    @click="openPreview"
  >
    <img v-if="src" :src="src" :alt="alt || image.filename" />
    <span v-else-if="failed">Image unavailable</span>
    <span v-else>Loading image…</span>
  </button>
</template>

<style scoped>
.authenticated-image {
  display: grid;
  width: 100%;
  min-height: 96px;
  padding: 0;
  place-items: center;
  overflow: hidden;
  border: 1px solid var(--color-border);
  background: var(--color-background);
  color: var(--color-text-secondary);
  font-size: 10px;
}
.authenticated-image:not(:disabled) {
  cursor: zoom-in;
}
.authenticated-image:not(:disabled):hover,
.authenticated-image:not(:disabled):focus-visible {
  border-color: var(--color-primary);
}
img {
  width: 100%;
  height: 118px;
  object-fit: cover;
}
</style>
