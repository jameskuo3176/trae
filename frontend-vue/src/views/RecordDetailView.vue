<script setup>
import { computed, nextTick, ref, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { qorApi } from '@/api/qor'
import { annotationsApi } from '@/api/annotations'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import SourceFileLink from '@/components/common/SourceFileLink.vue'
import AuthenticatedImage from '@/components/common/AuthenticatedImage.vue'
import { normalizeTimingSections, timingMetricLabel } from '@/utils/timing'

const route = useRoute()
const record = ref(null)
const siblings = ref([])
const siblingCount = ref(0)
const loading = ref(true)
const error = ref('')
const annotation = ref(null)
const annotationLoading = ref(false)
const annotationError = ref('')
const canEditAnnotation = ref(false)
const editing = ref(false)
const draftText = ref('')
const removedImageIds = ref(new Set())
const newImages = ref([])
const saving = ref(false)
const preview = ref(null)
const lightboxClose = ref(null)

const groups = [
  {
    key: 'metadata',
    title: '元数据',
    fields: [
      ['id', 'Record ID'],
      ['project_id', '项目 ID'],
      ['project_name', '项目'],
      ['module_id', '模块 ID'],
      ['module_name', '模块'],
      ['version', '版本'],
      ['tag', 'Tag'],
      ['full_dir', '运行目录'],
      ['release_dir', '发布目录'],
      ['version_description', '版本描述'],
      ['owner_id', '上传者 ID'],
      ['uploader_username', '上传者'],
      ['uploader_display_name', '上传者显示名'],
      ['recorded_at_display', '记录时间'],
      ['released_at_display', '发布时间'],
      ['released_by', '发布者 ID'],
      ['is_released', '发布状态'],
      ['source_file', '源文件']
    ]
  },
  {
    key: 'area',
    title: '面积',
    fields: [
      ['area_total', '总面积'],
      ['area_combinational', '组合逻辑面积'],
      ['area_sequential', '时序逻辑面积'],
      ['area_black_box', '黑盒面积'],
      ['area_macro', '宏面积']
    ]
  },
  {
    key: 'power',
    title: '功耗',
    fields: [
      ['power_total', '总功耗'],
      ['power_internal', '内部功耗'],
      ['power_switching', '开关功耗'],
      ['power_leakage', '漏电功耗']
    ]
  },
  {
    key: 'cells',
    title: 'Cells / Physical',
    fields: [
      ['cell_count', 'Cell 数'],
      ['instance_count', 'Instance 数'],
      ['net_count', 'Net 数'],
      ['sequential_cell_count', '时序 Cell 数'],
      ['ram_cell_count', 'RAM Cell 数'],
      ['macro_cell_count', 'Macro Cell 数'],
      ['register_count', '寄存器数'],
      ['mbb_ratio', 'MBB 合并率'],
      ['clock_gating_ratio', '时钟门控率'],
      ['utilization', '利用率'],
      ['congestion', '拥塞'],
      ['congestion_h', '水平拥塞'],
      ['congestion_v', '垂直拥塞'],
      ['congestion_b', '拥塞 B']
    ]
  }
]

const backTarget = computed(() => {
  const next = Array.isArray(route.query.next) ? route.query.next[0] : route.query.next
  return typeof next === 'string' &&
    next.startsWith('/') &&
    !next.startsWith('//') &&
    !next.includes('\\')
    ? next
    : '/admin'
})

const timingSections = computed(() => normalizeTimingSections(record.value || {}))
const excludedExtraKeys = new Set([
  'clocks',
  'scenarios',
  'path_groups',
  'timing_sections',
  'timing_final'
])
const extraRows = computed(() =>
  Object.entries(record.value?.extra_fields || {}).filter(([key]) => !excludedExtraKeys.has(key))
)
const visibleExistingImages = computed(() =>
  (annotation.value?.images || []).filter(image => !removedImageIds.value.has(image.id))
)

function displayValue(value) {
  if (value == null || value === '') return '-'
  if (typeof value === 'number') return value.toFixed(2)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return value
}

function formatTimestamp(value) {
  if (!value) return 'Unknown time'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(new Date(value))
}

function formatBytes(value) {
  if (!value) return '0 B'
  return value < 1024 * 1024
    ? `${Math.max(1, Math.round(value / 1024))} KiB`
    : `${(value / 1024 / 1024).toFixed(1)} MiB`
}

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

async function loadAnnotation() {
  const projectId = record.value?.project_id || route.query.project_id
  if (!projectId) return
  annotationLoading.value = true
  annotationError.value = ''
  try {
    const data = await annotationsApi.get(projectId, record.value.id)
    annotation.value = data.annotation
    canEditAnnotation.value = data.can_edit === true
  } catch (requestError) {
    annotationError.value = requestError.message
  } finally {
    annotationLoading.value = false
  }
}

function startEdit() {
  draftText.value = annotation.value?.text || ''
  removedImageIds.value = new Set()
  newImages.value.forEach(image => URL.revokeObjectURL(image.preview))
  newImages.value = []
  annotationError.value = ''
  editing.value = true
}

function cancelEdit() {
  newImages.value.forEach(image => URL.revokeObjectURL(image.preview))
  newImages.value = []
  removedImageIds.value = new Set()
  draftText.value = annotation.value?.text || ''
  annotationError.value = ''
  editing.value = false
}

function addFiles(fileList) {
  const available = 6 - visibleExistingImages.value.length - newImages.value.length
  const files = [...fileList].slice(0, Math.max(0, available))
  newImages.value.push(
    ...files.map(file => ({
      id: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`,
      file,
      preview: URL.createObjectURL(file)
    }))
  )
}

function onDrop(event) {
  addFiles(event.dataTransfer.files)
}

function onPaste(event) {
  const items = event.clipboardData?.items || []
  const files = []
  for (const item of items) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  if (files.length) {
    addFiles(files)
    event.preventDefault()
  }
}

function removeExisting(id) {
  removedImageIds.value = new Set([...removedImageIds.value, id])
}

function removeNew(id) {
  const image = newImages.value.find(item => item.id === id)
  if (image) URL.revokeObjectURL(image.preview)
  newImages.value = newImages.value.filter(item => item.id !== id)
}

async function saveAnnotation() {
  saving.value = true
  annotationError.value = ''
  try {
    const form = new FormData()
    form.append('text', draftText.value)
    form.append(
      'keep_image_ids',
      JSON.stringify(visibleExistingImages.value.map(image => image.id))
    )
    newImages.value.forEach(image => form.append('images', image.file, image.file.name))
    const data = await annotationsApi.save(
      record.value.project_id || route.query.project_id,
      record.value.id,
      form
    )
    annotation.value = data.annotation
    canEditAnnotation.value = data.can_edit === true
    newImages.value.forEach(image => URL.revokeObjectURL(image.preview))
    newImages.value = []
    removedImageIds.value = new Set()
    editing.value = false
  } catch (requestError) {
    annotationError.value = requestError.message
  } finally {
    saving.value = false
  }
}

function isSourceKey(key, value) {
  return /^(source|source_file|file|path)$/i.test(key) && typeof value === 'string'
}

function detailLink(id) {
  return {
    name: 'RecordDetail',
    params: { id },
    query: { next: backTarget.value, project_id: record.value?.project_id }
  }
}

onMounted(async () => {
  try {
    const data = await qorApi.getRecordDetail(route.params.id, route.query.project_id)
    record.value = data.record
    siblings.value = data.siblings || []
    siblingCount.value = data.sibling_count ?? siblings.value.length
    await loadAnnotation()
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onLightboxKeydown)
  newImages.value.forEach(image => URL.revokeObjectURL(image.preview))
})
</script>

<template>
  <div class="detail-page">
    <router-link :to="backTarget" class="back-link">← 返回记录管理</router-link>
    <LoadingSpinner v-if="loading" text="加载记录详情..." />
    <div v-else-if="error" class="error-state">{{ error }}</div>
    <template v-else-if="record">
      <div class="card detail-header">
        <div class="card-header detail-title">
          <span>记录详情 #{{ record.id }}</span>
          <button
            v-if="canEditAnnotation && !editing"
            type="button"
            class="btn btn-sm"
            @click="startEdit"
          >
            编辑模式
          </button>
        </div>
        <div class="card-body">
          <strong>{{ record.module_name || '-' }}</strong>
          <span>{{ record.tag || record.version || '-' }}</span>
          <code>{{ record.full_dir || '-' }}</code>
        </div>
      </div>

      <div class="group-grid">
        <section class="card metric-group timing-dossier">
          <div class="card-header">Timing analysis / path groups</div>
          <div v-if="!Object.keys(timingSections).length" class="empty-state timing-empty">
            No scenario or path-group timing detail is available for this record.
          </div>
          <div v-else class="timing-analyses">
            <article
              v-for="(scenarios, analysisName) in timingSections"
              :key="analysisName"
              class="timing-analysis"
            >
              <h2>{{ analysisName }}</h2>
              <section
                v-for="(pathGroups, scenarioName) in scenarios"
                :key="scenarioName"
                class="timing-scenario"
              >
                <h3>{{ scenarioName }}</h3>
                <div class="table-wrap">
                  <table class="table timing-table">
                    <thead>
                      <tr>
                        <th>Path group</th>
                        <th
                          v-for="metric in [
                            ...new Set(
                              Object.values(pathGroups).flatMap(group => Object.keys(group))
                            )
                          ]"
                          :key="metric"
                        >
                          {{ timingMetricLabel(metric) }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(metrics, pathGroupName) in pathGroups" :key="pathGroupName">
                        <th>{{ pathGroupName }}</th>
                        <td
                          v-for="metric in [
                            ...new Set(
                              Object.values(pathGroups).flatMap(group => Object.keys(group))
                            )
                          ]"
                          :key="metric"
                        >
                          {{ displayValue(metrics[metric]) }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>
            </article>
          </div>
        </section>

        <section class="card metric-group annotation-dossier">
          <div class="card-header">Review annotation evidence</div>
          <LoadingSpinner v-if="annotationLoading" text="Loading annotation…" />
          <div v-else-if="editing" class="annotation-editor">
            <label>
              <span>Comment / annotation</span>
              <textarea
                v-model="draftText"
                rows="7"
                placeholder="Capture review conclusions, exceptions, and follow-up evidence…"
              />
            </label>
            <div
              class="image-drop-zone"
              tabindex="0"
              @dragover.prevent
              @drop.prevent="onDrop"
              @paste="onPaste"
            >
              <strong>Attach evidence images</strong>
              <span>PNG, JPEG, WebP, or GIF · 5 MiB each · 6 maximum · paste or drag images here</span>
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                multiple
                aria-label="Annotation images"
                @change="addFiles($event.target.files)"
              />
            </div>
            <div
              v-if="visibleExistingImages.length || newImages.length"
              class="annotation-gallery edit-gallery"
            >
              <figure v-for="image in visibleExistingImages" :key="image.id">
                <AuthenticatedImage :image="image" @preview="openPreview" />
                <figcaption>{{ image.filename }} · {{ formatBytes(image.byte_size) }}</figcaption>
                <button type="button" @click="removeExisting(image.id)">Remove</button>
              </figure>
              <figure v-for="image in newImages" :key="image.id">
                <img :src="image.preview" :alt="image.file.name" />
                <figcaption>{{ image.file.name }}</figcaption>
                <button type="button" @click="removeNew(image.id)">Remove</button>
              </figure>
            </div>
            <p v-if="annotationError" class="error-line" role="alert">{{ annotationError }}</p>
            <div class="editor-actions">
              <button
                type="button"
                class="btn btn-sm btn-default"
                :disabled="saving"
                @click="cancelEdit"
              >
                Cancel
              </button>
              <button type="button" class="btn btn-sm" :disabled="saving" @click="saveAnnotation">
                {{ saving ? 'Saving…' : 'Save annotation' }}
              </button>
            </div>
          </div>
          <div v-else class="annotation-read">
            <p v-if="annotationError" class="error-line" role="alert">{{ annotationError }}</p>
            <template v-if="annotation">
              <p class="annotation-copy">{{ annotation.text || 'No written annotation.' }}</p>
              <p class="annotation-byline">
                <strong>{{
                  annotation.author?.display_name || annotation.author?.username || 'Unknown author'
                }}</strong>
                <span>Opened {{ formatTimestamp(annotation.created_at) }}</span>
                <span>Last revised {{ formatTimestamp(annotation.updated_at) }}</span>
              </p>
              <div v-if="annotation.images?.length" class="annotation-gallery">
                <figure v-for="image in annotation.images" :key="image.id">
                  <AuthenticatedImage :image="image" @preview="openPreview" />
                  <figcaption>
                    <span>{{ image.filename }}</span>
                    <small>{{ image.content_type }} · {{ formatBytes(image.byte_size) }}</small>
                  </figcaption>
                </figure>
              </div>
            </template>
            <div v-else class="empty-state annotation-empty">
              No annotation evidence has been saved for this record.
            </div>
          </div>
        </section>

        <section v-for="group in groups" :key="group.key" class="card metric-group">
          <div class="card-header">{{ group.title }}</div>
          <div class="card-body table-wrap">
            <table class="table detail-table">
              <tbody>
                <tr v-for="[key, label] in group.fields" :key="key">
                  <th>
                    {{ label }} <small>{{ key }}</small>
                  </th>
                  <td>
                    <SourceFileLink v-if="key === 'source_file'" :path="record[key]" />
                    <pre v-else-if="typeof record[key] === 'object'">{{
                      displayValue(record[key])
                    }}</pre>
                    <span v-else>{{ displayValue(record[key]) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="card metric-group extra-fields">
          <div class="card-header">Extra Fields</div>
          <div class="card-body table-wrap">
            <table class="table detail-table">
              <tbody>
                <tr v-for="[key, value] in extraRows" :key="key">
                  <th>{{ key }}</th>
                  <td>
                    <SourceFileLink v-if="isSourceKey(key, value)" :path="value" />
                    <pre v-else>{{ displayValue(value) }}</pre>
                  </td>
                </tr>
                <tr v-if="extraRows.length === 0">
                  <td colspan="2" class="empty-state">无额外字段</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="record.raw_dc_report" class="card metric-group raw-report">
          <div class="card-header">原始 DC 报告</div>
          <div class="card-body">
            <details>
              <summary>展开原始上传内容</summary>
              <pre>{{ record.raw_dc_report }}</pre>
            </details>
          </div>
        </section>

        <section class="card metric-group siblings">
          <div class="card-header">同版本 Runs（{{ siblingCount }}）</div>
          <div class="card-body table-wrap">
            <table class="table detail-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>面积</th>
                  <th>WNS</th>
                  <th>功耗</th>
                  <th>Cells</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in siblings" :key="item.id">
                  <td>
                    <router-link :to="detailLink(item.id)">
                      {{ item.full_dir || item.version || `#${item.id}` }}
                    </router-link>
                  </td>
                  <td>{{ displayValue(item.area_total) }}</td>
                  <td>{{ displayValue(item.wns_setup) }}</td>
                  <td>{{ displayValue(item.power_total) }}</td>
                  <td>{{ displayValue(item.cell_count) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </template>
    <div
      v-if="preview"
      class="image-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="Annotation image preview"
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
  </div>
</template>

<style scoped>
.detail-page {
  max-width: 1400px;
  margin: 0 auto;
}
.back-link {
  display: inline-block;
  margin-bottom: 20px;
  color: var(--color-primary);
}
.detail-header .card-body {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 24px;
}
.detail-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.detail-header code {
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}
.group-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.table-wrap {
  padding: 0;
  overflow-x: auto;
}
.detail-table {
  margin: 0;
  font-size: 12px;
}
.detail-table th {
  width: 42%;
  white-space: nowrap;
}
.detail-table th small {
  display: block;
  color: var(--color-text-secondary);
  font-family: monospace;
  font-weight: 400;
}
.detail-table td {
  overflow-wrap: anywhere;
}
.detail-table pre {
  margin: 0;
  white-space: pre-wrap;
  font: inherit;
}
.extra-fields,
.raw-report,
.siblings,
.timing-dossier,
.annotation-dossier {
  grid-column: 1 / -1;
}
.timing-analyses {
  display: grid;
  gap: 10px;
  padding: 10px;
}
.timing-analysis {
  border: 1px solid var(--color-border-strong);
  background: var(--color-background);
}
.timing-analysis > h2 {
  margin: 0;
  padding: 8px 10px;
  border-bottom: 1px solid var(--color-border-strong);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.timing-scenario {
  margin: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.timing-scenario h3 {
  margin: 0;
  padding: 6px 8px;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  font-size: 11px;
  font-family: Consolas, monospace;
}
.timing-table {
  margin: 0;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.timing-table th:first-child {
  position: sticky;
  left: 0;
  background: var(--color-surface);
  text-align: left;
}
.timing-table tbody th:first-child {
  border-left: 3px solid var(--color-primary);
  color: var(--color-text);
  font-weight: 700;
}
.timing-table tbody tr:hover th:first-child {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.timing-table tbody tr:hover th:first-child * {
  color: inherit;
}
.timing-table td {
  text-align: right;
}
.timing-empty,
.annotation-empty {
  padding: 24px;
}
.annotation-editor,
.annotation-read {
  padding: 12px;
}
.annotation-editor label {
  display: grid;
  gap: 5px;
}
.annotation-editor label > span {
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.annotation-editor textarea {
  width: 100%;
  resize: vertical;
  font: inherit;
}
.image-drop-zone {
  display: grid;
  gap: 4px;
  margin-top: 10px;
  padding: 16px;
  border: 1px dashed var(--color-border-strong);
  background: var(--color-background);
  color: var(--color-text);
  text-align: center;
  outline: none;
  cursor: pointer;
}
.image-drop-zone:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-focus-ring);
}
.image-drop-zone span {
  color: var(--color-text-secondary);
  font-size: 10px;
}
.image-drop-zone input {
  margin: 6px auto 0;
}
.annotation-copy {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.6;
}
.annotation-byline {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 10px 0 0;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: 10px;
}
.annotation-byline strong {
  color: var(--color-text);
}
.annotation-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.annotation-gallery figure {
  min-width: 0;
  margin: 0;
  padding: 5px;
  border: 1px solid var(--color-border);
  background: var(--color-background);
}
.annotation-gallery figure > img {
  width: 100%;
  height: 118px;
  object-fit: cover;
}
.annotation-gallery figcaption {
  padding: 5px 2px 0;
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.annotation-gallery figcaption span,
.annotation-gallery figcaption small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}
.annotation-gallery figcaption small {
  margin-top: 2px;
  color: var(--color-text-secondary);
  font-size: 9px;
}
.edit-gallery figure {
  position: relative;
}
.edit-gallery figure > button {
  width: 100%;
  margin-top: 4px;
  border: 1px solid var(--color-danger);
  background: var(--color-danger-background);
  color: var(--color-danger);
  font-size: 10px;
}
.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 12px;
}
.error-line {
  margin: 8px 0;
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
  max-width: min(1100px, 94vw);
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
.raw-report pre {
  max-height: 520px;
  overflow: auto;
  white-space: pre-wrap;
}
@media (max-width: 480px) {
  .group-grid {
    grid-template-columns: 1fr;
  }
}
</style>
