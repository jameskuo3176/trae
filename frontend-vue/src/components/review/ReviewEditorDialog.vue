<script setup>
import { computed, ref, toRef } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'

const props = defineProps({
  open: Boolean,
  form: { type: Object, required: true },
  submitting: Boolean,
  error: { type: String, default: '' },
  scope: { type: String, default: '' },
  weekStart: { type: String, default: '' },
  editing: Boolean
})
const localForm = computed(() => props.form)

const emit = defineEmits(['close', 'submit'])
const titleInput = ref(null)
const { dialogRef, handleDialogKeydown } = useDialogFocus(toRef(props, 'open'), {
  initialFocus: titleInput,
  canClose: () => !props.submitting,
  onEscape: () => emit('close')
})
</script>

<template>
  <div v-if="open" class="display-picker-mask" @mousedown.self="$emit('close')">
    <form
      ref="dialogRef"
      class="review-editor"
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-editor-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
      @submit.prevent="$emit('submit')"
    >
      <header>
        <div>
          <span class="dialog-kicker">WEEKLY REVIEW DRAFT</span>
          <h2 id="review-editor-title">{{ editing ? '编辑评审' : '创建评审' }}</h2>
          <p>已根据当前可见周数据预填建议；内容绑定冻结快照，不混入后续上传数据。</p>
        </div>
        <button
          type="button"
          class="picker-close"
          aria-label="关闭"
          :disabled="submitting"
          @click="$emit('close')"
        >
          ×
        </button>
      </header>

      <div class="review-editor-body">
        <label class="editor-field editor-field-wide">
          <span>标题 <b aria-hidden="true">*</b></span>
          <input
            ref="titleInput"
            v-model="localForm.title"
            type="text"
            required
            :disabled="submitting"
          />
        </label>
        <label class="editor-field editor-field-wide">
          <span>概要 / 评审内容</span>
          <textarea v-model="localForm.summary" rows="4" :disabled="submitting" />
        </label>
        <label class="editor-field">
          <span>发现 <small>每行一项</small></span>
          <textarea v-model="localForm.findings" rows="7" :disabled="submitting" />
        </label>
        <label class="editor-field">
          <span>决策 <small>每行一项</small></span>
          <textarea v-model="localForm.decisions" rows="7" :disabled="submitting" />
        </label>
        <label class="editor-field">
          <span>下一步 <small>每行一项</small></span>
          <textarea v-model="localForm.nextSteps" rows="7" :disabled="submitting" />
        </label>
        <label class="editor-field">
          <span>结论 / 建议 <small>可选</small></span>
          <textarea v-model="localForm.verdict" rows="7" :disabled="submitting" />
        </label>
        <p v-if="error" class="editor-error" role="alert">{{ error }}</p>
      </div>

      <footer>
        <span class="editor-scope">{{ scope }} · {{ weekStart }}</span>
        <div>
          <button class="btn" type="button" :disabled="submitting" @click="$emit('close')">
            Cancel
          </button>
          <button class="btn btn-primary" type="submit" :disabled="submitting">
            {{ submitting ? '保存中…' : editing ? 'Save Review' : 'Create Review' }}
          </button>
        </div>
      </footer>
    </form>
  </div>
</template>
