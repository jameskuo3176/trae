<script setup>
import { computed, ref, toRef, watch } from 'vue'
import { adminApi } from '@/api/admin'
import { useDialogFocus } from '@/composables/useDialogFocus'

const props = defineProps({
  open: { type: Boolean, default: false },
  projects: { type: Array, default: () => [] },
  configChecksum: { type: String, default: '' },
  initialProject: { type: String, default: '' }
})

const emit = defineEmits(['close', 'applied'])
const projectName = ref('')
const projectYaml = ref('')
const preview = ref(null)
const loading = ref(false)
const applying = ref(false)
const error = ref('')
const yamlInput = ref(null)
const maxLength = 500000

const characterCount = computed(() => projectYaml.value.length)
const isOverLimit = computed(() => characterCount.value > maxLength)
const canPreview = computed(
  () =>
    Boolean(projectName.value && projectYaml.value.trim() && props.configChecksum) &&
    !isOverLimit.value &&
    !loading.value &&
    !applying.value
)
const changes = computed(() =>
  Object.entries(preview.value?.plan?.changes || {})
    .filter(([, count]) => count > 0)
    .map(([name, count]) => ({ name, count }))
)
const deletionCount = computed(() => {
  const diff = preview.value?.yaml_diff
  if (diff) {
    return (diff.groups?.removed?.length || 0) + (diff.modules?.removed?.length || 0)
  }
  const values = preview.value?.plan?.changes || {}
  return (values.group_deletes || 0) + (values.module_link_deletes || 0)
})
const yamlDiffRows = computed(() => {
  const diff = preview.value?.yaml_diff
  if (!diff) return []
  const rows = [
    ['新增 Group', diff.groups?.added],
    ['更新 Group', diff.groups?.updated],
    ['删除 Group', diff.groups?.removed],
    ['新增 Module', diff.modules?.added],
    ['更新 Module', diff.modules?.updated],
    ['删除 Module', diff.modules?.removed],
    [
      '移动 Module',
      (diff.modules?.moved || []).map(item => `${item.name}（${item.from} → ${item.to}）`)
    ]
  ]
  return rows.filter(([, items]) => items?.length).map(([label, items]) => ({ label, items }))
})

const changeLabels = {
  project_owner_updates: 'Project Owner 更新',
  group_creates: 'Group 新增',
  group_updates: 'Group 更新',
  group_deletes: 'Group 删除',
  module_owner_updates: 'Module Owner 更新',
  legacy_owner_updates: '旧模块 Owner 更新',
  module_link_creates: 'Module 关联新增',
  module_link_moves: 'Module 移组',
  module_link_deletes: 'Module 关联删除'
}

const { dialogRef, handleDialogKeydown } = useDialogFocus(toRef(props, 'open'), {
  initialFocus: yamlInput,
  canClose: () => !loading.value && !applying.value,
  onEscape: () => requestClose()
})

watch(
  () => props.open,
  open => {
    if (!open) return
    projectName.value = props.projects.some(project => project.name === props.initialProject)
      ? props.initialProject
      : props.projects[0]?.name || ''
    projectYaml.value = ''
    preview.value = null
    error.value = ''
  }
)

watch([projectName, projectYaml], () => {
  preview.value = null
  error.value = ''
})

function requestClose() {
  if (!loading.value && !applying.value) emit('close')
}

function errorMessage(caught, fallback) {
  return caught.response?.data?.error || caught.response?.data?.detail || caught.message || fallback
}

async function requestPreview() {
  if (!canPreview.value) return
  loading.value = true
  error.value = ''
  try {
    preview.value = await adminApi.importReviewHierarchyProjectYaml({
      project: projectName.value,
      project_yaml: projectYaml.value,
      config_checksum: props.configChecksum,
      dry_run: true
    })
  } catch (caught) {
    error.value = errorMessage(caught, 'YAML 校验失败')
  } finally {
    loading.value = false
  }
}

