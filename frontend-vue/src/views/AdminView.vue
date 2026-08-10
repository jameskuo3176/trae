<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { adminApi } from '@/api/admin'
import { projectsApi } from '@/api/projects'
import { qorApi } from '@/api/qor'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import DataUploadModal from '@/components/admin/DataUploadModal.vue'
import SnapshotBackupManager from '@/components/admin/SnapshotBackupManager.vue'
import { useTableSort } from '@/composables/useTableSort'

const activeTab = ref('records')
const projects = ref([])
const modules = ref([])
const users = ref([])
const records = ref([])
const loading = ref(false)
const error = ref('')

// 请求竞态控制：取消上一次未完成的请求
let abortController = null

// 项目管理
const newProject = ref({ name: '', description: '' })
const newModule = ref({ name: '', project_id: '', module_type: '' })
const newUser = ref({ username: '', password: '', role: 'owner', display_name: '' })

// 记录管理筛选
const recordFilter = ref({ project_id: '', module_id: '', version: '', owner_id: '' })
const selectedRecordIds = ref(new Set())
const recordOwners = ref([])

// 排序状态
const recordsSort = useTableSort('id', 'desc')
const projectsSort = useTableSort('id', 'desc')
const modulesSort = useTableSort('id', 'desc')
const usersSort = useTableSort('username', 'asc')

// Modal
const showUploadModal = ref(false)

const roleLabels = {
  admin: '管理员',
  owner: 'Owner',
  release: 'Release',
  viewer: '观察者'
}

// 排序后的计算数据（带调试日志）
const sortedRecords = computed(() => {
  const result = recordsSort.computeSorted(records.value)
  console.log('[Admin] sortedRecords computed:', result?.length, 'rows, first 3:', (result || []).slice(0, 3).map(r => ({ id: r.id, proj: r.project_name || r.project_id, mod: r.module_name || r.module_id })))
  return result
})
const sortedProjects = computed(() => projectsSort.computeSorted(projects.value))
const sortedModules = computed(() => modulesSort.computeSorted(modules.value))
const sortedUsers = computed(() => usersSort.computeSorted(users.value))

// 核心修复：记录管理筛选用的模块列表，独立计算，不受 Tab 切换影响
const filterModules = computed(() => {
  if (!recordFilter.value.project_id) {
    // 未选择项目 → 显示全部模块
    const all = []
    for (const p of projects.value) {
      if (p.modules && Array.isArray(p.modules)) {
        for (const m of p.modules) {
          all.push({ ...m, project_id: p.id, project_name: p.name })
        }
      }
    }
    return all
  }
  // 已选择项目 → 只显示该项目的模块
  const pid = String(recordFilter.value.project_id)
  const proj = projects.value.find(p => String(p.id) === pid)
  if (proj && proj.modules && Array.isArray(proj.modules)) {
    return proj.modules.map(m => ({ ...m, project_id: proj.id, project_name: proj.name }))
  }
  return []
})

onMounted(async () => {
  await loadProjects()
  await loadTabData()
})

watch(activeTab, () => {
  if (activeTab.value === 'records') recordsSort.resetSort()
  if (activeTab.value === 'projects') projectsSort.resetSort()
  if (activeTab.value === 'modules') modulesSort.resetSort()
  if (activeTab.value === 'users') usersSort.resetSort()
  loadTabData()
})

// 项目变更 → 清除模块选择 + 自动加载记录
watch(() => recordFilter.value.project_id, (newVal) => {
  // 清除可能无效的模块选择
  if (recordFilter.value.module_id) {
    const validModuleIds = filterModules.value.map(m => String(m.id))
    if (!validModuleIds.includes(String(recordFilter.value.module_id))) {
      recordFilter.value.module_id = ''
    }
  }
  // 自动加载记录（与原始 Django 模板行为一致）
  loadRecords()
})

// 模块变更 → 自动加载记录
watch(() => recordFilter.value.module_id, (newVal, oldVal) => {
  console.log('[Admin] module_id watcher:', oldVal, '→', newVal, '| project_id:', recordFilter.value.project_id)
  loadRecords()
})

async function loadProjects() {
    try {
        const data = await projectsApi.list()
        projects.value = data || []
    } catch { /* ignore */ }
}

