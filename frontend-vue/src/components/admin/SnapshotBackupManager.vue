<script setup>
import { onMounted, ref, watch } from 'vue'
import { adminApi } from '@/api/admin'
import { reviewApi } from '@/api/review'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

const props = defineProps({
  projectId: { type: [String, Number], default: '' }
})
const activeTab = ref('snapshots')
const snapshots = ref([])
const backups = ref([])
const loading = ref(false)
const error = ref('')
const verifySummary = ref(null)
const copiedId = ref(null)

onMounted(loadData)
watch(
  () => props.projectId,
  () => activeTab.value === 'snapshots' && loadData()
)

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    if (activeTab.value === 'snapshots') {
      snapshots.value = props.projectId
        ? await reviewApi.listSnapshots({ project_id: props.projectId })
        : []
    } else {
      backups.value = await adminApi.listBackups()
    }
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function selectTab(tab) {
  activeTab.value = tab
  await loadData()
}

async function createSnapshot() {
  if (!props.projectId) {
    error.value = '请先在记录管理中选择一个项目'
    return
  }
  try {
    await reviewApi.createSnapshot({ project_id: Number(props.projectId) })
    await loadData()
  } catch (e) {
    error.value = e.message || '创建快照失败'
  }
}

async function createBackup() {
  try {
    await adminApi.createBackup()
    await loadData()
  } catch (e) {
    error.value = e.message || '创建备份失败'
  }
}

async function verifyBackups() {
  try {
    verifySummary.value = await adminApi.verifyBackups()
  } catch (e) {
    error.value = e.message || '备份校验失败'
  }
}

function restoreCommand(backup) {
  return (
    backup.restore_apply_command ||
    `python manage.py restore_backup "${backup.file_path}" --verify --apply`
  )
}

function verificationLabel(backup) {
  const verified = verifySummary.value?.details?.find(item => item.id === backup.id)
  if (verified?.status) {
    return (
      {
        ok: '校验通过',
        corrupted: '校验失败',
        missing: '文件缺失',
        error: '校验异常'
      }[verified.status] || verified.status
    )
  }
  return (
    {
      ok: '校验通过',
      corrupted: '校验失败',
      missing: '文件缺失',
      present: '文件存在（未跑全量校验）',
      error: '校验异常',
      unknown: '未校验'
    }[backup.verification_status] ||
    backup.verification_status ||
    '未校验'
  )
}

function schemaLabel(backup) {
  const schema = backup.manifest?.schema
  if (!schema) return backup.manifest?.legacy ? 'legacy（无 manifest）' : '—'
  const apps = schema.migration_apps || Object.keys(schema.django_migrations || {})
  const core = schema.django_migrations?.core
  return core
    ? `core=${core}${apps.length > 1 ? ` · ${apps.length} apps` : ''}`
    : `apps=${apps.join(',') || '—'}`
}

async function copyRestoreCommand(backup) {
  await navigator.clipboard.writeText(restoreCommand(backup))
  copiedId.value = backup.id
  window.setTimeout(() => {
    if (copiedId.value === backup.id) copiedId.value = null
  }, 1400)
}
</script>

<template>
  <section class="snapshot-backup-section card">
    <div class="card-header">
      <span>Snapshot & Backup</span>
      <div class="actions">
        <button v-if="activeTab === 'snapshots'" class="btn btn-sm" @click="createSnapshot">
          冻结本周快照
        </button>
        <template v-else>
          <button class="btn btn-sm" @click="verifyBackups">校验全部</button>
          <button class="btn btn-sm" @click="createBackup">创建完整备份</button>
        </template>
      </div>
    </div>
    <div class="tabs">
      <button :class="{ active: activeTab === 'snapshots' }" @click="selectTab('snapshots')">
        周快照
      </button>
      <button :class="{ active: activeTab === 'backups' }" @click="selectTab('backups')">
        数据库备份
      </button>
    </div>
    <div class="card-body">
      <p v-if="error" class="error-text">{{ error }}</p>
      <LoadingSpinner v-if="loading" text="加载中..." />
      <template v-else-if="activeTab === 'snapshots'">
        <p v-if="!projectId" class="muted">选择具体项目后可查看和冻结本周评审数据。</p>
        <div v-for="snapshot in snapshots" :key="snapshot.id" class="list-row">
          <div>
            <strong>{{ snapshot.name }}</strong>
            <div class="muted">{{ snapshot.created_at }} · {{ snapshot.record_count }} records</div>
          </div>
          <span>{{ snapshot.verified ? '校验通过' : '校验失败' }}</span>
        </div>
      </template>
      <template v-else>
        <p v-if="verifySummary" class="muted">
          校验：{{ verifySummary.ok }}/{{ verifySummary.total }} 正常，
          {{ verifySummary.corrupted }} 损坏，{{ verifySummary.missing }} 缺失
        </p>
        <div v-for="backup in backups" :key="backup.id" class="list-row backup-row">
          <div>
            <strong>{{ backup.created_at }}</strong>
            <div class="muted">
              {{ backup.file_size_mb }} MB · {{ backup.record_count }} records · {{ backup.status }}
            </div>
            <div class="muted">校验状态：{{ verificationLabel(backup) }}</div>
            <div class="muted">schema / migration：{{ schemaLabel(backup) }}</div>
            <code class="restore-cmd" :title="restoreCommand(backup)">{{
              restoreCommand(backup)
            }}</code>
          </div>
          <button
            class="btn btn-sm"
            :title="restoreCommand(backup)"
            @click="copyRestoreCommand(backup)"
          >
            {{ copiedId === backup.id ? '已复制' : '复制安全恢复命令' }}
          </button>
        </div>
        <p class="muted">
          恢复会替换数据库文件，必须通过管理命令在维护窗口执行；Web
          请求不会在线覆盖正在使用的数据库。 Mongo/hybrid 模式会拒绝自动 --apply。
        </p>
      </template>
    </div>
  </section>
</template>

<style scoped>
.snapshot-backup-section {
  margin-top: 16px;
}
.actions,
.tabs,
.list-row {
  display: flex;
  align-items: center;
}
.actions {
  gap: 8px;
}
.tabs {
  border-bottom: 1px solid var(--color-border);
}
.tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  padding: 10px 16px;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.tabs button.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}
.list-row {
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border);
}
.backup-row {
  align-items: flex-start;
}
.restore-cmd {
  display: block;
  margin-top: 6px;
  max-width: 52rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--color-text-secondary);
}
.muted {
  color: var(--color-text-secondary);
  font-size: 12px;
}
</style>
