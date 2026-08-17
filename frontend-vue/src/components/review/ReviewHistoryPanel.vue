<script setup>
defineProps({
  reviews: { type: Array, default: () => [] },
  reviewType: { type: String, required: true },
  statusLabel: { type: Function, required: true }
})

defineEmits(['submit', 'open', 'edit', 'remove'])
</script>

<template>
  <section class="review-list card">
    <div class="card-header">历史 {{ reviewType === 'project' ? 'Project' : 'Group' }} 评审</div>
    <div class="card-body">
      <div
        v-for="review in reviews"
        :key="`${review.project_id}:${review.review_type || reviewType}:${review.id}`"
        class="review-row"
      >
        <div>
          <strong>{{ review.title }}</strong>
          <span class="muted">{{ review.group_name || review.project_name || '' }}</span>
          <span
            :class="[
              'provenance-chip',
              { legacy: review.snapshot_provenance?.binding !== 'frozen' }
            ]"
          >
            {{
              review.snapshot_provenance?.binding === 'frozen'
                ? `Snapshot ${review.snapshot_provenance.id}`
                : 'Legacy / live-unbound'
            }}
          </span>
        </div>
        <div class="review-actions">
          <span class="status">{{ statusLabel(review.status) }}</span>
          <span v-if="review.status === 'submitted' && !review.can_review" class="review-waiting">
            等待有权限的审核人处理
          </span>
          <button v-if="review.can_submit" class="btn btn-sm" @click="$emit('submit', review)">
            {{ review.status === 'rejected' ? '重新提交' : '提交' }}
          </button>
          <button v-if="review.can_edit" class="btn btn-sm" @click="$emit('edit', review)">
            编辑
          </button>
          <button
            v-if="review.can_delete"
            class="btn btn-sm btn-danger"
            @click="$emit('remove', review)"
          >
            删除
          </button>
          <button class="btn btn-sm review-detail-button" @click="$emit('open', review, $event)">
            查看详情
          </button>
        </div>
      </div>
      <p v-if="!reviews.length" class="muted">暂无评审记录</p>
    </div>
  </section>
</template>
