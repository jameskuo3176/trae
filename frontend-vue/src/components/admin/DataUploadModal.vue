<script setup>
import { computed, ref, watch } from 'vue'
import { adminApi } from '@/api/admin'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useDialogFocus } from '@/composables/useDialogFocus'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  projects: { type: Array, default: () => [] },
  initialProjectId: { type: [String, Number], default: '' }
})
const emit = defineEmits(['update:modelValue', 'success'])

const step = ref(1)
const mode = ref('single')
const files = ref([])
const fileInput = ref(null)
const directoryInput = ref(null)
const previewFiles = ref([])
const previewSummary = ref({})
const selectedPreviewIndex = ref(0)
const projectId = ref('')
const moduleId = ref('')
const moduleSelectionExplicit = ref(false)
const moduleNameSource = ref('dirname')
const filenameSuffixes = ref('_qor,qor,_qor_report')
const releaseDir = ref('')
const autoRelease = ref(false)
const loading = ref(false)
const previewing = ref(false)
const error = ref('')
const selectionNotice = ref('')
const uploadResult = ref(null)

const writableProjects = computed(() =>
  props.projects.filter(project => project.is_writable !== false)
)
const selectedProject = computed(() =>
  writableProjects.value.find(project => String(project.id) === projectId.value)
)
const availableModules = computed(() =>
  Array.isArray(selectedProject.value?.modules) ? selectedProject.value.modules : []
)
const selectedModule = computed(() =>
  availableModules.value.find(module => String(module.id) === moduleId.value)
)
const busy = computed(() => loading.value || previewing.value)
const selectedPreview = computed(() => previewFiles.value[selectedPreviewIndex.value] || null)
const previewColumns = computed(() => selectedPreview.value?.columns || [])
const previewData = computed(() => selectedPreview.value?.preview || [])
const importTotals = computed(() => ({
  saved: Number(uploadResult.value?.saved ?? uploadResult.value?.total_saved ?? 0),
  updated: Number(uploadResult.value?.updated ?? uploadResult.value?.total_updated ?? 0),
  skipped: Number(uploadResult.value?.skipped ?? uploadResult.value?.total_skipped ?? 0),
  errors: Number(
    uploadResult.value?.errors ??
      uploadResult.value?.total_errors ??
      uploadResult.value?.failed_files ??
      0
  )
}))
const validPreviewCount = computed(() => Number(previewSummary.value.valid_files || 0))
const errorPreviewCount = computed(() => Number(previewSummary.value.error_files || 0))
const canConfirmUpload = computed(
  () =>
    Boolean(projectId.value && files.value.length) &&
    (mode.value !== 'single' || Boolean(moduleId.value)) &&
    validPreviewCount.value > 0
)
const confirmUploadLabel = computed(() => {
  if (mode.value === 'directory' && validPreviewCount.value > 0) {
    return `确认导入 ${validPreviewCount.value} 个模块`
  }
  return '确认导入'
})
const { dialogRef, handleDialogKeydown } = useDialogFocus(
  computed(() => props.modelValue),
  { canClose: () => !busy.value, onEscape: close }
)

watch(
  () => props.modelValue,
  open => {
    if (!open) return
    resetState()
    const preferred = String(props.initialProjectId || '')
    projectId.value = writableProjects.value.some(project => String(project.id) === preferred)
      ? preferred
      : writableProjects.value.length === 1
        ? String(writableProjects.value[0].id)
        : ''
  }
)

watch(projectId, () => {
  moduleId.value = availableModules.value.length === 1 ? String(availableModules.value[0].id) : ''
  moduleSelectionExplicit.value = false
})

watch(mode, () => {
  files.value = []
  previewFiles.value = []
  selectionNotice.value = ''
  error.value = ''
  if (fileInput.value) fileInput.value.value = ''
  if (directoryInput.value) directoryInput.value.value = ''
})

function resetState() {
  step.value = 1
  mode.value = 'single'
  files.value = []
  previewFiles.value = []
  previewSummary.value = {}
  selectedPreviewIndex.value = 0
  moduleId.value = ''
  moduleSelectionExplicit.value = false
  moduleNameSource.value = 'dirname'
  filenameSuffixes.value = '_qor,qor,_qor_report'
  releaseDir.value = ''
  autoRelease.value = false
  loading.value = false
  previewing.value = false
  error.value = ''
  selectionNotice.value = ''
  uploadResult.value = null
}

