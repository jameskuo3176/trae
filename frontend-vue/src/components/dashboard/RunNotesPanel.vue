<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { annotationsApi } from '@/api/annotations'
import AuthenticatedImage from '@/components/common/AuthenticatedImage.vue'
import SourceFileLink from '@/components/common/SourceFileLink.vue'

const dashboard = useDashboardStore()
const annotations = ref([])
const loading = ref(false)
const error = ref('')
const preview = ref(null)
const lightboxClose = ref(null)
let controller

const requestRecords = computed(() =>
  dashboard.selectedRecords.map(record => ({
    project_id: record.project_id,
    record_id: record.id
  }))
)
const recordFor = annotation =>
  dashboard.records.find(
    record =>
      String(record.project_id) === String(annotation.project_id) &&
      String(record.id) === String(annotation.record_id)
  )

const formatTimestamp = value =>
  value
    ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
        new Date(value)
      )
    : 'Unknown time'
const formatBytes = value =>
  !value
    ? '0 B'
    : value < 1024 * 1024
      ? `${Math.max(1, Math.round(value / 1024))} KiB`
      : `${(value / 1024 / 1024).toFixed(1)} MiB`

async function openPreview(payload) {
  preview.value = payload
  document.addEventListener('keydown', onLightboxKeydown)
  await nextTick()
  lightboxClose.value?.focus()
}

function closePreview() {
  const trigger = preview.value?.trigger
  preview.value = null
  document.removeEventListener('keydown', onLightboxKeydown)
  nextTick(() => trigger?.focus?.())
}

function onLightboxKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closePreview()
  } else if (event.key === 'Tab') {
    event.preventDefault()
    lightboxClose.value?.focus()
  }
}

async function load() {
  controller?.abort()
  if (!requestRecords.value.length) {
    annotations.value = []
    return
  }
  controller = new AbortController()
  loading.value = true
  error.value = ''
  try {
    annotations.value = await annotationsApi.batch(requestRecords.value, controller.signal)
  } catch (requestError) {
    if (requestError.code !== 'ERR_CANCELED') error.value = requestError.message
  } finally {
    loading.value = false
  }
}
watch(
  () => requestRecords.value.map(record => `${record.project_id}:${record.record_id}`).join('|'),
  load,
  { immediate: true }
)
onBeforeUnmount(() => {
  controller?.abort()
  document.removeEventListener('keydown', onLightboxKeydown)
})
</script>
<template>
  <section class="card annotations-panel">
    <header class="card-header">
      <span>用户添加注释信息</span>
      <small>{{ annotations.length }} annotated selected run(s)</small>
    </header>
    <div v-if="loading" class="empty-state">Loading annotation evidence…</div>
    <div v-else-if="error" class="error-line" role="alert">
      {{ error }}
      <button type="button" class="btn btn-sm btn-default" @click="load">Retry</button>
    </div>
    <div v-else-if="!dashboard.selectedRecords.length" class="empty-state aggregate-empty">
      Select one or more runs to review their annotation evidence.
    </div>
    <div v-else-if="!annotations.length" class="empty-state aggregate-empty">
      No saved annotation evidence exists for the currently selected runs.
    </div>
    <div v-else class="annotation-ledger">
      <article v-for="(item, index) in annotations" :key="`${item.project_id}:${item.record_id}`">
        <header>
          <span class="evidence-index">Evidence {{ String(index + 1).padStart(2, '0') }}</span>
          <div>
            <strong>{{ recordFor(item)?.module_name || item.record.module_name }}</strong>
            <span>
              {{ recordFor(item)?.project_name || `Project ${item.project_id}` }}
              · record #{{ item.record_id }}
            </span>
          </div>
          <code>{{ item.record.tag || item.record.version }}</code>
          <small>
            <SourceFileLink
              v-if="recordFor(item)?.full_dir || item.record.full_dir"
              :path="recordFor(item)?.full_dir || item.record.full_dir"
            />
            <template v-else>No run path</template>
          </small>
        </header>
        <div class="evidence-body">
          <p>{{ item.text || 'Image evidence only.' }}</p>
          <footer>
            <strong>{{
              item.author?.display_name || item.author?.username || 'Unknown author'
            }}</strong>
            <time :datetime="item.created_at">Opened {{ formatTimestamp(item.created_at) }}</time>
            <time :datetime="item.updated_at">Revised {{ formatTimestamp(item.updated_at) }}</time>
          </footer>
        </div>
        <div v-if="item.images.length" class="evidence-strip">
          <figure v-for="image in item.images" :key="image.id">
            <AuthenticatedImage
              :image="image"
              :alt="`${item.record.module_name}: ${image.filename}`"
              @preview="openPreview"
            />
            <figcaption>
              <span>{{ image.filename }}</span>
              <small>{{ image.content_type }} · {{ formatBytes(image.byte_size) }}</small>
            </figcaption>
          </figure>
        </div>
      </article>
    </div>
    <div
      v-if="preview"
      class="image-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="Dashboard evidence image preview"
      @click.self="closePreview"
    >
      <button
        ref="lightboxClose"
        type="button"
        aria-label="Close image preview"
        @click="closePreview"
      >
        ×
      </button>
      <img :src="preview.src" :alt="preview.alt" />
    </div>
  </section>
