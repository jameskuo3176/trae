<script setup>
import { ref } from 'vue'
import { adminApi } from '@/api/admin'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

defineProps({
  modelValue: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'success'])

const step = ref(1) // 1: upload, 2: preview, 3: confirm
const file = ref(null)
const fileInput = ref(null)
const previewData = ref([])
const releaseDir = ref('')
const autoRelease = ref(false)
const loading = ref(false)
const uploadProgress = ref(0)

function handleFileSelect(event) {
  const selectedFile = event.target.files[0]
  if (selectedFile) {
    file.value = selectedFile
    step.value = 2
    // 模拟预览数据
    previewData.value = [
      { module: 'module_a', version: 'v1.0', area: 100, timing: -0.5, power: 20 },
      { module: 'module_b', version: 'v1.1', area: 120, timing: -0.3, power: 22 }
    ]
  }
}

function dragOver(event) {
  event.preventDefault()
}

function drop(event) {
  event.preventDefault()
  const droppedFile = event.dataTransfer.files[0]
  if (droppedFile) {
    file.value = droppedFile
    step.value = 2
    previewData.value = [
      { module: 'module_a', version: 'v1.0', area: 100, timing: -0.5, power: 20 },
      { module: 'module_b', version: 'v1.1', area: 120, timing: -0.3, power: 22 }
    ]
  }
}

async function handleUpload() {
  loading.value = true
  uploadProgress.value = 0
  try {
    const formData = new FormData()
    formData.append('file', file.value)
    if (releaseDir.value) {
      formData.append('release_dir', releaseDir.value)
    }
    if (autoRelease.value) {
      formData.append('auto_release', 'true')
    }
    await adminApi.uploadCsv(formData)
    emit('success')
    step.value = 3
  } catch (e) {
    console.error('Upload failed:', e)
  } finally {
    loading.value = false
  }
}

function reset() {
  step.value = 1
  file.value = null
  previewData.value = []
  releaseDir.value = ''
  autoRelease.value = false
  if (fileInput.value) {
    fileInput.value.value = ''
  }
  emit('update:modelValue', false)
}

function close() {
  reset()
}
</script>

<template>
  <div v-if="modelValue" class="modal-overlay" @click.self="close">
    <div class="modal upload-modal">
      <div class="modal-header">
        <h3>📤 上传数据</h3>
        <button class="btn btn-sm btn-default" @click="close">✕</button>
      </div>
      <div class="modal-body">
        <div class="step-indicator">
          <div
            v-for="s in 3"
            :key="s"
            class="step-item"
            :class="{ active: s <= step, done: s < step }"
          >
            <span class="step-number">{{ s === 1 ? '📁' : s === 2 ? '👁️' : '✅' }}</span>
            <span class="step-label">{{ s === 1 ? '选择文件' : s === 2 ? '预览' : '完成' }}</span>
          </div>
        </div>

        <div v-if="step === 1" class="step-content">
          <div class="drop-zone" @dragover="dragOver" @drop="drop" @click="() => fileInput.click()">
            <div class="drop-icon">📂</div>
            <div class="drop-text">拖放文件到此处，或点击选择</div>
            <div class="drop-hint">支持 CSV / JSON 格式</div>
            <input
              ref="fileInput"
              type="file"
              accept=".csv,.json"
              style="display: none"
              @change="handleFileSelect"
            />
          </div>
        </div>

        <div v-if="step === 2" class="step-content">
          <div class="file-info">
            <span class="file-name">{{ file?.name }}</span>
            <span class="file-size">{{ (file?.size / 1024).toFixed(1) }} KB</span>
          </div>
          <div class="preview-section">
            <h4>📋 数据预览</h4>
            <div class="preview-table-wrapper">
              <table class="table preview-table">
                <thead>
                  <tr>
                    <th v-for="header in Object.keys(previewData[0])" :key="header">
                      {{ header }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in previewData" :key="row.module">
                    <td v-for="value in Object.values(row)" :key="value">{{ value }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="options-section">
            <div class="form-group">
              <label>Release目录（可选）</label>
              <input v-model="releaseDir" type="text" placeholder="/path/to/release" />
              <span class="hint">留空将使用记录的 full_dir</span>
            </div>
            <div class="form-group checkbox-group">
              <label>
                <input v-model="autoRelease" type="checkbox" />
                上传后自动发布
              </label>
            </div>
          </div>
        </div>

        <div v-if="step === 3" class="step-content success-content">
          <div class="success-icon">✅</div>
          <h3>上传成功！</h3>
          <p>数据已成功导入</p>
          <button class="btn" @click="close">完成</button>
        </div>
      </div>

      <div v-if="step === 2" class="modal-footer">
        <button class="btn btn-default" @click="step = 1">上一步</button>
        <button class="btn" :disabled="loading" @click="handleUpload">
          <LoadingSpinner v-if="loading" text="" />
          确认上传
        </button>
      </div>

      <div v-if="loading" class="progress-bar-container">
        <div class="progress-bar" :style="{ width: `${uploadProgress}%` }"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
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
  color: var(--color-text-secondary);
  opacity: 0.5;
}

.step-item.active,
.step-item.done {
  opacity: 1;
}

.step-item.active {
  color: var(--color-primary);
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
  background: rgba(0, 212, 255, 0.05);
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
  margin-bottom: 12px;
  font-size: 14px;
  color: var(--color-text-secondary);
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

.progress-bar-container {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: var(--color-surface-hover);
}

.progress-bar {
  height: 100%;
  background: var(--color-primary);
  transition: width 0.3s;
}
</style>
