<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { qorApi } from '@/api/qor'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const route = useRoute()
const record = ref(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    record.value = await qorApi.getRecordDetail(route.params.id)
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="detail-page">
    <router-link to="/dashboard" class="back-link">← 返回 Dashboard</router-link>
    <LoadingSpinner v-if="loading" text="加载记录详情..." />
    <div v-else-if="error" class="error-state">{{ error }}</div>
    <div v-else-if="record" class="card">
      <div class="card-header">记录详情 #{{ record.id }}</div>
      <div class="card-body">
        <div class="detail-grid">
          <div class="detail-item">
            <span class="label">项目</span>
            <span>{{ record.project_name }}</span>
          </div>
          <div class="detail-item">
            <span class="label">模块</span>
            <span>{{ record.module_name }}</span>
          </div>
          <div class="detail-item">
            <span class="label">版本</span>
            <span>{{ record.version }}</span>
          </div>
          <div class="detail-item">
            <span class="label">目录</span>
            <span>{{ record.dir }}</span>
          </div>
          <div class="detail-item">
            <span class="label">操作者</span>
            <span>{{ record.owner }}</span>
          </div>
          <div class="detail-item">
            <span class="label">日期</span>
            <span>{{ record.date }}</span>
          </div>
        </div>
        <div v-if="record.metrics" class="metrics-section">
          <h3>指标数据</h3>
          <table class="table">
            <thead>
              <tr>
                <th>指标</th>
                <th>值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(val, key) in record.metrics" :key="key">
                <td>{{ key }}</td>
                <td>{{ val }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail-page {
  max-width: 900px;
  margin: 0 auto;
}
.back-link {
  display: inline-block;
  margin-bottom: 20px;
  color: var(--color-primary);
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.detail-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.detail-item .label {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.metrics-section h3 {
  margin-bottom: 12px;
  font-size: 16px;
}
</style>