function errorMessage(caught, fallback) {
  const payload = caught?.response?.data ?? caught?.cause?.response?.data
  const failedFile = payload?.file_results?.find(result => result.ok === false)
  const responseMessage =
    typeof payload === 'string' && !payload.trim().startsWith('<')
      ? payload.trim()
      : payload?.error || payload?.detail || payload?.message
  return failedFile?.error || responseMessage || caught?.message || fallback
}

function formatItemErrors(errors) {
  return (errors || [])
    .map(item => {
      if (typeof item === 'string') return item
      if (item?.message) return item.message
      if (item?.reason) {
        return item.row ? `第 ${item.row} 行：${item.reason}` : item.reason
      }
      if (item?.error) return item.error
      return ''
    })
    .filter(Boolean)
    .join('；')
}

function normalizeName(value) {
  return String(value || '')
    .trim()
    .normalize('NFKC')
    .toLocaleLowerCase()
}

function autoMatchModule(names) {
  if (mode.value !== 'single' || moduleSelectionExplicit.value) return
  const csvNames = [...new Set(names.map(normalizeName).filter(Boolean))]
  if (csvNames.length !== 1) return
  const matches = availableModules.value.filter(
    module => normalizeName(module.name) === csvNames[0]
  )
  if (matches.length === 1) moduleId.value = String(matches[0].id)
}

function markModuleExplicit() {
  moduleSelectionExplicit.value = Boolean(moduleId.value)
}

function relativePath(file) {
  return file.webkitRelativePath || file.name
}

function appendCommonFormData(formData) {
  files.value.forEach(file => {
    formData.append('files', file)
    formData.append('file_paths', relativePath(file))
  })
  formData.append('project_id', projectId.value)
  formData.append('module_name_source', mode.value === 'directory' ? moduleNameSource.value : 'csv')
  formData.append('filename_suffixes', filenameSuffixes.value)
}

function normalizePreview(result) {
  if (Array.isArray(result.files)) return result.files
  return [
    {
      filename: files.value[0]?.name || '',
      relative_path: relativePath(files.value[0] || {}),
      inferred_module: result.module_names?.[0] || result.preview?.[0]?.module_name || '',
      module_exists: true,
      can_auto_create: false,
      total_rows: Number(result.total_rows || 0),
      columns: result.columns || [],
      preview: result.preview || [],
      errors: result.errors || []
    }
  ]
}

async function previewSelection(selectedFiles) {
  error.value = ''
  selectionNotice.value = ''
  if (!projectId.value) {
    error.value = '请先选择目标项目'
    return
  }
  const picked = Array.from(selectedFiles || [])
  const csvFiles = picked.filter(file => file.name.toLowerCase().endsWith('.csv'))
  if (!csvFiles.length) {
    error.value = '未找到可上传的 CSV 文件'
    return
  }
  if (mode.value === 'single' && picked.length > 1) csvFiles.splice(1)
  if (picked.length !== csvFiles.length) {
    selectionNotice.value = `已忽略 ${picked.length - csvFiles.length} 个非 CSV 文件`
  }
  files.value = csvFiles
  previewing.value = true
  try {
    const formData = new FormData()
    appendCommonFormData(formData)
    const result = await adminApi.previewCsvUpload(formData)
    previewFiles.value = normalizePreview(result)
    previewSummary.value = result.summary || {
      total_files: previewFiles.value.length,
      valid_files: previewFiles.value.filter(item => !(item.errors || []).length).length,
      total_rows: previewFiles.value.reduce((sum, item) => sum + Number(item.total_rows || 0), 0),
      error_files: previewFiles.value.filter(item => (item.errors || []).length).length
    }
    selectedPreviewIndex.value = Math.max(
      0,
      previewFiles.value.findIndex(item => !(item.errors || []).length)
    )
    autoMatchModule(
      previewFiles.value.flatMap(item => [
        item.inferred_module,
        ...(item.preview || []).map(row => row.module_name)
      ])
    )
    step.value = 2
  } catch (caught) {
    files.value = []
    error.value = errorMessage(caught, 'CSV 预览失败')
  } finally {
    previewing.value = false
  }
}

