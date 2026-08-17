<script setup>
import { computed, ref, toRef, watch } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'

const props = defineProps({
  open: { type: Boolean, default: false },
  records: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' }
})

const emit = defineEmits(['close', 'submit'])
const bulkReleaseDir = ref('')
const bulkReleaseDirInput = ref(null)
const rowValues = ref({})
const projectCount = computed(
  () => new Set(props.records.map(record => String(record.project_id))).size
)
const bulkCharacterCount = computed(() => bulkReleaseDir.value.length)
const isBulkOverLimit = computed(() => bulkCharacterCount.value > 500)
const changedRecords = computed(() =>
  props.records.filter(
    record => normalize(rowValues.value[recordKey(record)]) !== normalize(record.release_dir)
  )
)
const invalidRecordKeys = computed(
  () =>
    new Set(
      props.records
        .filter(record => (rowValues.value[recordKey(record)] || '').length > 500)
        .map(recordKey)
    )
)
const changedCount = computed(() => changedRecords.value.length)
const hasInvalidRows = computed(() => invalidRecordKeys.value.size > 0)

const { dialogRef, handleDialogKeydown } = useDialogFocus(toRef(props, 'open'), {
  initialFocus: bulkReleaseDirInput,
  canClose: () => !props.saving,
  onEscape: () => emit('close')
})

watch(
  () => props.open,
  open => {
    if (!open) return
    bulkReleaseDir.value = ''
    rowValues.value = Object.fromEntries(
      props.records.map(record => [recordKey(record), record.release_dir || ''])
    )
  }
)

function recordKey(record) {
  return `${record.project_id}:${record.id}`
}

function normalize(value) {
  return String(value || '').trim()
}

function rowValue(record) {
  return rowValues.value[recordKey(record)] || ''
}

function isChanged(record) {
  return normalize(rowValue(record)) !== normalize(record.release_dir)
}

function isInvalid(record) {
  return invalidRecordKeys.value.has(recordKey(record))
}

function requestClose() {
  if (!props.saving) emit('close')
}

function submit() {
  if (props.saving || hasInvalidRows.value || changedCount.value === 0) return
  emit(
    'submit',
    changedRecords.value.map(record => ({
      project_id: Number(record.project_id),
      record_id: Number(record.id),
      release_dir: rowValue(record)
    }))
  )
}

function fillAllRows() {
  if (props.saving || isBulkOverLimit.value) return
  rowValues.value = Object.fromEntries(
    props.records.map(record => [recordKey(record), bulkReleaseDir.value])
  )
}

function fallbackDirectory(record) {
  return record.full_dir || record.release_dir_effective || ''
}

function resetRow(record) {
  rowValues.value[recordKey(record)] = record.release_dir || ''
}

function rowInputId(record) {
  return `batch-release-dir-row-${record.project_id}-${record.id}`
}

function rowInputLabel(record) {
  const project = record.project_name || `项目 #${record.project_id}`
  const module = record.module_name || `模块 #${record.module_id}`
  const version = record.version || record.tag || '无版本'
  return `${project} / ${module} / ${version} 的新 release_dir`
}
</script>