async function applyImport() {
  if (!preview.value || applying.value) return
  applying.value = true
  error.value = ''
  try {
    const response = await adminApi.importReviewHierarchyProjectYaml({
      project: projectName.value,
      project_yaml: projectYaml.value,
      config_checksum: props.configChecksum,
      dry_run: false
    })
    emit('applied', response.status)
  } catch (caught) {
    error.value = errorMessage(caught, '项目 YAML 导入失败')
    if (caught.response?.status === 409) preview.value = null
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div v-if="open" class="yaml-import-mask" @mousedown.self="requestClose">
    <section
      ref="dialogRef"
      class="yaml-import-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="yaml-import-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
    >
      <header class="yaml-import-header">
        <div>
          <span>PROJECT CONFIG IMPORT</span>
          <h2 id="yaml-import-title">粘贴项目 YAML</h2>
          <p>只替换所选项目；其他项目和全局配置保持不变。</p>
        </div>
        <button
          type="button"
          aria-label="关闭项目 YAML 导入窗口"
          :disabled="loading || applying"
          @click="requestClose"
        >
          ×
        </button>
      </header>

      <div class="yaml-import-body">
        <ol class="import-steps" aria-label="导入步骤">
          <li :class="{ active: !preview }"><b>1</b> 粘贴配置</li>
          <li :class="{ active: preview }"><b>2</b> 预览差异</li>
          <li><b>3</b> 确认替换</li>
        </ol>

        <label class="field" for="yaml-import-project">
          <span>目标项目</span>
          <select id="yaml-import-project" v-model="projectName" :disabled="loading || applying">
            <option v-for="project in projects" :key="project.name" :value="project.name">
              {{ project.name }}{{ project.status === 'locked' ? '（已锁定）' : '' }}
            </option>
          </select>
        </label>

        <label class="field" for="yaml-import-content">
          <span>
            项目 YAML
            <small :class="{ invalid: isOverLimit }">
              {{ characterCount }} / {{ maxLength }}
            </small>
          </span>
          <textarea
            id="yaml-import-content"
            ref="yamlInput"
            v-model="projectYaml"
            rows="16"
            spellcheck="false"
            :disabled="loading || applying"
            :aria-invalid="isOverLimit"
            placeholder="owner: admin&#10;groups:&#10;  frontend:&#10;    owner: release&#10;    modules:&#10;      cpu:&#10;        release_owner: release"
          />
        </label>
        <p class="yaml-help">
          可粘贴裸项目配置、单个项目名映射，或仅含一个项目的
          <code>projects:</code> 映射。
        </p>

        <section v-if="preview" class="preview-panel" aria-live="polite">
          <div class="preview-heading">
            <div>
              <span>VALIDATION PASSED</span>
              <h3>{{ preview.project }} 替换预览</h3>
            </div>
            <strong>{{ preview.plan.total_changes }} 项数据库变更</strong>
          </div>
          <dl>
            <div>
              <dt>目标结构</dt>
              <dd>
                {{ preview.plan.desired.groups }} Groups /
                {{ preview.plan.desired.modules }} Modules
              </dd>
            </div>
            <div v-for="change in changes" :key="change.name">
              <dt>{{ changeLabels[change.name] || change.name }}</dt>
              <dd>{{ change.count }}</dd>
            </div>
          </dl>
          <div v-if="yamlDiffRows.length" class="name-diff">
            <div v-for="row in yamlDiffRows" :key="row.label">
              <strong>{{ row.label }}</strong>
              <span v-for="item in row.items" :key="item">{{ item }}</span>
            </div>
          </div>
          <p v-if="!changes.length" class="no-change">YAML 有效，数据库无需变更。</p>
          <p v-if="deletionCount" class="delete-warning" role="alert">
            注意：确认后将删除 {{ deletionCount }} 个未出现在粘贴配置中的 Group/Module 关联。
          </p>
        </section>

        <p v-if="error" class="yaml-error" role="alert">{{ error }}</p>
      </div>

      <footer class="yaml-import-footer">
        <span>{{ preview ? '已通过服务端校验，可确认替换' : '预览不会写入文件或数据库' }}</span>
        <div>
          <button
            type="button"
            class="btn btn-default"
            :disabled="loading || applying"
            @click="requestClose"
          >
            取消
          </button>
          <button
            v-if="!preview"
            type="button"
            class="btn"
            :disabled="!canPreview"
            @click="requestPreview"
          >
            {{ loading ? '校验中…' : '校验并预览' }}
          </button>
          <button
            v-else
            type="button"
            class="btn apply-button"
            :disabled="applying"
            @click="applyImport"
          >
            {{ applying ? '应用中…' : `确认替换 ${preview.project}` }}
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.yaml-import-mask {
  position: fixed;
  z-index: 1200;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgb(0 0 0 / 58%);
}
.yaml-import-dialog {
  display: grid;
  width: min(820px, 100%);
  max-height: calc(100vh - 40px);
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-top: 4px solid var(--color-primary);
  border-radius: 6px;
  background: var(--color-surface);
  box-shadow: 0 24px 70px rgb(0 0 0 / 30%);
}
.yaml-import-header,
.yaml-import-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  background: var(--color-surface-elevated);
}
.yaml-import-header {
  border-bottom: 1px solid var(--color-border);
}
.yaml-import-header span,
.preview-heading span {
  color: var(--color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.12em;
}
.yaml-import-header h2,
.preview-heading h3 {
  margin: 3px 0;
}
.yaml-import-header p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.yaml-import-header > button {
  border: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 26px;
  cursor: pointer;
}
.yaml-import-body {
  display: grid;
  gap: 14px;
  overflow-y: auto;
  padding: 18px 20px;
}
.import-steps {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 0;
  padding: 0;
  list-style: none;
}
.import-steps li {
  padding: 8px;
  border-bottom: 2px solid var(--color-border);
  color: var(--color-text-muted);
  font-size: 12px;
}
.import-steps li.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 700;
}
.import-steps b {
  margin-right: 5px;
}
.field {
  display: grid;
  gap: 6px;
}
.field > span {
  display: flex;
  justify-content: space-between;
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 700;
}
.field small {
  color: var(--color-text-muted);
  font-weight: 400;
}
.field small.invalid,
.yaml-error,
.delete-warning {
  color: var(--color-danger);
}
.field textarea {
  resize: vertical;
  min-height: 230px;
  font:
    12px/1.55 ui-monospace,
    SFMono-Regular,
    Consolas,
    monospace;
  tab-size: 2;
}
.yaml-help {
  margin: -8px 0 0;
  color: var(--color-text-muted);
  font-size: 11px;
}
.preview-panel {
  padding: 14px;
  border: 1px solid var(--color-success-border);
  background: var(--color-success-background);
}
.preview-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.preview-heading h3 {
  color: var(--color-text);
  font-size: 16px;
}
.preview-heading > strong {
  color: var(--color-success);
}
.preview-panel dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0 0;
}
.preview-panel dl > div {
  padding: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.preview-panel dt {
  color: var(--color-text-muted);
  font-size: 10px;
}
.preview-panel dd {
  margin: 3px 0 0;
  font-weight: 700;
}
.name-diff {
  display: grid;
  gap: 7px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--color-success-border);
}
.name-diff > div {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
}
.name-diff strong {
  min-width: 92px;
  font-size: 11px;
}
.name-diff span {
  padding: 2px 6px;
  border: 1px solid var(--color-border);
  border-radius: 3px;
  background: var(--color-surface);
  font:
    11px ui-monospace,
    SFMono-Regular,
    Consolas,
    monospace;
}
.no-change,
.delete-warning,
.yaml-error {
  margin: 10px 0 0;
  font-size: 12px;
}
.delete-warning,
.yaml-error {
  padding: 9px 10px;
  border: 1px solid var(--color-danger-border);
  background: var(--color-danger-background);
}
.yaml-import-footer {
  border-top: 1px solid var(--color-border);
}
.yaml-import-footer > span {
  color: var(--color-text-muted);
  font-size: 11px;
}
.yaml-import-footer > div {
  display: flex;
  gap: 8px;
}
.apply-button {
  min-width: 170px;
}
@media (max-width: 620px) {
  .yaml-import-mask {
    padding: 8px;
  }
  .yaml-import-dialog {
    max-height: calc(100vh - 16px);
  }
  .yaml-import-header,
  .yaml-import-footer {
    align-items: stretch;
  }
  .yaml-import-footer {
    flex-direction: column;
  }
  .yaml-import-footer > div {
    justify-content: flex-end;
  }
  .preview-panel dl {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
