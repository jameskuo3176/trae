<script setup>
import { computed, ref, toRef, watch } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'

const props = defineProps({
  open: { type: Boolean, default: false },
  record: { type: Object, default: null },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' }
})

const emit = defineEmits(['close', 'submit'])
const releaseDir = ref('')
const releaseDirInput = ref(null)
const characterCount = computed(() => releaseDir.value.length)
const isOverLimit = computed(() => characterCount.value > 500)
const normalizedValue = computed(() => releaseDir.value.trim())
const normalizedOriginal = computed(() => String(props.record?.release_dir || '').trim())
const isUnchanged = computed(() => normalizedValue.value === normalizedOriginal.value)
const isFallback = computed(() => normalizedValue.value === '')
const fullDir = computed(() => props.record?.full_dir || '')
const effectiveDirectory = computed(() => normalizedValue.value || fullDir.value)
const recordIdentity = computed(() => {
  if (!props.record) return ''
  const project = props.record.project_name || `项目 #${props.record.project_id}`
  const module = props.record.module_name || `模块 #${props.record.module_id}`
  const version = props.record.version || props.record.tag || '无版本'
  return `${project} / ${module} / ${version}`
})

const { dialogRef, handleDialogKeydown } = useDialogFocus(toRef(props, 'open'), {
  initialFocus: releaseDirInput,
  canClose: () => !props.saving,
  onEscape: () => emit('close')
})

watch(
  () => props.open,
  open => {
    if (open) releaseDir.value = props.record?.release_dir || ''
  }
)

function requestClose() {
  if (!props.saving) emit('close')
}

function submit() {
  if (props.saving || isOverLimit.value || isUnchanged.value) return
  emit('submit', releaseDir.value)
}
</script>

<template>
  <div v-if="open && record" class="release-dir-mask" @mousedown.self="requestClose">
    <form
      ref="dialogRef"
      class="release-dir-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="release-dir-edit-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
      @submit.prevent="submit"
    >
      <header>
        <div>
          <span class="dialog-kicker">RECORD PATH OVERRIDE</span>
          <h2 id="release-dir-edit-title">编辑 release_dir</h2>
          <p>{{ recordIdentity }}</p>
        </div>
        <button
          type="button"
          class="dialog-close"
          aria-label="关闭 release_dir 编辑对话框"
          :disabled="saving"
          @click="requestClose"
        >
          ×
        </button>
      </header>

      <div class="release-dir-body">
        <label class="release-dir-field" for="release-dir-edit-input">
          <span>
            <b>release_dir</b>
            <small :class="{ 'is-invalid': isOverLimit }">{{ characterCount }} / 500</small>
          </span>
          <textarea
            id="release-dir-edit-input"
            ref="releaseDirInput"
            v-model="releaseDir"
            rows="5"
            spellcheck="false"
            placeholder="留空以使用 full_dir"
            :disabled="saving"
            :aria-invalid="isOverLimit"
            aria-describedby="release-dir-edit-help"
          />
        </label>
        <p id="release-dir-edit-help" class="field-help">
          清空此字段会移除显式 release_dir，并自动回退到原始 full_dir。
        </p>
        <p v-if="isOverLimit" class="field-error" role="alert">
          release_dir 长度不能超过 500 个字符。
        </p>

        <section class="path-context" aria-label="目录对比">
          <div>
            <span>原始 full_dir</span>
            <code>{{ fullDir || 'full_dir 不可用' }}</code>
          </div>
          <div :class="['effective-path', { 'is-fallback': isFallback }]">
            <span>
              保存后生效目录
              <b>{{ isFallback ? 'FALLBACK' : 'EXPLICIT' }}</b>
            </span>
            <code>{{ effectiveDirectory || 'full_dir 不可用' }}</code>
          </div>
        </section>

        <p v-if="error" class="dialog-error" role="alert">{{ error }}</p>
      </div>

      <footer>
        <span>
          {{
            isUnchanged
              ? '当前值未发生变化'
              : isFallback
                ? '将清除显式目录并使用 full_dir'
                : '将保存新的显式发布目录'
          }}
        </span>
        <div>
          <button type="button" class="btn btn-default" :disabled="saving" @click="requestClose">
            取消
          </button>
          <button class="btn" type="submit" :disabled="saving || isOverLimit || isUnchanged">
            {{ saving ? '保存中…' : '保存 release_dir' }}
          </button>
        </div>
      </footer>
    </form>
  </div>