<template>
  <div v-if="open" class="batch-dir-mask" @mousedown.self="requestClose">
    <form
      ref="dialogRef"
      class="batch-dir-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="batch-release-dir-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
      @submit.prevent="submit"
    >
      <header class="batch-dir-header">
        <div>
          <span class="batch-dir-kicker">BATCH PATH UPDATE</span>
          <h2 id="batch-release-dir-title">批量更新 release_dir</h2>
          <p>逐行编辑需要变更的目录，只会提交已修改的记录。</p>
        </div>
        <button
          class="batch-dir-close"
          type="button"
          aria-label="关闭批量更新对话框"
          :disabled="saving"
          @click="requestClose"
        >
          ×
        </button>
      </header>

      <div class="batch-dir-body">
        <ol class="batch-dir-steps" aria-label="操作步骤">
          <li class="is-complete"><b>1</b><span>核对记录</span></li>
          <li class="is-active"><b>2</b><span>输入目录</span></li>
          <li><b>3</b><span>确认更新</span></li>
        </ol>

        <div class="batch-dir-summary" aria-label="更新范围">
          <span><b>{{ records.length }}</b> 条记录</span>
          <span><b>{{ projectCount }}</b> 个项目</span>
          <span class="changed-summary"><b>{{ changedCount }}</b> 已修改</span>
        </div>

        <div class="batch-dir-bulk">
          <label class="batch-dir-field" for="batch-release-dir-bulk-input">
            <span class="batch-dir-label">
              <b>统一填充（可选）</b>
              <small :class="{ 'is-over-limit': isBulkOverLimit }">
                {{ bulkCharacterCount }} / 500
              </small>
            </span>
            <textarea
              id="batch-release-dir-bulk-input"
              ref="bulkReleaseDirInput"
              v-model="bulkReleaseDir"
              rows="2"
              spellcheck="false"
              placeholder="/workspace/releases/project/run"
              :disabled="saving"
              :aria-invalid="isBulkOverLimit"
              aria-describedby="batch-release-dir-bulk-help"
            />
          </label>
          <button
            class="btn btn-default batch-dir-fill-button"
            type="button"
            :disabled="saving || isBulkOverLimit"
            aria-label="将统一填充值复制到所有选中记录"
            @click="fillAllRows"
          >
            填充所有行
          </button>
        </div>
        <p id="batch-release-dir-bulk-help" class="batch-dir-help">
          输入内容不会自动修改记录；点击“填充所有行”后才会应用到下方每一行。
        </p>

        <section class="batch-dir-preview" aria-labelledby="batch-release-dir-preview-title">
          <div class="batch-dir-preview-heading">
            <h3 id="batch-release-dir-preview-title">逐行变更集</h3>
            <span>空值会清除 release_dir，并回退显示 full_dir</span>
          </div>
          <div class="batch-dir-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>项目</th>
                  <th>模块</th>
                  <th>版本</th>
                  <th>当前 release_dir</th>
                  <th>新的 release_dir</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="record in records"
                  :key="recordKey(record)"
                  :class="{ 'is-changed': isChanged(record), 'is-invalid': isInvalid(record) }"
                >
                  <td>{{ record.project_name || `#${record.project_id}` }}</td>
                  <td>{{ record.module_name || `#${record.module_id}` }}</td>
                  <td>{{ record.version || record.tag || '-' }}</td>
                  <td class="path-cell current-path">
                    <code v-if="record.release_dir">{{ record.release_dir }}</code>
                    <span v-else class="fallback-value">
                      <b>未设置 · fallback</b>
                      <code>{{ fallbackDirectory(record) || 'full_dir 不可用' }}</code>
                    </span>
                  </td>
                  <td class="path-cell proposed-path">
                    <div class="row-editor">
                      <label class="sr-only" :for="rowInputId(record)">
                        {{ rowInputLabel(record) }}
                      </label>
                      <textarea
                        :id="rowInputId(record)"
                        v-model="rowValues[recordKey(record)]"
                        class="row-path-input"
                        rows="2"
                        spellcheck="false"
                        :disabled="saving"
                        :aria-label="rowInputLabel(record)"
                        :aria-invalid="isInvalid(record)"
                        :aria-describedby="
                          isInvalid(record) ? `${rowInputId(record)}-status` : undefined
                        "
                      />
                      <div class="row-editor-meta">
                        <span
                          :id="`${rowInputId(record)}-status`"
                          :class="{ 'is-invalid-text': isInvalid(record) }"
                        >
                          {{
                            isInvalid(record)
                              ? `${rowValue(record).length} / 500 · 超出限制`
                              : `${rowValue(record).length} / 500`
                          }}
                        </span>
                        <button
                          v-if="isChanged(record)"
                          type="button"
                          class="row-reset"
                          :disabled="saving"
                          :aria-label="`撤销 ${rowInputLabel(record)} 的修改`"
                          @click="resetRow(record)"
                        >
                          撤销修改
                        </button>
                      </div>
                      <span v-if="normalize(rowValue(record)) === ''" class="fallback-value">
                        <b>空值 · 回退 full_dir</b>
                        <code>{{ fallbackDirectory(record) || 'full_dir 不可用' }}</code>
                      </span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <p v-if="error" class="batch-dir-error" role="alert">{{ error }}</p>
      </div>

      <footer class="batch-dir-footer">
        <span>
          已修改 {{ changedCount }} 条
          <template v-if="hasInvalidRows"> · 请修正超长目录</template>
        </span>
        <div>
          <button class="btn btn-default" type="button" :disabled="saving" @click="requestClose">
            取消
          </button>
          <button
            class="btn"
            type="submit"
            :disabled="saving || hasInvalidRows || changedCount === 0"
          >
            {{ saving ? '更新中…' : `更新 ${changedCount} 条记录` }}
          </button>
        </div>
      </footer>
    </form>
  </div>
