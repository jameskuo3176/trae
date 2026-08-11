<script setup>
import { ref, onMounted } from 'vue'
import { violationsApi } from '@/api/violations'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const sourceFiles = ref([])
const loading = ref(false)
const error = ref('')

onMounted(async () => {
  await loadSourceFiles()
})

async function loadSourceFiles() {
  loading.value = true
  try {
    const data = await violationsApi.getSourceFiles({})
    sourceFiles.value = data || []
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="source-page">
    <h1>源文件检查</h1>
    <LoadingSpinner v-if="loading" text="加载源文件信息..." />
    <div v-else-if="error" class="error-state">{{ error }}</div>
    <div v-else-if="sourceFiles.length === 0" class="empty-state">暂无源文件数据</div>
    <div v-else class="card">
      <div class="card-header">源文件列表</div>
      <div class="card-body">
        <table class="table">
          <thead>
            <tr>
              <th>文件路径</th>
              <th>违例数</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(f, idx) in sourceFiles" :key="idx">
              <td>{{ f.path || f.file || f.name }}</td>
              <td>{{ f.violation_count || f.count || 0 }}</td>
              <td>
                <span class="tag" :class="f.status === 'fixed' ? 'tag-success' : 'tag-warning'">
                  {{ f.status || '待处理' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.source-page h1 {
  margin-bottom: 20px;
  font-size: 24px;
}
.tag-success {
  background: rgba(56, 142, 60, 0.2);
  color: #66bb6a;
  border-color: #388e3c;
}
.tag-warning {
  background: rgba(255, 152, 0, 0.2);
  color: #ffb74d;
  border-color: #f57c00;
}
</style>