function handleFileSelect(event) {
  previewSelection(event.target.files)
}

function drop(event) {
  event.preventDefault()
  if (mode.value === 'single') previewSelection(event.dataTransfer.files)
}

async function handleUpload() {
  if (!projectId.value || !files.value.length) {
    error.value = !projectId.value ? '请选择目标项目' : '请选择 CSV 文件'
    return
  }
  if (mode.value === 'single' && !moduleId.value) {
    error.value = '请选择目标模块；CSV 中的 module_name 未能唯一匹配现有模块'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const formData = new FormData()
    appendCommonFormData(formData)
    formData.append('mark_released', String(autoRelease.value))
    formData.append('release_dir', releaseDir.value)
    if (mode.value === 'single' && moduleId.value) formData.append('module_id', moduleId.value)
    uploadResult.value = await adminApi.uploadCsv(formData)
    const writes = importTotals.value.saved + importTotals.value.updated
    if (uploadResult.value?.ok === false || writes === 0) {
      const failedFile = uploadResult.value?.file_results?.find(result => result.ok === false)
      throw new Error(failedFile?.error || uploadResult.value?.error || '没有导入任何记录')
    }
    emit('success', uploadResult.value)
    step.value = 3
  } catch (caught) {
    error.value = errorMessage(caught, '上传失败')
  } finally {
    loading.value = false
  }
}

function close() {
  if (busy.value) return
  resetState()
  projectId.value = ''
  emit('update:modelValue', false)
}
</script>

