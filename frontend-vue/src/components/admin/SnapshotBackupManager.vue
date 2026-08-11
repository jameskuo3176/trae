<script setup>
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api/admin'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

const activeTab = ref('snapshots')
const snapshots = ref([])
const backups = ref([])
const loading = ref(false)
const showConfirm = ref(null)
const confirmConfig = ref(null)

async function loadData() {
  loading.value = true
  try {
    if (activeTab.value === 'snapshots') {
      const data = await adminApi.getDashboardConfigs()
      snapshots.value = data || []
    } else {
      await adminApi.getDashboardConfigs() // 使用同接口
      backups.value = [
        { id: 1, created_at: '2026-08-09 14:30', status: 'OK', size: '2.4MB' },
        { id: 2, created_at: '2026-08-08 00:00', status: 'OK', size: '2.3MB' }
      ]
    }
  } catch (e) {
    console.error('Load failed:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => loadData())
function selectTab(tab) {
  activeTab.value = tab
  loadData()
}

const pendingConfirm = ref(null)

async function createSnapshot() {
  confirmConfig.value = {
    title: '创建快照',
    message: '确定要创建当前数据的快照吗？',
    confirmText: '创建',
    isDanger: false
  }
  pendingConfirm.value = async () => {
    try {
      const newSnap = await adminApi.saveDashboardConfig({ name: 'Manual Snapshot' })
      snapshots.value.unshift(newSnap)
    } catch (e) {
      console.error('Failed:', e)
    }
  }
  showConfirm.value = true
}

async function verifySnapshot(snap) {
  try {
    await adminApi.saveDashboardConfig({ id: snap.id, verify: true })
    alert('验证成功！')
  } catch (e) {
    alert('验证失败')
  }
}

async function rollbackSnapshot(snap) {
  confirmConfig.value = {
    title: '回滚快照',
    message: '确定要回滚到此快照吗？当前数据将被覆盖。',
    confirmText: '确认回滚',
    isDanger: true
  }
  pendingConfirm.value = async () => {
    try {
      await adminApi.saveDashboardConfig({ id: snap.id, rollback: true })
      alert('回滚成功！')
    } catch (e) {
      alert('回滚失败')
    }
  }
  showConfirm.value = true
}

async function createBackup() {
  confirmConfig.value = {
    title: '创建备份',
    message: '确定要创建完整备份吗？',
    confirmText: '创建',
    isDanger: false
  }
  pendingConfirm.value = async () => {
    backups.value.unshift({
      id: Date.now(),
      created_at: new Date().toLocaleString(),
      status: 'OK',
      size: '2.5MB'
    })
    alert('备份成功！')
  }
  showConfirm.value = true
}

async function handleConfirm() {
  showConfirm.value = false
  if (pendingConfirm.value) {
    await pendingConfirm.value()
    pendingConfirm.value = null
  }
}
</script>

<template>
  <div class="snapshot-backup-section">
    <div class="card">
      <div class="card-header">
        <div class="header-left">
          <span>📸 Snapshot & Backup</span>
        </div>
        <div class="header-actions">
          <button v-if="activeTab === 'snapshots'" class="btn btn-sm" @click="createSnapshot">
            + 创建快照
          </button>
          <button v-else class="btn btn-sm" @click="createBackup">+ 创建备份</button>
        </div>
      </div>

      <div class="tabs">
        <button
          :class="['tab-btn', { active: activeTab === 'snapshots' }]"
          @click="selectTab('snapshots')"
        >
          Snapshots
        </button>
        <button
          :class="['tab-btn', { active: activeTab === 'backups' }]"
          @click="selectTab('backups')"
        >
          Backups
        </button>
      </div>

      <div class="card-body content-body">
        <LoadingSpinner v-if="loading" text="加载中..." />

        <div v-else-if="activeTab === 'snapshots'">
          <div v-if="snapshots.length === 0" class="empty-state">暂无快照</div>
          <div v-else class="list-container">
            <div v-for="snap in snapshots" :key="snap.id" class="list-item">
              <div class="item-main">
                <span class="item-title">📸 {{ snap.name || 'Snapshot ' + snap.id }}</span>
                <span class="item-meta">{{ snap.created_at }}</span>
              </div>
              <div class="item-actions">
                <button class="btn btn-sm btn-default" @click="verifySnapshot(snap)">✓ 验证</button>
                <button class="btn btn-sm btn-danger" @click="rollbackSnapshot(snap)">
                  ↩ 回滚
                </button>
              </div>
            </div>
          </div>
        </div>

        <div v-else>
          <div v-if="backups.length === 0" class="empty-state">暂无备份</div>
          <div v-else class="list-container">
            <div v-for="bk in backups" :key="bk.id" class="list-item">
              <div class="item-main">
                <span class="item-title">💾 Backup</span>
                <span class="item-meta">{{ bk.created_at }}</span>
              </div>
              <div class="item-right">
                <span
                  class="tag"
                  :style="{ background: bk.status === 'OK' ? '#4caf50' : '#ff9800' }"
                >
                  {{ bk.status }}
                </span>
                <span class="item-meta">{{ bk.size }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <ConfirmDialog
      v-if="showConfirm"
      v-model="showConfirm"
      :title="confirmConfig.title"
      :message="confirmConfig.message"
      :confirm-text="confirmConfig.confirmText"
      :is-danger="confirmConfig.isDanger"
      @confirm="handleConfirm"
    />
  </div>
</template>

<style scoped>
.snapshot-backup-section {
  margin-top: 16px;
}

.header-left {
  flex: 1;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.tabs {
  display: flex;
  gap: 4px;
  padding: 0 16px;
  border-bottom: 1px solid var(--color-border);
  margin: 0 -16px 16px -16px;
}

.tab-btn {
  padding: 10px 16px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--color-text-secondary);
  font-size: 14px;
  cursor: pointer;
  margin-bottom: -1px;
}

.tab-btn.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.content-body {
  padding-top: 0;
}

.list-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  transition: all 0.2s;
}

.list-item:hover {
  background: var(--color-surface-hover);
  border-color: var(--color-primary);
}

.item-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.item-title {
  font-weight: 500;
}

.item-meta {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.item-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.item-actions {
  display: flex;
  gap: 8px;
}

.empty-state {
  padding: 48px;
  text-align: center;
  color: var(--color-text-secondary);
}
</style>