async function loadTabData() {
    loading.value = true
    error.value = ''
    try {
        if (activeTab.value === 'projects') {
            const data = await projectsApi.list()
            projects.value = data || []
        } else if (activeTab.value === 'modules') {
            const allProjects = await projectsApi.list()
            projects.value = allProjects || []
            const allModules = []
            for (const p of (allProjects || [])) {
                if (p.modules) {
                    p.modules.forEach(m => {
                        allModules.push({ ...m, project_name: p.name, project_id: p.id })
                    })
                }
            }
            modules.value = allModules
        } else if (activeTab.value === 'users') {
            const data = await adminApi.listUsers()
            users.value = data || []
        } else if (activeTab.value === 'records') {
            await loadRecords()
        }
    } catch (e) {
        error.value = e.response?.data?.error || e.message || '加载失败'
    } finally {
        loading.value = false
    }
}

async function loadRecords() {
    console.log('[Admin] loadRecords START, filter:', JSON.stringify(recordFilter.value))
    // 取消上一次未完成的请求，防止竞态条件
    if (abortController) {
        abortController.abort()
        console.log('[Admin] loadRecords: aborted previous request')
    }
    abortController = new AbortController()
    const signal = abortController.signal

    try {
        const allProjects = await projectsApi.list()
        // 请求被取消则不再继续
        if (signal.aborted) return
        projects.value = allProjects || []
        
        const projectIdToName = {}
        for (const p of allProjects || []) {
            projectIdToName[p.id] = p.name
        }

        let validProjectId = recordFilter.value.project_id
        if (validProjectId) {
            const projectExists = allProjects?.some(p => String(p.id) === String(validProjectId))
            if (!projectExists) {
                validProjectId = ''
                recordFilter.value.project_id = ''
            }
        }
        
        let validModuleId = recordFilter.value.module_id
        if (validModuleId) {
            const moduleExists = filterModules.value.some(m => String(m.id) === String(validModuleId))
            if (!moduleExists) {
                validModuleId = ''
                recordFilter.value.module_id = ''
            }
        }

        const params = {}
        if (validProjectId) {
            params.project_ids = validProjectId
        } else {
            params.project_ids = (allProjects || []).map(p => p.id).join(',')
        }
        if (validModuleId) params.module_ids = validModuleId
        if (recordFilter.value.version) params.versions = recordFilter.value.version
        if (recordFilter.value.owner_id) params.owner_id = recordFilter.value.owner_id
        
        console.log('[Admin] loadRecords params:', JSON.stringify(params))
        
        const data = await qorApi.getQorData(params, signal)
        // 请求被取消则不再继续
        if (signal.aborted) return
        
        console.log('[Admin] loadRecords received:', data?.length, 'records')
        
        records.value = (data || []).map(r => ({
            ...r,
            project_name: projectIdToName[r.project_id] || r.project_name || '-'
        }))
        
        console.log('[Admin] records.value set, sample:', records.value.slice(0, 3).map(r => ({ id: r.id, pid: r.project_id, pn: r.project_name, mid: r.module_id, mn: r.module_name })))
        
    } catch (e) {
        // 忽略取消导致的错误
        if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED' || signal.aborted) return
        console.error('Load records error:', e)
        error.value = '加载记录失败: ' + (e.message || '未知错误')
    }
}