</template>

<style scoped>
.batch-dir-mask {
  position: fixed;
  z-index: 1300;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: var(--color-overlay);
}

.batch-dir-dialog {
  display: flex;
  flex-direction: column;
  width: min(1080px, 100%);
  max-height: min(820px, 94vh);
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-top: 4px solid var(--color-primary);
  border-radius: 6px;
  background: var(--color-surface-elevated);
  color: var(--color-text);
  box-shadow: 0 24px 64px var(--color-shadow);
}

.batch-dir-header,
.batch-dir-footer {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 20px;
}

.batch-dir-header {
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-elevated);
}

.batch-dir-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.batch-dir-header h2 {
  margin: 0;
  font-size: 19px;
  line-height: 1.25;
}

.batch-dir-header p {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.batch-dir-close {
  padding: 2px 8px;
  border: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 25px;
  line-height: 1;
}

.batch-dir-close:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}

.batch-dir-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px;
}

.batch-dir-steps {
  display: flex;
  align-items: center;
  margin: 0 0 14px;
  padding: 0;
  list-style: none;
}

.batch-dir-steps li {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--color-text-muted);
  font-size: 11px;
  font-weight: 700;
}

.batch-dir-steps li:not(:last-child)::after {
  content: '';
  flex: 1;
  height: 1px;
  margin: 0 10px;
  background: var(--color-border);
}

.batch-dir-steps b {
  display: grid;
  width: 21px;
  height: 21px;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: 50%;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
}

.batch-dir-steps .is-complete,
.batch-dir-steps .is-active {
  color: var(--color-text);
}

.batch-dir-steps .is-complete b {
  border-color: var(--color-success-border);
  background: var(--color-success-background);
  color: var(--color-success);
}

.batch-dir-steps .is-active b {
  border-color: var(--color-primary);
  background: var(--color-surface-selected);
  color: var(--color-primary);
}

.batch-dir-summary {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.batch-dir-summary span {
  padding: 5px 9px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-size: 11px;
}

.batch-dir-summary b {
  color: var(--color-text);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 13px;
}

.batch-dir-summary .changed-summary {
  border-color: var(--color-success-border);
  background: var(--color-success-background);
  color: var(--color-success);
}

.batch-dir-summary .changed-summary b {
  color: var(--color-success);
}

.batch-dir-bulk {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 10px;
}

.batch-dir-field {
  display: block;
}

.batch-dir-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
  font-size: 12px;
}

.batch-dir-label small {
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.batch-dir-label small.is-over-limit {
  color: var(--color-danger);
  font-weight: 700;
}

.batch-dir-field textarea {
  width: 100%;
  min-height: 58px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  line-height: 1.45;
}

.batch-dir-field textarea[aria-invalid='true'],
.row-path-input[aria-invalid='true'] {
  border-color: var(--color-danger);
}

.batch-dir-fill-button {
  min-height: 38px;
  white-space: nowrap;
}

.batch-dir-help,
.batch-dir-limit {
  margin: 6px 0 0;
  font-size: 11px;
}

.batch-dir-help {
  color: var(--color-text-secondary);
}

.batch-dir-limit,
.batch-dir-error {
  color: var(--color-danger);
}

.batch-dir-preview {
  margin-top: 17px;
  border: 1px solid var(--color-border);
  border-radius: 5px;
  background: var(--color-surface);
  overflow: hidden;
}

.batch-dir-preview-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
}

