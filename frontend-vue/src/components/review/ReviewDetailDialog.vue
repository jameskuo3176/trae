<script setup>
import { computed, nextTick, ref, toRef, watch } from 'vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useDialogFocus } from '@/composables/useDialogFocus'

const props = defineProps({
  open: Boolean,
  review: { type: Object, default: null },
  loading: Boolean,
  error: { type: String, default: '' },
  action: { type: String, default: '' },
  comment: { type: String, default: '' },
  submitting: Boolean,
  statusLabel: { type: Function, required: true },
  periodLabel: { type: Function, required: true },
  formatTime: { type: Function, required: true }
})

const emit = defineEmits(['close', 'begin-action', 'cancel-action', 'confirm', 'update:comment'])
const closeButton = ref(null)
const commentInput = ref(null)
let decisionReturnFocus = null
const { dialogRef, handleDialogKeydown } = useDialogFocus(toRef(props, 'open'), {
  initialFocus: closeButton,
  canClose: () => !props.submitting,
  onEscape: () => emit(props.action ? 'cancel-action' : 'close')
})

watch(
  () => props.action,
  async (action, previousAction) => {
    if (action) {
      decisionReturnFocus = document.activeElement
      await nextTick()
      commentInput.value?.focus()
    } else if (previousAction) {
      const target = decisionReturnFocus
      decisionReturnFocus = null
      await nextTick()
      target?.focus?.()
    }
  }
)

