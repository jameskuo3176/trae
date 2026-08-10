<script setup>
import { ref, onMounted, computed } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import FilterBar from '@/components/filters/FilterBar.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { qorApi } from '@/api/qor'

const activeTab = ref('tile')
const reviews = ref([])
const loading = ref(false)
const filters = useFiltersStore()
const tileReview = ref({
  status: 'DRAFT',
  comment: '',
  qaSignoff: false
})
const groupReview = ref({
  status: 'DRAFT',
  passNoPass: '',
  comments: ''
})
const subsystemReview = ref({
  status: 'DRAFT',
  findings: [],
  finalVerdict: ''
})

const tabCounts = computed(() => {
  return {
    tile: reviews.filter(r => r.type === 'tile').length,
    group: reviews.filter(r => r.type === 'group').length,
    subsystem: reviews.filter(r => r.type === 'subsystem').length
  }
})

const getStatusColor = (status) => {
  if (status === 'APPROVED') return '#4caf50'
  if (status === 'REJECTED') return '#e74c3c'
  if (status === 'SUBMITTED') return '#3498db'
  return '#999'
}

const getStatusLabel = (status) => {
  if (status === 'APPROVED') return '已通过'
  if (status === 'REJECTED') return '已拒绝'
  if (status === 'SUBMITTED') return '已提交'
  return '草稿'
}

onMounted(async () => {
  await loadReviews()
})

async function loadReviews() {
  loading.value = true
  try {
    const params = {}
    if (filters.projectId) params.project_id = filters.projectId
    const data = await qorApi.getRunNotes(params)
    reviews.value = data || []
  } catch (e) {
    console.error('Review load failed:', e)
  } finally {
    loading.value = false
  }
}

async function saveTileReview() {
  try {
    tileReview.value.status = 'SUBMITTED'
    alert('评审已提交')
  } catch (e) {
    console.error('Failed:', e)
  }
}

async function saveGroupReview() {
  try {
    groupReview.value.status = 'SUBMITTED'
    alert('评审已提交')
  } catch (e) {
    console.error('Failed:', e)
  }
}

async function approve() {
  if (activeTab.value === 'tile') tileReview.value.status = 'APPROVED'
  if (activeTab.value === 'group') groupReview.value.status = 'APPROVED'
  if (activeTab.value === 'subsystem') subsystemReview.value.status = 'APPROVED'
  alert('评审已通过')
}

async function reject() {
  if (activeTab.value === 'tile') tileReview.value.status = 'REJECTED'
  if (activeTab.value === 'group') groupReview.value.status = 'REJECTED'
  if (activeTab.value === 'subsystem') subsystemReview.value.status = 'REJECTED'
  alert('评审已拒绝')
}
</script>