</template>
<style scoped>
.annotations-panel > .card-header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.annotations-panel > .card-header small {
  color: var(--color-text-secondary);
  font-weight: 400;
}
.annotation-ledger {
  display: grid;
  gap: 8px;
  padding: 8px;
}
.annotation-ledger article {
  display: grid;
  grid-template-columns: minmax(180px, 0.8fr) minmax(280px, 2fr);
  gap: 6px 16px;
  padding: 10px;
  border: 1px solid var(--color-border);
  border-left: 4px solid var(--color-primary);
  background: var(--color-background);
}
.annotation-ledger article > header {
  grid-row: span 1;
}
.annotation-ledger header,
.annotation-ledger header div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.annotation-ledger header span,
.annotation-ledger footer {
  color: var(--color-text-secondary);
  font-size: 10px;
}
.annotation-ledger .evidence-index {
  color: var(--color-primary);
  font-family: Consolas, monospace;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.annotation-ledger code {
  margin-top: 5px;
  color: var(--color-primary);
}
.annotation-ledger header small {
  overflow: hidden;
  color: var(--color-text-secondary);
  font:
    9px Consolas,
    monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.evidence-body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: space-between;
  gap: 10px;
}
.evidence-body p {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.5;
}
.evidence-body footer {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding-top: 7px;
  border-top: 1px solid var(--color-border);
}
.evidence-body footer strong {
  color: var(--color-text);
}
.evidence-strip {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 180px));
  gap: 6px;
}
.evidence-strip figure {
  min-width: 0;
  margin: 0;
  padding: 4px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.evidence-strip figcaption {
  padding: 5px 2px 1px;
  overflow: hidden;
  color: var(--color-text);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.evidence-strip figcaption span,
.evidence-strip figcaption small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}
.evidence-strip figcaption small {
  margin-top: 2px;
  color: var(--color-text-secondary);
}
.aggregate-empty {
  padding: 28px;
}
.error-line {
  padding: 12px;
  color: var(--color-danger);
}
.image-lightbox {
  position: fixed;
  inset: 0;
  z-index: 1400;
  display: grid;
  padding: 32px;
  place-items: center;
  background: var(--color-overlay);
}
.image-lightbox img {
  max-width: 94vw;
  max-height: 88vh;
  border: 1px solid var(--color-border-strong);
  box-shadow: 0 18px 52px var(--color-shadow);
}
.image-lightbox button {
  position: fixed;
  top: 16px;
  right: 20px;
  border: 0;
  background: transparent;
  color: white;
  font-size: 30px;
}
@media (max-width: 760px) {
  .annotation-ledger article {
    grid-template-columns: 1fr;
  }
  .annotation-ledger article > header {
    grid-row: auto;
  }
}
</style>