function readable(value) {
  if (Array.isArray(value)) return value.map(readable).join(' · ')
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${readable(item)}`)
      .join(' · ')
  }
  return String(value)
}

function items(value) {
  if (value === null || value === undefined || value === '') return []
  if (Array.isArray(value)) {
    return value.map((item, index) =>
      typeof item === 'object'
        ? {
            label: item.name || item.metric || item.title || `项目 ${index + 1}`,
            value: readable(item)
          }
        : { label: '', value: String(item) }
    )
  }
  if (typeof value === 'object') {
    return Object.entries(value).map(([label, item]) => ({ label, value: readable(item) }))
  }
  return [{ label: '', value: String(value) }]
}

const sections = computed(() =>
  [
    ['key_metrics', '关键指标'],
    ['findings', '发现'],
    ['decisions', '决策'],
    ['next_steps', '下一步'],
    ['risks', '风险']
  ]
    .map(([key, title]) => ({ key, title, values: items(props.review?.[key]) }))
    .filter(section => section.values.length)
)

const timeline = computed(() => {
  if (!props.review) return []
  return [
    { label: '创建', time: props.review.created_at },
    { label: '提交', time: props.review.submitted_at },
    ...(props.review.resubmitted_at
      ? [{ label: '重新提交', time: props.review.resubmitted_at }]
      : []),
    {
      label: props.review.status === 'rejected' ? '驳回' : '审核',
      time: props.review.reviewed_at
    }
  ]
})
</script>

<template>
  <div v-if="open" class="display-picker-mask" @mousedown.self="$emit('close')">
    <section
      ref="dialogRef"
      class="review-detail-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-detail-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
    >
      <header>
        <div>
          <span class="dialog-kicker">REVIEW DECISION RECORD</span>
          <h2 id="review-detail-title">{{ review?.title || '评审详情' }}</h2>
          <p v-if="review">{{ review.review_type === 'project' ? 'Project' : 'Group' }}</p>
        </div>
        <button
          ref="closeButton"
          type="button"
          class="picker-close"
          aria-label="关闭评审详情"
          :disabled="submitting"
          @click="$emit('close')"
        >
          ×
        </button>
      </header>
      <LoadingSpinner v-if="loading" text="加载评审记录..." />
      <div v-else-if="error && !review" class="review-detail-load-error" role="alert">
        {{ error }}
      </div>
      <template v-else-if="review">
        <div class="review-detail-body">
          <div class="review-detail-meta">
            <dl>
              <div>
                <dt>状态</dt>
                <dd>
                  <span class="status">{{ statusLabel(review.status) }}</span>
                </dd>
              </div>
              <div>
                <dt>周期</dt>
                <dd>{{ periodLabel(review.period) }}</dd>
              </div>
              <div>
                <dt>范围</dt>
                <dd>{{ review.group_name || review.project_name || review.subsystem || '-' }}</dd>
              </div>
              <div>
                <dt>创建人</dt>
                <dd>
                  {{
                    review.leader_name ||
                    review.manager_name ||
                    `ID ${review.leader_id || review.manager_id}`
                  }}
                </dd>
              </div>
            </dl>
          </div>

          <section
            :class="[
              'snapshot-provenance',
              { legacy: review.snapshot_provenance?.binding !== 'frozen' }
            ]"
          >
            <h3>冻结输入来源</h3>
            <template v-if="review.snapshot_provenance?.binding === 'frozen'">
              <p>
                Snapshot {{ review.snapshot_provenance.id }} ·
                {{ review.snapshot_provenance.week_start }} · config
                {{ review.snapshot_provenance.config_version || '—' }}
              </p>
              <code>{{ review.snapshot_provenance.checksum }}</code>
              <strong>
                {{ review.snapshot_provenance.verified ? '完整性校验通过' : '完整性校验失败' }}
              </strong>
            </template>
            <p v-else>Legacy / live-unbound：此历史记录创建于冻结绑定契约之前。</p>
          </section>

          <section v-if="review.summary" class="review-evidence-section">
            <h3>概要</h3>
            <p>{{ review.summary }}</p>
          </section>
          <section v-if="review.verdict" class="review-evidence-section review-verdict">
            <h3>结论</h3>
            <p>{{ review.verdict }}</p>
          </section>
          <section v-for="section in sections" :key="section.key" class="review-evidence-section">
            <h3>{{ section.title }}</h3>
            <ul>
              <li v-for="(item, index) in section.values" :key="index">
                <strong v-if="item.label">{{ item.label }}</strong
                ><span>{{ item.value }}</span>
              </li>
            </ul>
          </section>
          <section class="review-timeline-section">
            <h3>状态时间线</h3>
            <ol class="review-timeline">
              <li v-for="event in timeline" :key="event.label" :class="{ complete: event.time }">
                <span class="timeline-marker" />
                <div>
                  <strong>{{ event.label }}</strong
                  ><time>{{ event.time ? formatTime(event.time) : '尚未发生' }}</time>
                </div>
              </li>
            </ol>
          </section>
          <section v-if="review.reviewed_at" class="review-outcome">
            <h3>审核结果</h3>
            <p>
              <strong>{{ review.reviewer_name || `审核人 ID ${review.reviewed_by}` }}</strong> ·
              {{ formatTime(review.reviewed_at) }}
            </p>
            <blockquote v-if="review.review_comment">{{ review.review_comment }}</blockquote>
          </section>
          <div
            v-if="review.status === 'submitted' && !review.can_review"
            class="review-waiting-panel"
          >
            <strong>等待有权限的审核人处理</strong>
          </div>
          <form v-if="action" class="review-decision-form" @submit.prevent="$emit('confirm')">
            <label
              ><span>{{ action === 'approve' ? '批准意见' : '驳回意见' }}</span
              ><textarea
                ref="commentInput"
                :value="comment"
                rows="4"
                :disabled="submitting"
                @input="$emit('update:comment', $event.target.value)"
              />
            </label>
            <div>
              <button type="button" class="btn" @click="$emit('cancel-action')">取消</button
              ><button
                :class="['btn', action === 'approve' ? 'btn-success' : 'btn-danger']"
                type="submit"
              >
                {{ submitting ? '处理中…' : `确认${action === 'approve' ? '批准' : '驳回'}` }}
              </button>
            </div>
          </form>
          <p v-if="error" class="editor-error" role="alert">{{ error }}</p>
        </div>
        <footer>
          <span class="editor-scope">项目 {{ review.project_id }} · Review {{ review.id }}</span>
          <div>
            <template v-if="review.status === 'submitted' && review.can_review && !action">
              <button type="button" class="btn btn-danger" @click="$emit('begin-action', 'reject')">
                驳回
              </button>
              <button
                type="button"
                class="btn btn-success"
                @click="$emit('begin-action', 'approve')"
              >
                批准
              </button>
            </template>
            <button type="button" class="btn" :disabled="submitting" @click="$emit('close')">
              关闭
            </button>
          </div>
        </footer>
      </template>
    </section>
  </div>
</template>