<template>
  <div v-if="modelValue" class="modal-overlay" @click.self="close">
    <section
      ref="dialogRef"
      class="modal upload-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="data-upload-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
    >
      <header class="modal-header">
        <div>
          <h3 id="data-upload-title">上传 QoR 数据</h3>
          <p>先检查文件与模块映射，再执行导入</p>
        </div>
        <button
          type="button"
          class="btn btn-sm btn-default"
          aria-label="关闭上传对话框"
          :disabled="busy"
          @click="close"
        >
          ✕
        </button>
      </header>

      <div class="modal-body">
        <ol class="step-indicator" aria-label="上传进度">
          <li
            v-for="(label, index) in ['配置与选择', '检查映射与数据', '导入汇总']"
            :key="label"
            class="step-item"
            :class="{ active: index + 1 === step, done: index + 1 < step }"
            :aria-current="index + 1 === step ? 'step' : undefined"
          >
            <span class="step-number">{{ index + 1 }}</span
            ><span class="step-label">{{ label }}</span>
          </li>
        </ol>

        <div v-if="step === 1" class="step-content">
          <fieldset class="mode-picker">
            <legend>上传方式</legend>
            <label class="mode-card" :class="{ selected: mode === 'single' }">
              <input v-model="mode" type="radio" value="single" :disabled="busy" />
              <span
                ><strong>单文件上传</strong><small>选择一个 CSV，并手动确认目标模块</small></span
              >
            </label>
            <label class="mode-card" :class="{ selected: mode === 'directory' }">
              <input v-model="mode" type="radio" value="directory" :disabled="busy" />
              <span><strong>整目录上传</strong><small>保留相对路径，批量检查模块映射</small></span>
            </label>
          </fieldset>

          <div class="control-grid">
            <div class="form-group project-field">
              <label for="upload-project">目标项目</label>
              <select id="upload-project" v-model="projectId" :disabled="busy">
                <option value="" disabled>请选择项目</option>
                <option
                  v-for="project in writableProjects"
                  :key="project.id"
                  :value="String(project.id)"
                >
                  {{ project.name }}
                </option>
              </select>
              <span v-if="!writableProjects.length" class="hint"
                >没有可写项目，请先创建或解锁项目。</span
              >
            </div>
            <div v-if="mode === 'single'" class="form-group project-field">
              <label for="upload-module">目标模块</label>
              <select
                id="upload-module"
                v-model="moduleId"
                :disabled="busy || !projectId"
                @change="markModuleExplicit"
              >
                <option value="" disabled>请选择模块</option>
                <option
                  v-for="module in availableModules"
                  :key="module.id"
                  :value="String(module.id)"
                >
                  {{ module.name }}
                </option>
              </select>
              <span class="hint">CSV module_name 可自动匹配；手动选择始终优先。</span>
            </div>
            <template v-else>
              <div class="form-group project-field">
                <label for="module-source">模块名推断方式</label>
                <select id="module-source" v-model="moduleNameSource" :disabled="busy">
                  <option value="dirname">父目录名（推荐）</option>
                  <option value="filename">文件名</option>
                </select>
              </div>
              <div v-if="moduleNameSource === 'filename'" class="form-group project-field">
                <label for="filename-suffixes">忽略的文件名后缀</label>
                <input
                  id="filename-suffixes"
                  v-model="filenameSuffixes"
                  type="text"
                  :disabled="busy"
                />
                <span class="hint">英文逗号分隔，按顺序移除。</span>
              </div>
            </template>
          </div>

          <aside v-if="mode === 'directory'" class="directory-note">
            <code>base/module_alu/module_alu_qor.csv → module_alu</code>
            <p>浏览器只发送你选择的 CSV 文件；服务器不会扫描任何服务器目录。</p>
          </aside>

          <button
            type="button"
            class="drop-zone"
            :class="{ 'is-loading': previewing }"
            :disabled="busy"
            :aria-label="mode === 'directory' ? '选择包含 CSV 的目录' : '选择 CSV 文件'"
            @dragover.prevent
            @drop="drop"
            @click="mode === 'directory' ? directoryInput?.click() : fileInput?.click()"
          >
            <LoadingSpinner v-if="previewing" text="正在解析并检查数据..." />
            <template v-else>
              <span class="drop-mark" aria-hidden="true">{{
                mode === 'directory' ? 'DIR' : 'CSV'
              }}</span>
              <span class="drop-text">{{
                mode === 'directory' ? '点击选择整个目录' : '拖放 CSV 到此处，或点击选择'
              }}</span>
              <span class="drop-hint">选择后仅预览，不会立即写入数据</span>
            </template>
          </button>
          <input
            ref="fileInput"
            class="visually-hidden"
            type="file"
            accept=".csv,text/csv"
            @change="handleFileSelect"
          />
          <input
            ref="directoryInput"
            class="visually-hidden"
            type="file"
            webkitdirectory
            multiple
            accept=".csv,text/csv"
            @change="handleFileSelect"
          />
          <p v-if="selectionNotice" class="selection-notice" role="status">{{ selectionNotice }}</p>
        </div>

        <div v-if="step === 2" class="step-content">
          <div class="upload-target">
            <span
              >项目 <strong>{{ selectedProject?.name || '-' }}</strong></span
            >
            <span
              >{{ mode === 'single' ? '模块' : '推断策略' }}
              <strong>{{
                mode === 'single'
                  ? selectedModule?.name || '待选择'
                  : moduleNameSource === 'dirname'
                    ? '父目录名'
                    : '文件名'
              }}</strong></span
            >
          </div>
          <div class="summary-strip" aria-live="polite">
            <span
              ><strong>{{ previewSummary.total_files || 0 }}</strong> 文件</span
            >
            <span class="status-valid"
              ><strong>{{ previewSummary.valid_files || 0 }}</strong> 可导入</span
            >
            <span
              ><strong>{{ previewSummary.total_rows || 0 }}</strong> 行</span
            >
            <span :class="{ 'status-error': previewSummary.error_files }"
              ><strong>{{ previewSummary.error_files || 0 }}</strong> 异常</span
            >
          </div>
          <p
            v-if="mode === 'directory' && errorPreviewCount && validPreviewCount"
            class="partial-warning"
            role="status"
          >
            {{ errorPreviewCount }} 个文件无法导入（如根目录 CSV），将跳过；其余
            {{ validPreviewCount }} 个文件可继续导入。
          </p>
          <p v-else-if="validPreviewCount === 0" class="upload-error inline-error" role="alert">
            所选文件均无法导入，请检查目录结构（base/module_name/*.csv）或 CSV 内容后重新选择。
          </p>

          <section class="manifest-section" aria-labelledby="manifest-title">
            <div class="preview-heading">
              <h4 id="manifest-title">文件清单与映射</h4>
              <span>选择可用文件查看真实数据</span>
            </div>
            <div class="manifest-scroll">
              <table class="table manifest-table">
                <thead>
                  <tr>
                    <th>相对路径</th>
                    <th>推断模块</th>
                    <th>映射</th>
                    <th>行数</th>
                    <th>检查结果</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(item, index) in previewFiles"
                    :key="`${item.relative_path}-${index}`"
                    :class="{ selected: index === selectedPreviewIndex }"
                    @click="selectedPreviewIndex = index"
                  >
                    <td>
                      <button
                        type="button"
                        class="path-button"
                        @click="selectedPreviewIndex = index"
                      >
                        {{ item.relative_path || item.filename }}
                      </button>
                    </td>
                    <td>{{ item.inferred_module || '—' }}</td>
                    <td>
                      <span
                        class="status-chip"
                        :class="item.module_exists ? 'ok' : item.can_auto_create ? 'warn' : 'bad'"
                        >{{
                          item.module_exists ? '已匹配' : item.can_auto_create ? '可新建' : '未匹配'
                        }}</span
                      >
                    </td>
                    <td>{{ item.total_rows || 0 }}</td>
                    <td class="result-cell" :class="{ 'status-error': (item.errors || []).length }">
                      {{ formatItemErrors(item.errors) || '通过' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="selectedPreview" class="preview-section">
            <div class="preview-heading">
              <h4>
                数据预览 ·
                <code>{{ selectedPreview.relative_path || selectedPreview.filename }}</code>
              </h4>
              <span>显示前 {{ previewData.length }} 行</span>
            </div>
            <div class="preview-table-wrapper">
              <table class="table preview-table">
                <thead>
                  <tr>
                    <th v-for="header in previewColumns" :key="header">{{ header }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in previewData" :key="rowIndex">
                    <td v-for="header in previewColumns" :key="header">{{ row[header] }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <details class="release-options">
            <summary>发布选项（默认不发布）</summary>
            <div class="options-section">
              <div class="form-group">
                <label for="release-dir">Release 目录（可选）</label
                ><input
                  id="release-dir"
                  v-model="releaseDir"
                  type="text"
                  placeholder="/path/to/release"
                /><span class="hint">留空将使用记录的 full_dir。</span>
              </div>
              <div class="form-group checkbox-group">
                <label><input v-model="autoRelease" type="checkbox" />导入后标记为已发布</label
                ><span class="hint release-warning"
                  >建议保持关闭。发布必须由 YAML 配置的 Release Owner 在网页中确认。</span
                >
              </div>
            </div>
          </details>
        </div>

        <div v-if="step === 3" class="step-content success-content">
          <span class="completion-mark" aria-hidden="true">✓</span>
          <h3>导入已完成</h3>
          <div class="summary-strip completion-summary">
            <span
              >新增 <strong>{{ importTotals.saved }}</strong></span
            ><span
              >更新 <strong>{{ importTotals.updated }}</strong></span
            ><span
              >跳过 <strong>{{ importTotals.skipped }}</strong></span
            ><span :class="{ 'status-error': importTotals.errors }"
              >错误 <strong>{{ importTotals.errors }}</strong></span
            >
          </div>
          <div v-if="uploadResult?.file_results?.length" class="manifest-scroll">
            <table class="table manifest-table">
              <thead>
                <tr>
                  <th>文件</th>
                  <th>模块</th>
                  <th>新增 / 更新 / 跳过</th>
                  <th>结果</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(item, index) in uploadResult.file_results"
                  :key="`${item.relative_path}-${index}`"
                >
                  <td>
                    <code>{{ item.relative_path || item.filename }}</code>
                  </td>
                  <td>{{ item.inferred_module || '—' }}</td>
                  <td>{{ item.saved || 0 }} / {{ item.updated || 0 }} / {{ item.skipped || 0 }}</td>
                  <td :class="{ 'status-error': item.ok === false || item.errors?.length }">
                    {{ item.error || formatItemErrors(item.errors) || '成功' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <button type="button" class="btn" @click="close">完成</button>
        </div>

        <p v-if="error" class="upload-error" role="alert">{{ error }}</p>
        <p class="sr-status" aria-live="polite">
          {{ previewing ? '正在检查文件' : loading ? '正在导入数据' : '' }}
        </p>
      </div>

      <footer v-if="step === 2" class="modal-footer">
        <button type="button" class="btn btn-default" :disabled="loading" @click="step = 1">
          上一步
        </button>
        <button
          type="button"
          class="btn"
          :disabled="loading || !canConfirmUpload"
          @click="handleUpload"
        >
          <LoadingSpinner v-if="loading" text="" />{{ confirmUploadLabel }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--color-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.upload-modal {
  width: 90%;
  max-width: 800px;
  max-height: 90vh;
  overflow-y: auto;
}

.step-indicator {
  display: flex;
  gap: 16px;
  justify-content: center;
  margin-bottom: 24px;
}

.step-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: var(--color-text-muted);
  opacity: 1;
}

.step-item.active {
  color: var(--color-primary);
}

.step-item.done {
  color: var(--color-success);
}

.step-number {
  font-size: 24px;
}

.step-label {
  font-size: 12px;
}

.drop-zone {
  border: 2px dashed var(--color-border);
  border-radius: 12px;
  padding: 48px 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.drop-zone:hover {
  border-color: var(--color-primary);
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.drop-zone.is-loading {
  cursor: wait;
  opacity: 0.75;
}
.drop-zone:hover :is(.drop-text, .drop-hint) {
  color: inherit;
}

.drop-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.drop-text {
  font-size: 16px;
  margin-bottom: 8px;
  color: var(--color-text);
}

.drop-hint {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.file-info {
  display: flex;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--color-surface-hover);
  border-radius: 8px;
  margin-bottom: 16px;
}

.upload-target {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.upload-target strong {
  color: var(--color-text);
}

.file-name {
  font-weight: 500;
}

.file-size {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.preview-section {
  margin-bottom: 24px;
}

.preview-section h4 {
  margin: 0;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.preview-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.preview-heading span {
  color: var(--color-text-muted);
  font-size: 11px;
}

.preview-table-wrapper {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
}

.preview-table {
  font-size: 13px;
}

.options-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 6px;
}

.form-group input[type='text'] {
  width: 100%;
}

.project-field {
  margin-bottom: 16px;
}

.project-field select {
  width: 100%;
}

.hint {
  display: block;
  font-size: 11px;
  color: var(--color-text-secondary);
  margin-top: 4px;
}

.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.success-content {
  text-align: center;
  padding: 24px 0;
}

.success-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.success-content h3 {
  margin-bottom: 8px;
}

.success-content p {
  color: var(--color-text-secondary);
  margin-bottom: 24px;
}

.upload-error {
  margin: 14px 0 0;
  padding: 10px 12px;
  border: 1px solid var(--color-danger-border);
  border-radius: 4px;
  background: var(--color-danger-background);
  color: var(--color-danger);
  font-size: 12px;
}

.upload-error.inline-error {
  margin: 0 0 16px;
}

.partial-warning {
  margin: 0 0 16px;
  padding: 10px 12px;
  border: 1px solid var(--color-warning-border, var(--color-border));
  border-radius: 4px;
  background: var(--color-warning-background, var(--color-surface-hover));
  color: var(--color-warning);
  font-size: 12px;
}

.upload-modal {
  max-width: 940px;
}

.modal-header h3 {
  margin: 0;
}

.modal-header p {
  margin: 3px 0 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.step-indicator {
  margin: 0 0 18px;
  padding: 0;
  list-style: none;
}

.step-item {
  position: relative;
  flex: 1;
  flex-direction: row;
  justify-content: center;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--color-border);
}

.step-item.active {
  border-color: var(--color-primary);
}

.step-item.done {
  border-color: var(--color-success);
}

.step-number {
  display: inline-grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
}

.mode-picker {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 16px;
  padding: 0;
  border: 0;
}

.mode-picker legend {
  grid-column: 1 / -1;
  margin-bottom: 7px;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 600;
}

.mode-card {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  cursor: pointer;
}

.mode-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-background, var(--color-surface-hover));
}

.mode-card input {
  margin-top: 3px;
  accent-color: var(--color-primary);
}

.mode-card strong,
.mode-card small {
  display: block;
}

.mode-card small {
  margin-top: 3px;
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 400;
}

.control-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.control-grid :is(select, input) {
  width: 100%;
}

.directory-note {
  margin: 0 0 14px;
  padding: 10px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--color-surface-hover);
}

.directory-note code,
.preview-heading code,
.path-button,
.manifest-table code {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Consolas, monospace);
}

.directory-note p {
  margin: 5px 0 0;
  color: var(--color-text-secondary);
  font-size: 11px;
}

.drop-zone {
  display: flex;
  width: 100%;
  flex-direction: column;
  align-items: center;
  border-radius: 6px;
  padding: 26px 20px;
  background: transparent;
  color: var(--color-text);
  font: inherit;
}

.drop-zone:focus-visible,
.mode-card:has(input:focus-visible) {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.drop-zone:disabled {
  cursor: wait;
}

.drop-mark {
  margin-bottom: 8px;
  color: var(--color-primary);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Consolas, monospace);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.selection-notice {
  margin: 8px 0 0;
  color: var(--color-warning);
  font-size: 12px;
}

.visually-hidden,
.sr-status {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  clip-path: inset(50%);
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-hover);
}

.summary-strip span {
  padding: 9px 12px;
  border-right: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: 12px;
}

.summary-strip span:last-child {
  border-right: 0;
}

.summary-strip strong {
  margin-right: 3px;
  color: var(--color-text);
  font-size: 14px;
}

.status-valid {
  color: var(--color-success) !important;
}

.status-error {
  color: var(--color-danger) !important;
}

.manifest-section {
  margin-bottom: 18px;
}

.manifest-scroll {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: 6px;
}

.manifest-table {
  width: 100%;
  min-width: 680px;
  font-size: 12px;
}

.manifest-table tr.selected {
  background: var(--color-primary-background, var(--color-surface-hover));
}

.path-button {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-primary);
  cursor: pointer;
  text-align: left;
}

.status-chip {
  display: inline-block;
  padding: 2px 6px;
  border: 1px solid currentColor;
  border-radius: 4px;
  font-size: 10px;
  white-space: nowrap;
}

.status-chip.ok {
  color: var(--color-success);
}

.status-chip.warn {
  color: var(--color-warning);
}

.status-chip.bad {
  color: var(--color-danger);
}

.result-cell {
  max-width: 250px;
}

.preview-section {
  margin-bottom: 18px;
}

.preview-heading h4 {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.release-options {
  border-top: 1px solid var(--color-border);
  padding-top: 12px;
}

.release-options summary {
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.release-options .options-section {
  margin-top: 12px;
}

.release-warning {
  color: var(--color-warning);
}

.completion-mark {
  display: inline-grid;
  width: 44px;
  height: 44px;
  place-items: center;
  margin-bottom: 10px;
  border: 2px solid var(--color-success);
  border-radius: 50%;
  color: var(--color-success);
  font-size: 26px;
}

.completion-summary {
  margin: 16px auto;
  text-align: left;
}

.success-content > .btn {
  margin-top: 18px;
}

@media (max-width: 640px) {
  .upload-modal {
    width: calc(100% - 16px);
    max-height: calc(100vh - 16px);
  }

  .mode-picker,
  .control-grid {
    grid-template-columns: 1fr;
  }

  .step-indicator {
    gap: 5px;
  }

  .step-item {
    align-items: flex-start;
    justify-content: flex-start;
  }

  .step-label {
    font-size: 10px;
  }

  .summary-strip {
    grid-template-columns: repeat(2, 1fr);
  }

  .summary-strip span:nth-child(2) {
    border-right: 0;
  }

  .summary-strip span:nth-child(-n + 2) {
    border-bottom: 1px solid var(--color-border);
  }
}
</style>