<template>
  <div class="review-page">
    <h1>评审中心</h1>
    <FilterBar />

    <div class="tabs">
      <button
        :class="['tab-btn', { active: activeTab === 'tile' }]"
        @click="activeTab = 'tile'"
      >
        Tile 评审
        <span v-if="tabCounts.tile" class="tab-count">{{ tabCounts.tile }}</span>
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'group' }]"
        @click="activeTab = 'group'"
      >
        Group 评审
        <span v-if="tabCounts.group" class="tab-count">{{ tabCounts.group }}</span>
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'subsystem' }]"
        @click="activeTab = 'subsystem'"
      >
        Subsystem 评审
        <span v-if="tabCounts.subsystem" class="tab-count">{{ tabCounts.subsystem }}</span>
      </button>
    </div>

    <LoadingSpinner v-if="loading" text="加载评审数据..." />

    <div v-else class="review-container">
      <!-- Tile Review Tab -->
      <div v-if="activeTab === 'tile'" class="card">
        <div class="card-header">
          <span>Tile 评审</span>
          <span class="tag" :style="{ background: getStatusColor(tileReview.status) }">
            {{ getStatusLabel(tileReview.status) }}
          </span>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label>评审意见</label>
            <textarea
              v-model="tileReview.comment"
              placeholder="请输入评审意见..."
              rows="6"
            ></textarea>
          </div>
          <div class="form-group checkbox-group">
            <label>
              <input type="checkbox" v-model="tileReview.qaSignoff" />
              QA 已签核
            </label>
          </div>
          <div class="actions-row">
            <button class="btn" @click="saveTileReview" :disabled="tileReview.status !== 'DRAFT'">
              保存草稿
            </button>
            <button class="btn btn-primary" @click="saveTileReview" :disabled="tileReview.status !== 'DRAFT'">
              提交评审
            </button>
            <div class="approval-actions">
              <button class="btn btn-success" @click="approve" :disabled="tileReview.status !== 'SUBMITTED'">
                通过
              </button>
              <button class="btn btn-danger" @click="reject" :disabled="tileReview.status !== 'SUBMITTED'">
                拒绝
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Group Review Tab -->
      <div v-else-if="activeTab === 'group'" class="card">
        <div class="card-header">
          <span>Group 评审</span>
          <span class="tag" :style="{ background: getStatusColor(groupReview.status) }">
            {{ getStatusLabel(groupReview.status) }}
          </span>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label>Pass/No Pass</label>
            <select v-model="groupReview.passNoPass">
              <option value="">请选择</option>
              <option value="PASS">Pass</option>
              <option value="NO_PASS">No Pass</option>
            </select>
          </div>
          <div class="form-group">
            <label>评审评论</label>
            <textarea
              v-model="groupReview.comments"
              placeholder="请输入评审评论..."
              rows="6"
            ></textarea>
          </div>
          <div class="actions-row">
            <button class="btn" @click="saveGroupReview" :disabled="groupReview.status !== 'DRAFT'">
              保存草稿
            </button>
            <button class="btn btn-primary" @click="saveGroupReview" :disabled="groupReview.status !== 'DRAFT'">
              提交评审
            </button>
            <div class="approval-actions">
              <button class="btn btn-success" @click="approve" :disabled="groupReview.status !== 'SUBMITTED'">
                通过
              </button>
              <button class="btn btn-danger" @click="reject" :disabled="groupReview.status !== 'SUBMITTED'">
                拒绝
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Subsystem Review Tab -->
      <div v-else-if="activeTab === 'subsystem'" class="card">
        <div class="card-header">
          <span>Subsystem 评审</span>
          <span class="tag" :style="{ background: getStatusColor(subsystemReview.status) }">
            {{ getStatusLabel(subsystemReview.status) }}
          </span>
        </div>
        <div class="card-body">
          <div class="form-group">
            <label>最终结论</label>
            <select v-model="subsystemReview.finalVerdict">
              <option value="">请选择</option>
              <option value="ACCEPT">Accept</option>
              <option value="REJECT">Reject</option>
              <option value="CONDITIONAL">Conditional</option>
            </select>
          </div>
          <div class="actions-row">
            <button class="btn" :disabled="subsystemReview.status !== 'DRAFT'">
              保存草稿
            </button>
            <button class="btn btn-primary" :disabled="subsystemReview.status !== 'DRAFT'">
              提交评审
            </button>
            <div class="approval-actions">
              <button class="btn btn-success" @click="approve" :disabled="subsystemReview.status !== 'SUBMITTED'">
                通过
              </button>
              <button class="btn btn-danger" @click="reject" :disabled="subsystemReview.status !== 'SUBMITTED'">
                拒绝
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-page h1 {
  margin-bottom: 20px;
  font-size: 24px;
}
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  color: var(--color-text);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.tab-btn:hover {
  background: var(--color-surface-hover);
}
.tab-btn.active {
  background: rgba(52, 152, 219, 0.15);
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.tab-count {
  background: var(--color-primary);
  color: white;
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 10px;
}
.review-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.form-group {
  margin-bottom: 16px;
}
.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 6px;
  color: var(--color-text);
}
.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 14px;
}
.form-group textarea:focus,
.form-group select:focus,
.form-group input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.1);
}
.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: normal;
  cursor: pointer;
}
.checkbox-group input {
  width: auto;
}
.actions-row {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid var(--color-border);
}
.actions-row .btn:first-of-type {
  margin-right: auto;
}
.approval-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}
.btn-primary {
  background: var(--color-primary);
  color: white;
  border-color: var(--color-primary);
}
.btn-primary:hover {
  background: #1a7a9d;
}
.btn-success {
  background: #4caf50;
  color: white;
  border-color: #4caf50;
}
.btn-success:hover {
  background: #43a047;
}
.btn-danger {
  background: #e74c3c;
  color: white;
  border-color: #e74c3c;
}
.btn-danger:hover {
  background: #d62c1a;
}
</style>
