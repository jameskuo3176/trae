<script setup>
import { computed, ref } from 'vue'
import { useDashboardStore } from '@/stores/dashboard'
import { dashboardApi } from '@/api/dashboard'
import RiskRatingControl from '@/components/common/RiskRatingControl.vue'

const dashboard = useDashboardStore()
const busyKey = ref('')
const error = ref('')
const rows = computed(() => dashboard.records.filter(record => record.risk))

async function updateRisk(record, rating) {
  const key = `${record.project_id}:${record.id}`
  busyKey.value = key
  error.value = ''
  try {
    record.risk = rating
      ? await dashboardApi.setRisk(record.project_id, record.id, rating)
      : await dashboardApi.clearRisk(record.project_id, record.id)
  } catch (exception) {
    error.value =
      exception.response?.data?.error?.message || exception.message || '风险等级保存失败'
  } finally {
    busyKey.value = ''
  }
}
</script>

<template>
  <section class="risk-overview card">
    <header class="card-header">
      <span>版本风险评估</span>
      <small>排除 I2C / C2O / I2O；人工判断会约束后续改善或恶化版本</small>
    </header>
    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
    <div class="risk-grid">
      <article v-for="record in rows" :key="`${record.project_id}:${record.id}`">
        <div>
          <strong>{{ record.module_name || '-' }} · {{ record.tag || record.version }}</strong>
          <small>
            WNS {{ record.risk.summary?.worst_wns ?? '-' }} · TNS
            {{ record.risk.summary?.worst_tns ?? '-' }}
          </small>
        </div>
        <RiskRatingControl
          :risk="record.risk"
          :disabled="!record.risk.can_edit"
          :busy="busyKey === `${record.project_id}:${record.id}`"
          @change="updateRisk(record, $event)"
        />
      </article>
    </div>
  </section>
</template>

<style scoped>
.card-header small {
  color: var(--color-text-secondary);
  font-size: 10px;
}
.risk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
}
.risk-grid article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
}
.risk-grid article > div {
  min-width: 0;
}
.risk-grid strong,
.risk-grid small {
  display: block;
}
.risk-grid strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.risk-grid article small {
  margin-top: 3px;
  color: var(--color-text-secondary);
  font-size: 10px;
}
</style>