// 记录管理：切换发布状态
async function toggleRelease(recordId) {
  try {
    const result = await adminApi.toggleRelease(recordId)
    const idx = records.value.findIndex(r => r.id === recordId)
    if (idx >= 0) {
      records.value[idx] = { ...records.value[idx], ...result }
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '发布操作失败'
  }
}

// 记录管理：编辑release目录
async function editReleaseDir(recordId, currentDir) {
  const newDir = prompt('请输入release_dir（留空将使用full_dir）:\n当前值: ' + (currentDir || '(未设置)'), currentDir || '')
  if (newDir === null) return
  try {
    const result = await adminApi.updateReleaseDir(recordId, newDir)
    const idx = records.value.findIndex(r => r.id === recordId)
    if (idx >= 0) {
      records.value[idx] = { ...records.value[idx], ...result }
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '更新失败'
  }
}

// 记录管理：全选/清空
function selectAllRecords() {
  records.value.forEach(r => selectedRecordIds.value.add(r.id))
}
function clearRecordSelection() {
  selectedRecordIds.value.clear()
}

// 记录管理：批量发布
async function batchRelease() {
  const ids = Array.from(selectedRecordIds.value)
  if (ids.length === 0) {
    alert('请先勾选要发布的记录')
    return
  }
  if (!confirm('确定要发布选中的' + ids.length + '条记录？')) return
  try {
    const result = await adminApi.batchRelease({ record_ids: ids, released: true })
    alert('发布完成: 成功' + (result.updated || 0) + '条')
    selectedRecordIds.value.clear()
    await loadRecords()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '批量发布失败'
  }
}

// 记录管理：批量撤回
async function batchUnrelease() {
  const ids = Array.from(selectedRecordIds.value)
  if (ids.length === 0) {
    alert('请先勾选要撤回的记录')
    return
  }
  if (!confirm('确定要撤回选中的' + ids.length + '条记录？')) return
  try {
    const result = await adminApi.batchRelease({ record_ids: ids, released: false })
    alert('撤回完成: 成功' + (result.updated || 0) + '条')
    selectedRecordIds.value.clear()
    await loadRecords()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '批量撤回失败'
  }
}

// 记录管理：编辑版本描述
async function editVersionDescription(recordId, currentDesc) {
  const newDesc = prompt('请输入版本描述:\n当前值: ' + (currentDesc || '(无)'), currentDesc || '')
  if (newDesc === null) return
  try {
    await adminApi.updateVersionDescription(recordId, newDesc)
    const idx = records.value.findIndex(r => r.id === recordId)
    if (idx >= 0) {
      records.value[idx] = { ...records.value[idx], version_description: newDesc }
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '更新失败'
  }
}

// 切换记录选中
function toggleRecordSelect(id) {
  const s = new Set(selectedRecordIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedRecordIds.value = s
}

function toggleAllRecords() {
  if (selectedRecordIds.value.size === records.value.length) {
    selectedRecordIds.value.clear()
  } else {
    records.value.forEach(r => selectedRecordIds.value.add(r.id))
  }
}

const selectedCount = computed(() => selectedRecordIds.value.size)

function getProjectName(r) {
  return r.project_name || '-'
}

function getOwnerDisplay(r) {
  return r.owner_username || r.owner || (r.owner_id ? '#' + r.owner_id : '-')
}

// 项目管理CRUD
async function handleCreateProject() {
  try {
    await adminApi.createProject(newProject.value)
    newProject.value = { name: '', description: '' }
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
}

async function handleDeleteProject(id) {
  if (!confirm('确定要删除这个项目吗？')) return
  try {
    await adminApi.deleteProject(id)
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
}

async function handleCreateModule() {
  try {
    await adminApi.createModule(newModule.value)
    newModule.value = { name: '', project_id: '', module_type: '' }
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
}

async function handleDeleteModule(id) {
  if (!confirm('确定要删除这个模块吗？')) return
  try {
    await adminApi.deleteModule(id)
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
}

async function handleCreateUser() {
  try {
    await adminApi.createUser(newUser.value)
    newUser.value = { username: '', password: '', role: 'owner', display_name: '' }
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
}

async function handleResetPassword(userId) {
  try {
    await adminApi.resetUserPassword(userId)
    alert('密码已重置')
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
}
</script>

<template>
  <div class="admin-page">
    <h1>管理后台</h1>
    <div class="tabs">
      <button
        :class="['tab-btn', { active: activeTab === 'records' }]"
        @click="activeTab = 'records'"
      >记录管理</button>
      <button
        :class="['tab-btn', { active: activeTab === 'projects' }]"
        @click="activeTab = 'projects'"
      >项目管理</button>
      <button
        :class="['tab-btn', { active: activeTab === 'modules' }]"
        @click="activeTab = 'modules'"
      >模块管理</button>
      <button
        :class="['tab-btn', { active: activeTab === 'users' }]"
        @click="activeTab = 'users'"
      >用户管理</button>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>
    <LoadingSpinner v-if="loading" text="加载中..." />

    <!-- 记录管理 -->
    <template v-if="activeTab === 'records' && !loading">
      <div class="card" style="margin-bottom: 12px;">
        <div class="card-header">
          <span>📋 记录管理</span>
          <div class="header-actions">
            <button class="btn" @click="showUploadModal = true">
              📤 上传数据
            </button>
          </div>
        </div>
        <div class="card-body" style="padding: 10px 16px;">
          <div class="record-filter-bar">
            <select v-model="recordFilter.project_id" style="min-width: 140px;">
              <option value="">全部项目</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <select v-model="recordFilter.module_id" style="min-width: 140px;">
              <option value="">全部模块</option>
              <option v-for="m in filterModules" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
            <input
              v-model="recordFilter.version"
              placeholder="版本号"
              style="width: 120px;"
              @keyup.enter="loadRecords"
            />
            <button class="btn btn-sm" @click="loadRecords">查询</button>
            <span style="margin-left: auto; font-size: 12px; color: var(--color-text-secondary);">
              共 {{ records.length }} 条记录
            </span>
          </div>
        </div>
      </div>

      <!-- 批量操作 -->
      <div class="card" style="margin-bottom: 12px;">
        <div class="card-body" style="padding: 8px 16px; display: flex; gap: 8px; align-items: center;">
          <label style="display: flex; align-items: center; gap: 4px; font-size: 12px; cursor: pointer;">
            <input type="checkbox" @change="toggleAllRecords" :checked="selectedCount === records.length && records.length > 0" />
            全选
          </label>
          <span style="font-size: 12px; color: var(--color-text-secondary);">已选 {{ selectedCount }} 条</span>
          <button class="btn btn-sm btn-success" @click="batchRelease" :disabled="selectedCount === 0">批量发布</button>
          <button class="btn btn-sm btn-default" @click="batchUnrelease" :disabled="selectedCount === 0">批量撤回</button>
          <button class="btn btn-sm btn-default" @click="clearRecordSelection" :disabled="selectedCount === 0">清空选择</button>
        </div>
      </div>

      <!-- 记录表格 -->
      <div class="card" :key="`records-card-${recordFilter.project_id}-${recordFilter.module_id}`">
        <div class="card-body" style="padding: 0; overflow-x: auto;">
          <table class="table" v-if="records.length > 0" style="margin: 0; font-size: 12px;">
            <thead>
              <tr>
                <th style="width: 30px;"></th>
                <th
                  :class="['sortable', recordsSort.getSortClass('id')]"
                  @click="recordsSort.sortBy('id')"
                >ID {{ recordsSort.getSortIcon('id') }}</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('project_name')]"
                  @click="recordsSort.sortBy('project_name')"
                >项目 {{ recordsSort.getSortIcon('project_name') }}</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('module_name')]"
                  @click="recordsSort.sortBy('module_name')"
                >模块 {{ recordsSort.getSortIcon('module_name') }}</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('version')]"
                  @click="recordsSort.sortBy('version')"
                >版本 {{ recordsSort.getSortIcon('version') }}</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('recorded_at')]"
                  @click="recordsSort.sortBy('recorded_at')"
                >日期 {{ recordsSort.getSortIcon('recorded_at') }}</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('owner_username')]"
                  @click="recordsSort.sortBy('owner_username')"
                >操作者 {{ recordsSort.getSortIcon('owner_username') }}</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('release_dir')]"
                  @click="recordsSort.sortBy('release_dir')"
                >release_dir {{ recordsSort.getSortIcon('release_dir') }}</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('is_released')]"
                  @click="recordsSort.sortBy('is_released')"
                >发布状态 {{ recordsSort.getSortIcon('is_released') }}</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in sortedRecords" :key="r.id">
                <td>
                  <input type="checkbox" :checked="selectedRecordIds.has(r.id)" @change="toggleRecordSelect(r.id)" />
                </td>
                <td>
                  <a :href="`/record/${r.id}`" target="_blank" style="color: var(--color-primary);">{{ r.id }}</a>
                </td>
                <td>{{ getProjectName(r) }}</td>
                <td>{{ r.module_name || '-' }}</td>
                <td>
                  <span :title="r.version_description">{{ r.version || r.tag || '-' }}</span>
                  <button
                    v-if="r.version_description"
                    class="btn btn-xs"
                    style="font-size: 10px; padding: 0 3px; margin-left: 4px;"
                    :title="r.version_description"
                    @click="editVersionDescription(r.id, r.version_description)"
                  >✏️</button>
                </td>
                <td>{{ r.recorded_at ? r.recorded_at.slice(0,10) : '-' }}</td>
                <td>{{ getOwnerDisplay(r) }}</td>
                <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace; font-size: 11px;"
                  :title="r.release_dir_effective || r.full_dir || ''"
                  :style="{ color: r.is_released && r.release_dir ? '#4caf50' : '#ff9800' }"
                >
                  <template v-if="r.is_released">
                    {{ r.release_dir || '⚠️ ' + (r.release_dir_effective || r.full_dir || '-') + ' (fallback)' }}
                  </template>
                  <template v-else>
                    {{ r.release_dir || r.release_dir_effective || r.full_dir || '-' }}
                  </template>
                  <button
                    class="btn btn-xs"
                    style="font-size: 10px; padding: 0 3px; margin-left: 4px;"
                    title="编辑release_dir"
                    @click="editReleaseDir(r.id, r.release_dir || '')"
                  >✏️</button>
                </td>
                <td>
                  <span class="tag" :style="{
                    background: r.is_released ? '#4caf50' : '#999',
                    color: '#fff',
                    fontSize: '11px'
                  }">{{ r.is_released ? '已发布' : '未发布' }}</span>
                </td>
                <td>
                  <button
                    class="btn btn-sm"
                    :class="r.is_released ? 'btn-default' : 'btn-success'"
                    style="font-size: 11px; padding: 2px 8px;"
                    @click="toggleRelease(r.id)"
                  >{{ r.is_released ? '撤回' : '发布' }}</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="padding: 24px; text-align: center; color: var(--color-text-secondary);">暂无记录，请选择项目后点击查询</p>
        </div>
      </div>

      <SnapshotBackupManager />
    </template>

    <!-- 项目管理 -->
    <template v-if="activeTab === 'projects' && !loading">
      <div class="card">
        <div class="card-header">新增项目</div>
        <div class="card-body">
          <div class="form-row">
            <input v-model="newProject.name" placeholder="项目名称" />
            <input v-model="newProject.description" placeholder="项目描述" />
            <button class="btn" @click="handleCreateProject">创建</button>
          </div>
        </div>
      </div>
      <div class="card" style="margin-top: 12px;">
        <div class="card-header">项目列表 ({{ projects.length }})</div>
        <div class="card-body">
          <table class="table" v-if="projects.length > 0">
            <thead>
              <tr>
                <th
                  :class="['sortable', projectsSort.getSortClass('id')]"
                  @click="projectsSort.sortBy('id')"
                >ID {{ projectsSort.getSortIcon('id') }}</th>
                <th
                  :class="['sortable', projectsSort.getSortClass('name')]"
                  @click="projectsSort.sortBy('name')"
                >名称 {{ projectsSort.getSortIcon('name') }}</th>
                <th
                  :class="['sortable', projectsSort.getSortClass('description')]"
                  @click="projectsSort.sortBy('description')"
                >描述 {{ projectsSort.getSortIcon('description') }}</th>
                <th
                  :class="['sortable', projectsSort.getSortClass('module_count')]"
                  @click="projectsSort.sortBy('module_count')"
                >模块数 {{ projectsSort.getSortIcon('module_count') }}</th>
                <th
                  :class="['sortable', projectsSort.getSortClass('status')]"
                  @click="projectsSort.sortBy('status')"
                >状态 {{ projectsSort.getSortIcon('status') }}</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in sortedProjects" :key="p.id">
                <td>{{ p.id }}</td>
                <td>{{ p.name }}</td>
                <td>{{ p.description || '-' }}</td>
                <td>{{ p.module_count || 0 }}</td>
                <td>
                  <span class="tag" :style="{ background: p.status === 'hidden' ? '#999' : '#4caf50' }">
                    {{ p.status || 'active' }}
                  </span>
                </td>
                <td>
                  <button class="btn btn-sm btn-danger" @click="handleDeleteProject(p.id)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color: var(--color-text-secondary);">暂无项目</p>
        </div>
      </div>
    </template>

    <!-- 模块管理 -->
    <template v-if="activeTab === 'modules' && !loading">
      <div class="card">
        <div class="card-header">新增模块</div>
        <div class="card-body">
          <div class="form-row">
            <input v-model="newModule.name" placeholder="模块名称" />
            <select v-model="newModule.project_id">
              <option value="">选择项目</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <input v-model="newModule.module_type" placeholder="模块类型" />
            <button class="btn" @click="handleCreateModule">创建</button>
          </div>
        </div>
      </div>
      <div class="card" style="margin-top: 12px;">
        <div class="card-header">模块列表 ({{ modules.length }})</div>
        <div class="card-body">
          <table class="table" v-if="modules.length > 0">
            <thead>
              <tr>
                <th
                  :class="['sortable', modulesSort.getSortClass('id')]"
                  @click="modulesSort.sortBy('id')"
                >ID {{ modulesSort.getSortIcon('id') }}</th>
                <th
                  :class="['sortable', modulesSort.getSortClass('name')]"
                  @click="modulesSort.sortBy('name')"
                >名称 {{ modulesSort.getSortIcon('name') }}</th>
                <th
                  :class="['sortable', modulesSort.getSortClass('project_name')]"
                  @click="modulesSort.sortBy('project_name')"
                >所属项目 {{ modulesSort.getSortIcon('project_name') }}</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in sortedModules" :key="m.id">
                <td>{{ m.id }}</td>
                <td>{{ m.name }}</td>
                <td>{{ m.project_name || '-' }}</td>
                <td>
                  <button class="btn btn-sm btn-danger" @click="handleDeleteModule(m.id)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color: var(--color-text-secondary);">暂无模块</p>
        </div>
      </div>
    </template>

    <!-- 用户管理 -->
    <template v-if="activeTab === 'users' && !loading">
      <div class="card">
        <div class="card-header">新增用户</div>
        <div class="card-body">
          <div class="form-row">
            <input v-model="newUser.username" placeholder="用户名" />
            <input v-model="newUser.password" type="password" placeholder="密码" />
            <select v-model="newUser.role">
              <option value="admin">管理员</option>
              <option value="owner">Owner</option>
              <option value="release">Release</option>
              <option value="viewer">观察者</option>
            </select>
            <input v-model="newUser.display_name" placeholder="显示名称" />
            <button class="btn" @click="handleCreateUser">创建</button>
          </div>
        </div>
      </div>
      <div class="card" style="margin-top: 12px;">
        <div class="card-header">用户列表 ({{ users.length }})</div>
        <div class="card-body">
          <table class="table" v-if="users.length > 0">
            <thead>
              <tr>
                <th
                  :class="['sortable', usersSort.getSortClass('username')]"
                  @click="usersSort.sortBy('username')"
                >用户名 {{ usersSort.getSortIcon('username') }}</th>
                <th
                  :class="['sortable', usersSort.getSortClass('role')]"
                  @click="usersSort.sortBy('role')"
                >角色 {{ usersSort.getSortIcon('role') }}</th>
                <th
                  :class="['sortable', usersSort.getSortClass('display_name')]"
                  @click="usersSort.sortBy('display_name')"
                >显示名称 {{ usersSort.getSortIcon('display_name') }}</th>
                <th
                  :class="['sortable', usersSort.getSortClass('created_at')]"
                  @click="usersSort.sortBy('created_at')"
                >创建时间 {{ usersSort.getSortIcon('created_at') }}</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in sortedUsers" :key="u.id">
                <td>{{ u.username }}</td>
                <td>
                  <span class="tag" :style="{
                    background: u.role === 'admin' ? '#e74c3c' : u.role === 'release' ? '#4caf50' : '#3498db',
                    color: '#fff'
                  }">{{ roleLabels[u.role] || u.role }}</span>
                </td>
                <td>{{ u.display_name || '-' }}</td>
                <td>{{ u.created_at || '-' }}</td>
                <td>
                  <button class="btn btn-sm btn-default" @click="handleResetPassword(u.id)">重置密码</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color: var(--color-text-secondary);">暂无用户</p>
        </div>
      </div>
    </template>

    <DataUploadModal v-model="showUploadModal" />
  </div>
</template>

<style scoped>
.admin-page h1 {
  margin-bottom: 20px;
  font-size: 24px;
}
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--color-border);
  flex-wrap: wrap;
}
.tab-btn {
  padding: 10px 16px;
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 14px;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
  cursor: pointer;
}
.tab-btn.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}
.form-row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.form-row input,
.form-row select {
  flex: 1;
}
.record-filter-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.record-filter-bar select,
.record-filter-bar input {
  font-size: 13px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.btn-success {
  background: #4caf50;
  color: white;
}
.btn-success:hover {
  background: #43a047;
}
.btn-xs {
  font-size: 10px;
  padding: 0 4px;
  line-height: 1.4;
  border: 1px solid var(--color-border);
  border-radius: 3px;
  background: transparent;
  cursor: pointer;
}
.btn-xs:hover {
  background: var(--color-surface-hover);
}

/* 排序表头样式 */
.sortable {
  cursor: pointer;
  user-select: none;
  transition: background-color 0.15s ease;
}
.sortable:hover {
  background-color: var(--color-surface-hover);
}
.sortable.sorted {
  background-color: rgba(var(--color-primary-rgb), 0.05);
  color: var(--color-primary);
}
</style>