</template>

<style scoped>
.release-dir-mask {
  position: fixed;
  z-index: 1300;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: var(--color-overlay);
}

.release-dir-dialog {
  display: flex;
  flex-direction: column;
  width: min(720px, 100%);
  max-height: min(760px, 94vh);
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-top: 4px solid var(--color-primary);
  border-radius: 6px;
  background: var(--color-surface-elevated);
  color: var(--color-text);
  box-shadow: 0 24px 64px var(--color-shadow);
}

.release-dir-dialog > header,
.release-dir-dialog > footer {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
}

.release-dir-dialog > header {
  border-bottom: 1px solid var(--color-border);
}

.dialog-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.release-dir-dialog h2 {
  margin: 0;
  font-size: 19px;
}

.release-dir-dialog header p {
  margin: 5px 0 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.dialog-close {
  padding: 2px 8px;
  border: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 25px;
  line-height: 1;
}

.dialog-close:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}

.release-dir-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 20px;
}

.release-dir-field {
  display: block;
}

.release-dir-field > span {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 7px;
  font-size: 12px;
}

.release-dir-field small {
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.release-dir-field small.is-invalid,
.field-error {
  color: var(--color-danger);
}

.release-dir-field textarea {
  width: 100%;
  min-height: 120px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  line-height: 1.45;
}

.release-dir-field textarea[aria-invalid='true'] {
  border-color: var(--color-danger);
}

.field-help,
.field-error {
  margin: 6px 0 0;
  font-size: 11px;
}

.field-help {
  color: var(--color-text-secondary);
}

.path-context {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.path-context > div {
  display: grid;
  gap: 6px;
  padding: 11px 12px;
  border: 1px solid var(--color-border);
  border-left: 3px solid var(--color-border-strong);
  border-radius: 4px;
  background: var(--color-surface);
}

.path-context span {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.path-context code {
  color: var(--color-text);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.path-context .effective-path {
  border-left-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 7%, var(--color-surface));
}

.path-context .effective-path.is-fallback {
  border-left-color: var(--color-warning);
  background: color-mix(in srgb, var(--color-warning) 7%, var(--color-surface));
}

.effective-path span b {
  color: var(--color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.85em;
  letter-spacing: 0.08em;
}

.effective-path.is-fallback span b {
  color: var(--color-warning);
}

.dialog-error {
  margin: 14px 0 0;
  padding: 9px 11px;
  border: 1px solid var(--color-danger-border);
  border-radius: 4px;
  background: var(--color-danger-background);
  color: var(--color-danger);
  font-size: 12px;
}

.release-dir-dialog > footer {
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}

.release-dir-dialog > footer > span {
  color: var(--color-text-secondary);
  font-size: 11px;
}

.release-dir-dialog > footer > div {
  display: flex;
  gap: 8px;
}

@media (max-width: 600px) {
  .release-dir-mask {
    padding: 8px;
  }

  .release-dir-dialog {
    max-height: calc(100dvh - 16px);
  }

  .release-dir-dialog > header,
  .release-dir-body,
  .release-dir-dialog > footer {
    padding-right: 12px;
    padding-left: 12px;
  }

  .release-dir-dialog > footer {
    align-items: stretch;
    flex-direction: column;
  }

  .release-dir-dialog > footer > div {
    justify-content: flex-end;
  }
}
</style>