.batch-dir-preview-heading h3 {
  margin: 0;
  font-size: 13px;
}

.batch-dir-preview-heading span {
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
}

.batch-dir-table-wrap {
  max-height: 270px;
  overflow: auto;
}

.batch-dir-preview table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
  font-size: var(--table-font-size, 12px);
}

.batch-dir-preview th,
.batch-dir-preview td {
  padding: 9px 11px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}

.batch-dir-preview tr:last-child td {
  border-bottom: 0;
}

.batch-dir-preview th {
  position: sticky;
  z-index: 1;
  top: 0;
  background: var(--color-surface-elevated);
  color: var(--color-text-secondary);
  font-size: 0.85em;
  letter-spacing: 0.03em;
  white-space: nowrap;
}

.path-cell {
  width: 32%;
}

.path-cell code {
  display: block;
  max-width: 330px;
  color: inherit;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.current-path {
  color: var(--color-text-secondary);
}

.proposed-path {
  min-width: 330px;
}

.batch-dir-preview tr.is-changed td {
  background: color-mix(in srgb, var(--color-primary) 7%, transparent);
}

.batch-dir-preview tr.is-changed td:first-child {
  box-shadow: inset 3px 0 0 var(--color-primary);
}

.batch-dir-preview tr.is-invalid td {
  background: color-mix(in srgb, var(--color-danger) 8%, transparent);
}

.batch-dir-preview tr.is-invalid td:first-child {
  box-shadow: inset 3px 0 0 var(--color-danger);
}

.row-editor {
  display: grid;
  gap: 5px;
}

.row-path-input {
  width: 100%;
  min-width: 280px;
  min-height: 48px;
  padding: 6px 8px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 1em;
  line-height: 1.35;
}

.row-editor-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 20px;
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.85em;
}

.row-editor-meta .is-invalid-text {
  color: var(--color-danger);
  font-weight: 700;
}

.row-reset {
  padding: 2px 5px;
  border: 0;
  background: transparent;
  color: var(--color-primary);
  font-size: 1em;
  font-weight: 700;
}

.row-reset:hover:not(:disabled) {
  color: var(--color-primary-hover);
  text-decoration: underline;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.fallback-value {
  display: grid;
  gap: 3px;
}

.fallback-value b {
  color: var(--color-warning);
  font-size: 0.85em;
}

.fallback-value code {
  color: var(--color-text-secondary);
}

.batch-dir-error {
  margin: 12px 0 0;
  padding: 9px 11px;
  border: 1px solid var(--color-danger-border);
  border-radius: 4px;
  background: var(--color-danger-background);
  font-size: 12px;
}

.batch-dir-footer {
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}

.batch-dir-footer > span {
  color: var(--color-text-secondary);
  font-size: 11px;
}

.batch-dir-footer > div {
  display: flex;
  gap: 8px;
}

@media (max-width: 680px) {
  .batch-dir-mask {
    padding: 8px;
  }

  .batch-dir-dialog {
    max-height: calc(100dvh - 16px);
  }

  .batch-dir-header,
  .batch-dir-body,
  .batch-dir-footer {
    padding-right: 12px;
    padding-left: 12px;
  }

  .batch-dir-steps li span {
    display: none;
  }

  .batch-dir-steps li:not(:last-child)::after {
    margin: 0 7px;
  }

  .batch-dir-bulk {
    grid-template-columns: 1fr;
  }

  .batch-dir-fill-button {
    justify-self: end;
  }

  .batch-dir-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .batch-dir-footer > div {
    justify-content: flex-end;
  }
}
</style>
