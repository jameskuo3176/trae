<script setup>
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi } from '@/api/admin'
import { projectsApi } from '@/api/projects'
import { qorApi } from '@/api/qor'
import { reviewApi } from '@/api/review'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import TableFontSizeControl from '@/components/common/TableFontSizeControl.vue'
import DataUploadModal from '@/components/admin/DataUploadModal.vue'
import SnapshotBackupManager from '@/components/admin/SnapshotBackupManager.vue'
import BatchReleaseDirDialog from '@/components/admin/BatchReleaseDirDialog.vue'
import ReleaseDirEditDialog from '@/components/admin/ReleaseDirEditDialog.vue'
import ReviewHierarchyTree from '@/components/admin/ReviewHierarchyTree.vue'
import { useTableSort } from '@/composables/useTableSort'

const activeTab = ref('records')
const route = useRoute()
const router = useRouter()
const projects = ref([])
const hiddenProjects = ref([])
const modules = ref([])
const users = ref([])
const records = ref([])
const recordOwners = ref([])
const hierarchyStatus = ref(null)
const recordsPagination = ref({
  page: Math.max(1, Number(route.query.page) || 1),
  page_size: Math.min(200, Math.max(1, Number(route.query.page_size) || 50)),
  total: 0,
  pages: 0
})
const loading = ref(false)
const error = ref('')
const modulePickerOpen = ref(false)
const moduleFilterActive = ref(false)
const moduleFilter = ref({ projectIds: [], moduleIds: [] })
const modulePickerDraft = ref({ projectIds: [], moduleIds: [] })

// 请求竞态控制：取消上一次未完成的请求
let abortController = null

// 项目管理
const newProject = ref({ name: '', description: '' })
const newModule = ref({ name: '', project_id: '', module_type: '' })
const newUser = ref({ username: '', password: '', role: 'owner', display_name: '' })

// 记录管理筛选
const recordFilter = ref({
  project_id: String(route.query.project_id || ''),
  module_id: String(route.query.module_id || ''),
  version: String(route.query.version || ''),
  owner_id: String(route.query.owner_id || '')
})
const selectedRecordIds = ref(new Set())

// 排序状态
const recordsSort = useTableSort('effective_at', 'desc')
const projectsSort = useTableSort('id', 'desc')
const modulesSort = useTableSort('id', 'desc')
const usersSort = useTableSort('username', 'asc')

// Modal
const showUploadModal = ref(false)
const showBatchReleaseDirDialog = ref(false)
const batchReleaseDirSaving = ref(false)
const batchReleaseDirError = ref('')
const releaseDirEditRecord = ref(null)
const releaseDirEditSaving = ref(false)
const releaseDirEditError = ref('')

const roleLabels = {
  admin: '管理员',
  owner: 'Owner',
  viewer: '观察者'
}

const sortedRecords = computed(() => recordsSort.computeSorted(records.value))
const manageableRecords = computed(() => records.value.filter(record => record.can_manage))
const sortedProjects = computed(() => projectsSort.computeSorted(projects.value))
const writableProjects = computed(() =>
  projects.value.filter(project => project.is_writable !== false && project.status === 'active')
)
const statusLabel = status =>
  ({ active: '可写', locked: '锁定', archived: '归档', hidden: '已隐藏' })[status] || status || '可写'
const statusColor = status =>
  ({ active: '#4caf50', locked: '#f0ad4e', archived: '#78909c', hidden: '#999' })[status] || '#4caf50'
const normalizeIdentityPart = value =>
  encodeURIComponent(
    String(value ?? '')
      .trim()
      .normalize('NFKC')
  )
const projectIdentity = project => normalizeIdentityPart(project?.project_id ?? project?.id)
const moduleIdentity = module =>
  `${normalizeIdentityPart(module?.project_id)}:${normalizeIdentityPart(module?.id)}`
const filteredModules = computed(() => {
  if (!moduleFilterActive.value) return modules.value
  const projectIds = new Set(moduleFilter.value.projectIds)
  const moduleIds = new Set(moduleFilter.value.moduleIds)
  return modules.value.filter(
    module => projectIds.has(projectIdentity(module)) && moduleIds.has(moduleIdentity(module))
  )
})
const sortedModules = computed(() => modulesSort.computeSorted(filteredModules.value))
const sortedUsers = computed(() => usersSort.computeSorted(users.value))
const draftVisibleModules = computed(() => {
  const projectIds = new Set(modulePickerDraft.value.projectIds)
  return modules.value.filter(module => projectIds.has(projectIdentity(module)))
})

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
const moduleFilterValue = module =>
  recordFilter.value.project_id ? String(module.id) : `${module.project_id}:${module.id}`
const recordIdentity = record => `${record.project_id}:${record.id}`
const ownerLabel = owner => owner.display_name || owner.username || `#${owner.id}`

const allModuleProjectIds = () => projects.value.map(projectIdentity)
const allModuleIds = () => modules.value.map(moduleIdentity)

function reconcileModuleFilter() {
  if (!moduleFilterActive.value) return
  const validProjectIds = new Set(allModuleProjectIds())
  const validModuleIds = new Set(allModuleIds())
  const projectIds = moduleFilter.value.projectIds.filter(id => validProjectIds.has(id))
  const moduleIds = moduleFilter.value.moduleIds.filter(id => validModuleIds.has(id))
  moduleFilter.value = { projectIds, moduleIds }
  moduleFilterActive.value =
    projectIds.length !== validProjectIds.size || moduleIds.length !== validModuleIds.size
}

function openModulePicker() {
  modulePickerDraft.value = moduleFilterActive.value
    ? {
        projectIds: [...moduleFilter.value.projectIds],
        moduleIds: [...moduleFilter.value.moduleIds]
      }
    : {
        projectIds: allModuleProjectIds(),
        moduleIds: allModuleIds()
      }
  modulePickerOpen.value = true
}

function closeModulePicker() {
  modulePickerOpen.value = false
}

function applyModulePicker() {
  const validProjectIds = new Set(allModuleProjectIds())
  const validModuleIds = new Set(allModuleIds())
  const projectIds = modulePickerDraft.value.projectIds.filter(id => validProjectIds.has(id))
  const moduleIds = modulePickerDraft.value.moduleIds.filter(id => validModuleIds.has(id))
  moduleFilter.value = { projectIds, moduleIds }
  moduleFilterActive.value =
    projectIds.length !== validProjectIds.size || moduleIds.length !== validModuleIds.size
  closeModulePicker()
}

function resetModuleFilter() {
  moduleFilter.value = {
    projectIds: allModuleProjectIds(),
    moduleIds: allModuleIds()
  }
  moduleFilterActive.value = false
  closeModulePicker()
}

function setAllModulePickerProjects(selected) {
  modulePickerDraft.value.projectIds = selected ? allModuleProjectIds() : []
}

function setAllVisibleModuleOptions(selected) {
  const visibleIds = new Set(draftVisibleModules.value.map(moduleIdentity))
  const preservedIds = modulePickerDraft.value.moduleIds.filter(id => !visibleIds.has(id))
  modulePickerDraft.value.moduleIds = selected ? [...preservedIds, ...visibleIds] : preservedIds
}

function handleModulePickerEscape(event) {
  if (event.key === 'Escape' && modulePickerOpen.value) closeModulePicker()
}

onMounted(async () => {
  document.addEventListener('keydown', handleModulePickerEscape)
  await loadProjects()
  await loadTabData()
})

onBeforeUnmount(() => document.removeEventListener('keydown', handleModulePickerEscape))

watch(activeTab, () => {
  if (activeTab.value === 'records') recordsSort.resetSort()
  if (activeTab.value === 'projects') projectsSort.resetSort()
  if (activeTab.value === 'modules') modulesSort.resetSort()
  if (activeTab.value === 'users') usersSort.resetSort()
  loadTabData()
})

// 项目变更 → 清除模块选择 + 自动加载记录
watch(
  () => recordFilter.value.project_id,
  async () => {
    // 清除可能无效的模块选择
    if (recordFilter.value.module_id) {
      const validModuleIds = filterModules.value.map(moduleFilterValue)
      if (!validModuleIds.includes(String(recordFilter.value.module_id))) {
        recordFilter.value.module_id = ''
      }
    }
    recordsPagination.value.page = 1
    await loadRecordOwners()
    // 自动加载记录（与原始 Django 模板行为一致）
    loadRecords()
  }
)

// 模块变更 → 自动加载记录
watch(
  () => recordFilter.value.module_id,
  () => {
    recordsPagination.value.page = 1
    loadRecords()
  }
)

// Owner 变更 → 自动加载上传者匹配的记录
watch(
  () => recordFilter.value.owner_id,
  () => {
    recordsPagination.value.page = 1
    loadRecords()
  }
)

async function loadProjects() {
  try {
    const data = await projectsApi.list()
    projects.value = data || []
  } catch {
    /* ignore */
  }
}

async function loadRecordOwners(projectId = recordFilter.value.project_id) {
  try {
    const params = {}
    if (projectId) params.project_ids = String(projectId)
    const data = await adminApi.getRecordOwners(params)
    recordOwners.value = Array.isArray(data) ? data : []
    if (
      recordFilter.value.owner_id &&
      !recordOwners.value.some(owner => String(owner.id) === String(recordFilter.value.owner_id))
    ) {
      recordFilter.value.owner_id = ''
    }
  } catch {
    recordOwners.value = []
  }
}

async function loadTabData() {
  loading.value = true
  error.value = ''
  try {
    if (activeTab.value === 'projects') {
      const data = await projectsApi.list()
      projects.value = data || []
      await loadHiddenProjects()
    } else if (activeTab.value === 'modules') {
      const allProjects = await projectsApi.list()
      projects.value = allProjects || []
      const allModules = []
      for (const p of allProjects || []) {
        if (p.modules) {
          p.modules.forEach(m => {
            allModules.push({ ...m, project_name: p.name, project_id: p.id })
          })
        }
      }
      modules.value = allModules
      reconcileModuleFilter()
    } else if (activeTab.value === 'users') {
      const data = await adminApi.listUsers()
      users.value = data || []
    } else if (activeTab.value === 'hierarchy') {
      hierarchyStatus.value = await adminApi.getReviewHierarchyStatus()
    } else if (activeTab.value === 'records') {
      await loadRecordOwners()
      await loadRecords()
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadRecords() {
  // 取消上一次未完成的请求，防止竞态条件
  if (abortController) {
    abortController.abort()
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
      const moduleExists = filterModules.value.some(
        m => moduleFilterValue(m) === String(validModuleId)
      )
      if (!moduleExists) {
        validModuleId = ''
        recordFilter.value.module_id = ''
      }
    }

    const params = {}
    if (validProjectId) {
      params.project_ids = validProjectId
      if (validModuleId) params.module_ids = validModuleId
    } else if (validModuleId && String(validModuleId).includes(':')) {
      const [moduleProjectId, localModuleId] = String(validModuleId).split(':', 2)
      params.project_ids = moduleProjectId
      params.module_ids = localModuleId
    } else {
      params.project_ids = (allProjects || []).map(p => p.id).join(',')
    }
    if (recordFilter.value.version) params.versions = recordFilter.value.version
    if (recordFilter.value.owner_id) params.owner_id = recordFilter.value.owner_id
    params.page = recordsPagination.value.page
    params.page_size = recordsPagination.value.page_size

    const data = await qorApi.getQorData(params, signal)
    // 请求被取消则不再继续
    if (signal.aborted) return

    const rows = Array.isArray(data) ? data : data.records || []
    recordsPagination.value = Array.isArray(data)
      ? { page: 1, page_size: rows.length, total: rows.length, pages: rows.length ? 1 : 0 }
      : data.pagination
    records.value = rows.map(r => ({
      ...r,
      effective_at: r.released_at || r.recorded_at,
      project_name: r.project_name || projectIdToName[r.project_id] || '-',
      module_name:
        r.module_name ||
        filterModules.value.find(
          module =>
            String(module.project_id) === String(r.project_id) &&
            String(module.id) === String(r.module_id)
        )?.name ||
        `#${r.module_id}`
    }))
    selectedRecordIds.value = new Set(
      [...selectedRecordIds.value].filter(identity =>
        records.value.some(record => recordIdentity(record) === identity)
      )
    )
    await router.replace({ query: currentRecordQuery() })
  } catch (e) {
    // 忽略取消导致的错误
    if (e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED' || signal.aborted) return
    error.value = '加载记录失败: ' + (e.message || '未知错误')
  }
}

// 记录管理：切换发布状态
async function toggleRelease(recordId, projectId) {
  try {
    const result = await adminApi.toggleRelease(recordId, projectId)
    const idx = records.value.findIndex(
      r => r.id === recordId && String(r.project_id) === String(projectId)
    )
    if (idx >= 0) {
      records.value[idx] = { ...records.value[idx], ...result }
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '发布操作失败'
  }
}

async function toggleReviewStar(record) {
  if (!record.can_select_review_star) return
  error.value = ''
  try {
    const payload = {
      project_id: Number(record.project_id),
      module_id: Number(record.global_module_id),
      record_id: String(record.id),
      week_start: record.review_week_start
    }
    if (record.review_star) await reviewApi.clearStar(payload)
    else await reviewApi.selectStar(payload)
    await loadRecords()
  } catch (e) {
    error.value =
      e.response?.data?.error ||
      e.response?.data?.detail ||
      e.message ||
      '切换评审星标失败'
  }
}

// 记录管理：编辑 release 目录
function openReleaseDirEditDialog(record) {
  releaseDirEditError.value = ''
  releaseDirEditRecord.value = record
}

function closeReleaseDirEditDialog() {
  if (releaseDirEditSaving.value) return
  releaseDirEditRecord.value = null
  releaseDirEditError.value = ''
}

async function editReleaseDir(newDir) {
  const record = releaseDirEditRecord.value
  if (!record || releaseDirEditSaving.value || newDir.length > 500) return
  releaseDirEditError.value = ''
  releaseDirEditSaving.value = true
  try {
    await adminApi.updateReleaseDir(record.id, record.project_id, newDir)
    releaseDirEditRecord.value = null
    // 服务端重新读取项目库，避免局部乐观更新掩盖跨项目 ID 冲突或持久化失败。
    await loadRecords()
  } catch (e) {
    releaseDirEditError.value =
      e.response?.data?.error || e.response?.data?.detail || e.message || '更新失败'
  } finally {
    releaseDirEditSaving.value = false
  }
}

// 记录管理：清空
function clearRecordSelection() {
  selectedRecordIds.value.clear()
}

// 记录管理：批量发布
async function batchRelease() {
  const items = selectedItems()
  if (items.length === 0) {
    alert('请先勾选要发布的记录')
    return
  }
  if (!confirm('确定要发布选中的' + items.length + '条记录？')) return
  try {
    const result = await adminApi.batchRelease({ items, released: true })
    alert('发布完成: 成功' + (result.updated || 0) + '条')
    selectedRecordIds.value.clear()
    await loadRecords()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '批量发布失败'
  }
}

// 记录管理：批量撤回
async function batchUnrelease() {
  const items = selectedItems()
  if (items.length === 0) {
    alert('请先勾选要撤回的记录')
    return
  }
  if (!confirm('确定要撤回选中的' + items.length + '条记录？')) return
  try {
    const result = await adminApi.batchRelease({ items, released: false })
    alert('撤回完成: 成功' + (result.updated || 0) + '条')
    selectedRecordIds.value.clear()
    await loadRecords()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '批量撤回失败'
  }
}

// 记录管理：批量更新 release_dir
function openBatchReleaseDirDialog() {
  if (selectedCount.value === 0) {
    alert('请先勾选要更新 release_dir 的记录')
    return
  }
  batchReleaseDirError.value = ''
  showBatchReleaseDirDialog.value = true
}

function closeBatchReleaseDirDialog() {
  if (batchReleaseDirSaving.value) return
  showBatchReleaseDirDialog.value = false
  batchReleaseDirError.value = ''
}

async function batchUpdateReleaseDir(items) {
  if (
    batchReleaseDirSaving.value ||
    !Array.isArray(items) ||
    items.length === 0 ||
    items.some(item => String(item.release_dir || '').length > 500)
  ) {
    return
  }

  batchReleaseDirError.value = ''
  batchReleaseDirSaving.value = true
  try {
    const result = await adminApi.batchUpdateReleaseDir({ items })
    const message = `release_dir 更新完成：成功 ${result.updated || 0} 条，跳过 ${result.skipped || 0} 条`
    showBatchReleaseDirDialog.value = false
    selectedRecordIds.value.clear()
    await loadRecords()
    alert(message)
  } catch (e) {
    batchReleaseDirError.value =
      e.response?.data?.error ||
      e.response?.data?.detail ||
      e.message ||
      '批量更新 release_dir 失败'
  } finally {
    batchReleaseDirSaving.value = false
  }
}

// 记录管理：编辑版本描述
async function editVersionDescription(recordId, projectId, currentDesc) {
  const newDesc = prompt('请输入版本描述:\n当前值: ' + (currentDesc || '(无)'), currentDesc || '')
  if (newDesc === null) return
  try {
    await adminApi.updateVersionDescription(recordId, projectId, newDesc)
    const idx = records.value.findIndex(
      r => r.id === recordId && String(r.project_id) === String(projectId)
    )
    if (idx >= 0) {
      records.value[idx] = { ...records.value[idx], version_description: newDesc }
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '更新失败'
  }
}

// 切换记录选中
function toggleRecordSelect(record) {
  const id = recordIdentity(record)
  const s = new Set(selectedRecordIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedRecordIds.value = s
}

function toggleAllRecords() {
  if (selectedRecordIds.value.size === manageableRecords.value.length) {
    selectedRecordIds.value.clear()
  } else {
    selectedRecordIds.value = new Set(manageableRecords.value.map(recordIdentity))
  }
}

const selectedCount = computed(() => selectedRecordIds.value.size)
const selectedRecords = computed(() =>
  records.value.filter(record => selectedRecordIds.value.has(recordIdentity(record)))
)

function getProjectName(r) {
  return r.project_name || '-'
}

function getOwnerDisplay(r) {
  return (
    r.uploader_display_name ||
    r.uploader_username ||
    r.owner_username ||
    (r.owner_id ? '#' + r.owner_id : '-')
  )
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16).replace('T', ' ')
  const pad = number => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function recordsReturnPath() {
  const query = new URLSearchParams(currentRecordQuery())
  const suffix = query.toString()
  return `/admin${suffix ? `?${suffix}` : ''}`
}

function currentRecordQuery() {
  const query = {}
  for (const [key, value] of Object.entries(recordFilter.value)) {
    if (value) query[key] = String(value)
  }
  query.page = String(recordsPagination.value.page)
  query.page_size = String(recordsPagination.value.page_size)
  return query
}

function selectedItems() {
  return [...selectedRecordIds.value].map(identity => {
    const [projectId, recordId] = identity.split(':', 2)
    return { project_id: Number(projectId), record_id: Number(recordId) }
  })
}

async function changePage(page) {
  if (page < 1 || page > recordsPagination.value.pages || page === recordsPagination.value.page)
    return
  recordsPagination.value.page = page
  await loadRecords()
}

async function changePageSize() {
  recordsPagination.value.page = 1
  await loadRecords()
}

async function deleteRecord(record) {
  if (!confirm(`确定删除 ${record.project_name || record.project_id} / #${record.id}？`)) return
  error.value = ''
  try {
    await adminApi.deleteRecord(record.id, record.project_id)
    selectedRecordIds.value.delete(recordIdentity(record))
    if (records.value.length === 1 && recordsPagination.value.page > 1) {
      recordsPagination.value.page -= 1
    }
    await loadRecords()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '删除失败'
  }
}

// 项目管理CRUD
async function loadHiddenProjects() {
  try {
    const data = await adminApi.listHiddenProjects()
    hiddenProjects.value = Array.isArray(data) ? data : []
  } catch {
    hiddenProjects.value = []
  }
}

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
  if (!confirm('确定要隐藏这个项目吗？数据会保留，可在“已隐藏项目”中恢复。')) return
  try {
    await adminApi.deleteProject(id)
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
}

async function handleRestoreProject(project) {
  if (!confirm(`确认恢复项目 “${project.name}”？`)) return
  error.value = ''
  try {
    await adminApi.restoreProject(project.id)
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '恢复失败'
  }
}

async function handleHardDeleteProject(project) {
  const warning =
    `彻底删除项目 “${project.name}”？\n` +
    `将删除 ${project.module_count || 0} 个模块 / ${project.record_count || 0} 条记录，不可恢复。`
  if (!confirm(warning)) return
  if (!confirm('再次确认：真的要彻底删除吗？')) return
  error.value = ''
  try {
    await adminApi.hardDeleteProject(project.id)
    await loadHiddenProjects()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '彻底删除失败'
  }
}

async function handleLockProject(project) {
  const reason = prompt(
    `锁定 “${project.name}”？\n锁定后禁止上传，但仍可查看历史数据。\n可选填写锁定原因:`,
    project.lock_reason || ''
  )
  if (reason === null) return
  error.value = ''
  try {
    await adminApi.lockProject(project.id, reason)
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '锁定失败'
  }
}

async function handleUnlockProject(project) {
  if (!confirm(`解锁 “${project.name}”？解锁后可继续上传。`)) return
  error.value = ''
  try {
    await adminApi.unlockProject(project.id)
    await loadTabData()
  } catch (e) {
    error.value = e.response?.data?.error || e.message || '解锁失败'
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
    <div class="admin-heading">
      <h1>管理后台</h1>
      <TableFontSizeControl />
    </div>
    <div class="tabs">
      <button
        :class="['tab-btn', { active: activeTab === 'records' }]"
        @click="activeTab = 'records'"
      >
        记录管理
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'projects' }]"
        @click="activeTab = 'projects'"
      >
        项目管理
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'modules' }]"
        @click="activeTab = 'modules'"
      >
        模块管理
      </button>
      <button :class="['tab-btn', { active: activeTab === 'users' }]" @click="activeTab = 'users'">
        用户管理
      </button>
      <button
        :class="['tab-btn', { active: activeTab === 'hierarchy' }]"
        @click="activeTab = 'hierarchy'"
      >
        评审层级状态
      </button>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>
    <LoadingSpinner v-if="loading" text="加载中..." />

    <!-- 记录管理 -->
    <template v-if="activeTab === 'records' && !loading">
      <div class="card" style="margin-bottom: 12px">
        <div class="card-header">
          <span>📋 记录管理</span>
          <div class="header-actions">
            <button class="btn" @click="showUploadModal = true">📤 上传数据</button>
          </div>
        </div>
        <div class="card-body" style="padding: 10px 16px">
          <div class="record-filter-bar">
            <select v-model="recordFilter.project_id" style="min-width: 140px">
              <option value="">全部项目</option>
              <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <select v-model="recordFilter.module_id" style="min-width: 140px">
              <option value="">全部模块</option>
              <option
                v-for="m in filterModules"
                :key="`${m.project_id}:${m.id}`"
                :value="moduleFilterValue(m)"
              >
                {{ m.name }}{{ recordFilter.project_id ? '' : ` · ${m.project_name}` }}
              </option>
            </select>
            <select
              v-model="recordFilter.owner_id"
              aria-label="Owner"
              style="min-width: 140px"
            >
              <option value="">全部 Owner</option>
              <option v-for="owner in recordOwners" :key="owner.id" :value="String(owner.id)">
                {{ ownerLabel(owner) }}
              </option>
            </select>
            <input
              v-model="recordFilter.version"
              placeholder="版本号"
              style="width: 120px"
              @keyup.enter="loadRecords"
            />
            <button class="btn btn-sm" @click="loadRecords">查询</button>
            <span style="margin-left: auto; font-size: 12px; color: var(--color-text-secondary)">
              共 {{ recordsPagination.total }} 条记录
            </span>
          </div>
        </div>
      </div>

      <!-- 批量操作 -->
      <div class="card" style="margin-bottom: 12px">
        <div
          class="card-body"
          style="padding: 8px 16px; display: flex; gap: 8px; align-items: center"
        >
          <label
            style="display: flex; align-items: center; gap: 4px; font-size: 12px; cursor: pointer"
          >
            <input
              type="checkbox"
              :checked="selectedCount === manageableRecords.length && manageableRecords.length > 0"
              @change="toggleAllRecords"
            />
            全选
          </label>
          <span style="font-size: 12px; color: var(--color-text-secondary)"
            >已选 {{ selectedCount }} 条</span
          >
          <button
            class="btn btn-sm btn-success"
            :disabled="selectedCount === 0"
            @click="batchRelease"
          >
            批量发布
          </button>
          <button
            class="btn btn-sm btn-default"
            :disabled="selectedCount === 0"
            @click="batchUnrelease"
          >
            批量撤回
          </button>
          <button
            class="btn btn-sm btn-default"
            :disabled="selectedCount === 0"
            @click="openBatchReleaseDirDialog"
          >
            批量更新 release_dir
          </button>
          <button
            class="btn btn-sm btn-default"
            :disabled="selectedCount === 0"
            @click="clearRecordSelection"
          >
            清空选择
          </button>
        </div>
      </div>

      <!-- 记录表格 -->
      <div :key="`records-card-${recordFilter.project_id}-${recordFilter.module_id}`" class="card">
        <div class="card-body" style="padding: 0; overflow-x: auto">
          <table v-if="records.length > 0" class="table records-table" style="margin: 0">
            <thead>
              <tr>
                <th style="width: 30px"></th>
                <th style="width: 52px">评审</th>
                <th
                  :class="['sortable', recordsSort.getSortClass('id')]"
                  @click="recordsSort.sortBy('id')"
                >
                  ID {{ recordsSort.getSortIcon('id') }}
                </th>
                <th
                  :class="['sortable', recordsSort.getSortClass('project_name')]"
                  @click="recordsSort.sortBy('project_name')"
                >
                  项目 {{ recordsSort.getSortIcon('project_name') }}
                </th>
                <th
                  :class="['sortable', recordsSort.getSortClass('module_name')]"
                  @click="recordsSort.sortBy('module_name')"
                >
                  模块 {{ recordsSort.getSortIcon('module_name') }}
                </th>
                <th
                  :class="['sortable', recordsSort.getSortClass('version')]"
                  @click="recordsSort.sortBy('version')"
                >
                  版本 {{ recordsSort.getSortIcon('version') }}
                </th>
                <th
                  :class="['sortable', recordsSort.getSortClass('effective_at')]"
                  @click="recordsSort.sortBy('effective_at')"
                >
                  日期 {{ recordsSort.getSortIcon('effective_at') }}
                </th>
                <th
                  :class="['sortable', recordsSort.getSortClass('owner_username')]"
                  @click="recordsSort.sortBy('owner_username')"
                >
                  上传者 {{ recordsSort.getSortIcon('owner_username') }}
                </th>
                <th
                  :class="['sortable', recordsSort.getSortClass('release_dir')]"
                  @click="recordsSort.sortBy('release_dir')"
                >
                  release_dir {{ recordsSort.getSortIcon('release_dir') }}
                </th>
                <th
                  :class="['sortable', recordsSort.getSortClass('is_released')]"
                  @click="recordsSort.sortBy('is_released')"
                >
                  发布状态 {{ recordsSort.getSortIcon('is_released') }}
                </th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in sortedRecords" :key="`${r.project_id}:${r.id}`">
                <td>
                  <input
                    v-if="r.can_manage"
                    type="checkbox"
                    :checked="selectedRecordIds.has(recordIdentity(r))"
                    @change="toggleRecordSelect(r)"
                  />
                </td>
                <td class="review-star-cell">
                  <button
                    type="button"
                    :class="['record-review-star', { selected: r.review_star }]"
                    :disabled="!r.can_select_review_star"
                    :aria-label="
                      r.review_star
                        ? `取消 ${r.module_name} ${r.version} 的评审星标`
                        : `将 ${r.module_name} ${r.version} 选为评审版本`
                    "
                    :title="
                      r.review_star
                        ? `点击取消 ${r.review_week_start} 当周评审星标`
                        : r.can_select_review_star
                          ? `设为 ${r.review_week_start} 当周评审版本`
                          : '无权限或 Module 尚未配置评审映射'
                    "
                    @click="toggleReviewStar(r)"
                  >
                    ★
                  </button>
                </td>
                <td>
                  <router-link
                    :to="{
                      name: 'RecordDetail',
                      params: { id: r.id },
                      query: { next: recordsReturnPath(), project_id: r.project_id }
                    }"
                    style="color: var(--color-primary)"
                  >
                    {{ r.id }}
                  </router-link>
                </td>
                <td>{{ getProjectName(r) }}</td>
                <td>{{ r.module_name || `#${r.module_id}` }}</td>
                <td>
                  <span :title="r.version_description">{{ r.version || r.tag || '-' }}</span>
                  <button
                    v-if="r.version_description && r.can_edit_description"
                    class="btn btn-xs table-inline-action"
                    :title="r.version_description"
                    @click="editVersionDescription(r.id, r.project_id, r.version_description)"
                  >
                    ✏️
                  </button>
                </td>
                <td>{{ r.release_sort_at_display || formatDateTime(r.effective_at) }}</td>
                <td>{{ getOwnerDisplay(r) }}</td>
                <td
                  class="release-dir-cell"
                  :style="{ color: r.is_released && r.release_dir ? '#4caf50' : '#ff9800' }"
                >
                  <span
                    class="release-dir-text"
                    :title="r.release_dir_effective || r.full_dir || ''"
                  >
                    <template v-if="r.is_released">
                      {{
                        r.release_dir ||
                        '⚠️ ' + (r.release_dir_effective || r.full_dir || '-') + ' (fallback)'
                      }}
                    </template>
                    <template v-else>
                      {{ r.release_dir || r.release_dir_effective || r.full_dir || '-' }}
                    </template>
                  </span>
                  <button
                    v-if="r.can_manage"
                    class="btn btn-xs release-dir-edit-btn"
                    :class="{ 'is-empty': !r.release_dir }"
                    :title="
                      r.release_dir
                        ? '修改发布目录（留空将使用 full_dir 兜底）'
                        : '添加发布目录（留空将使用 full_dir 兜底）'
                    "
                    @click="openReleaseDirEditDialog(r)"
                  >
                    ✏️ {{ r.release_dir ? '编辑' : '添加' }}
                  </button>
                </td>
                <td>
                  <span
                    class="tag release-status-tag"
                    :style="{
                      background: r.is_released ? '#4caf50' : '#999',
                      color: '#fff'
                    }"
                    >{{ r.is_released ? '已发布' : '未发布' }}</span
                  >
                </td>
                <td>
                  <button
                    v-if="r.can_manage"
                    class="btn btn-sm table-row-action"
                    :class="r.is_released ? 'btn-default' : 'btn-success'"
                    @click="toggleRelease(r.id, r.project_id)"
                  >
                    {{ r.is_released ? '撤回' : '发布' }}
                  </button>
                  <button
                    v-if="r.can_manage"
                    class="btn btn-sm btn-danger table-row-action"
                    style="margin-left: 4px"
                    @click="deleteRecord(r)"
                  >
                    删除
                  </button>
                  <span v-if="!r.can_manage" class="muted-action">只读</span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="padding: 24px; text-align: center; color: var(--color-text-secondary)">
            暂无记录，请选择项目后点击查询
          </p>
        </div>
      </div>
      <nav v-if="recordsPagination.pages > 0" class="record-pagination" aria-label="记录分页">
        <button
          class="btn btn-sm btn-default"
          :disabled="recordsPagination.page <= 1"
          @click="changePage(recordsPagination.page - 1)"
        >
          上一页
        </button>
        <span>第 {{ recordsPagination.page }} / {{ recordsPagination.pages }} 页</span>
        <button
          class="btn btn-sm btn-default"
          :disabled="recordsPagination.page >= recordsPagination.pages"
          @click="changePage(recordsPagination.page + 1)"
        >
          下一页
        </button>
        <select v-model.number="recordsPagination.page_size" @change="changePageSize">
          <option :value="25">25 / 页</option>
          <option :value="50">50 / 页</option>
          <option :value="100">100 / 页</option>
          <option :value="200">200 / 页</option>
        </select>
      </nav>

      <SnapshotBackupManager :project-id="recordFilter.project_id" />
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
      <div class="card" style="margin-top: 12px">
        <div class="card-header">项目列表 ({{ projects.length }})</div>
        <div class="card-body">
          <table v-if="projects.length > 0" class="table">
            <thead>
              <tr>
                <th
                  :class="['sortable', projectsSort.getSortClass('id')]"
                  @click="projectsSort.sortBy('id')"
                >
                  ID {{ projectsSort.getSortIcon('id') }}
                </th>
                <th
                  :class="['sortable', projectsSort.getSortClass('name')]"
                  @click="projectsSort.sortBy('name')"
                >
                  名称 {{ projectsSort.getSortIcon('name') }}
                </th>
                <th
                  :class="['sortable', projectsSort.getSortClass('description')]"
                  @click="projectsSort.sortBy('description')"
                >
                  描述 {{ projectsSort.getSortIcon('description') }}
                </th>
                <th
                  :class="['sortable', projectsSort.getSortClass('module_count')]"
                  @click="projectsSort.sortBy('module_count')"
                >
                  模块数 {{ projectsSort.getSortIcon('module_count') }}
                </th>
                <th
                  :class="['sortable', projectsSort.getSortClass('status')]"
                  @click="projectsSort.sortBy('status')"
                >
                  状态 {{ projectsSort.getSortIcon('status') }}
                </th>
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
                  <span
                    class="tag"
                    :style="{ background: statusColor(p.status), color: '#fff' }"
                    :title="p.lock_reason || ''"
                  >
                    {{ statusLabel(p.status) }}
                  </span>
                  <div v-if="p.status === 'locked'" class="project-lock-hint">
                    禁上传，可查看历史数据
                    <template v-if="p.lock_reason"> · {{ p.lock_reason }}</template>
                  </div>
                </td>
                <td class="project-actions">
                  <button
                    v-if="p.status === 'locked'"
                    class="btn btn-sm btn-success"
                    @click="handleUnlockProject(p)"
                  >
                    解锁
                  </button>
                  <button
                    v-else
                    class="btn btn-sm btn-default"
                    @click="handleLockProject(p)"
                  >
                    锁定
                  </button>
                  <button class="btn btn-sm btn-danger" @click="handleDeleteProject(p.id)">
                    隐藏
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color: var(--color-text-secondary)">暂无项目</p>
        </div>
      </div>
      <div class="card" style="margin-top: 12px">
        <div class="card-header">
          <span>已隐藏项目 ({{ hiddenProjects.length }})</span>
          <button class="btn btn-sm btn-default" type="button" @click="loadHiddenProjects">
            刷新
          </button>
        </div>
        <div class="card-body">
          <p class="project-help">
            隐藏后项目从常规列表消失，模块/记录仍保留，可随时恢复；彻底删除不可恢复。
          </p>
          <table v-if="hiddenProjects.length > 0" class="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>名称</th>
                <th>模块/记录</th>
                <th>隐藏信息</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in hiddenProjects" :key="`hidden-${p.id}`">
                <td>{{ p.id }}</td>
                <td>{{ p.name }}</td>
                <td>{{ p.module_count || 0 }} / {{ p.record_count || 0 }}</td>
                <td>
                  {{ p.hidden_by_name || '-' }}
                  <span v-if="p.hidden_at"> · {{ formatDateTime(p.hidden_at) }}</span>
                </td>
                <td class="project-actions">
                  <button class="btn btn-sm btn-success" @click="handleRestoreProject(p)">
                    恢复
                  </button>
                  <button class="btn btn-sm btn-danger" @click="handleHardDeleteProject(p)">
                    彻底删除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color: var(--color-text-secondary)">无已隐藏项目</p>
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
              <option v-for="p in writableProjects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
            <input v-model="newModule.module_type" placeholder="模块类型" />
            <button class="btn" @click="handleCreateModule">创建</button>
          </div>
        </div>
      </div>
      <div class="card" style="margin-top: 12px">
        <div class="card-header module-list-header">
          <div>
            <span>模块列表</span>
            <small v-if="moduleFilterActive">
              {{ filteredModules.length }} / {{ modules.length }} visible
            </small>
            <small v-else>{{ modules.length }} total</small>
          </div>
          <button
            class="module-picker-trigger"
            type="button"
            :aria-expanded="modulePickerOpen"
            aria-controls="admin-module-picker"
            @click="openModulePicker"
          >
            <span aria-hidden="true">#</span> pick
          </button>
        </div>
        <div class="card-body">
          <table v-if="filteredModules.length > 0" class="table">
            <thead>
              <tr>
                <th
                  :class="['sortable', modulesSort.getSortClass('id')]"
                  @click="modulesSort.sortBy('id')"
                >
                  ID {{ modulesSort.getSortIcon('id') }}
                </th>
                <th
                  :class="['sortable', modulesSort.getSortClass('name')]"
                  @click="modulesSort.sortBy('name')"
                >
                  名称 {{ modulesSort.getSortIcon('name') }}
                </th>
                <th
                  :class="['sortable', modulesSort.getSortClass('project_name')]"
                  @click="modulesSort.sortBy('project_name')"
                >
                  所属项目 {{ modulesSort.getSortIcon('project_name') }}
                </th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in sortedModules" :key="moduleIdentity(m)">
                <td>{{ m.id }}</td>
                <td>{{ m.name }}</td>
                <td>{{ m.project_name || '-' }}</td>
                <td>
                  <button class="btn btn-sm btn-danger" @click="handleDeleteModule(m.id)">
                    删除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else-if="modules.length && moduleFilterActive" class="module-filter-empty">
            <strong>没有模块匹配当前 #pick 条件</strong>
            <span>调整 Project / Module 选择，或恢复显示全部模块。</span>
            <button class="btn btn-sm btn-default" type="button" @click="resetModuleFilter">
              Reset · Show all
            </button>
          </div>
          <p v-else class="module-empty">暂无模块</p>
        </div>
      </div>
    </template>

    <div v-if="modulePickerOpen" class="module-picker-mask" @mousedown.self="closeModulePicker">
      <section
        id="admin-module-picker"
        class="module-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="admin-module-picker-title"
      >
        <header>
          <div>
            <span class="module-picker-kicker">ADMIN MODULE SCOPE</span>
            <h2 id="admin-module-picker-title">#pick 模块列表</h2>
            <p>草稿选择仅在 Apply 后更新模块列表。</p>
          </div>
          <button
            class="module-picker-close"
            type="button"
            aria-label="关闭模块筛选"
            @click="closeModulePicker"
          >
            ×
          </button>
        </header>

        <div class="module-picker-grid">
          <fieldset>
            <legend>
              Projects
              <b>{{ modulePickerDraft.projectIds.length }} / {{ projects.length }}</b>
            </legend>
            <div class="module-picker-actions">
              <button type="button" @click="setAllModulePickerProjects(true)">All</button>
              <button type="button" @click="setAllModulePickerProjects(false)">None</button>
            </div>
            <div class="module-picker-options">
              <label v-for="project in projects" :key="projectIdentity(project)">
                <input
                  v-model="modulePickerDraft.projectIds"
                  type="checkbox"
                  :value="projectIdentity(project)"
                />
                <span>{{ project.name }}</span>
              </label>
              <p v-if="!projects.length" class="module-picker-empty">暂无 Project</p>
            </div>
          </fieldset>

          <fieldset>
            <legend>
              Modules
              <b>
                {{
                  draftVisibleModules.filter(module =>
                    modulePickerDraft.moduleIds.includes(moduleIdentity(module))
                  ).length
                }}
                / {{ draftVisibleModules.length }}
              </b>
            </legend>
            <div class="module-picker-actions">
              <button type="button" @click="setAllVisibleModuleOptions(true)">All</button>
              <button type="button" @click="setAllVisibleModuleOptions(false)">None</button>
            </div>
            <div class="module-picker-options">
              <label v-for="module in draftVisibleModules" :key="moduleIdentity(module)">
                <input
                  v-model="modulePickerDraft.moduleIds"
                  type="checkbox"
                  :value="moduleIdentity(module)"
                />
                <span>
                  {{ module.name }}
                  <small>{{ module.project_name || 'Unknown project' }}</small>
                </span>
              </label>
              <p v-if="!draftVisibleModules.length" class="module-picker-empty">
                当前 Project 选择下没有 Module
              </p>
            </div>
          </fieldset>
        </div>

        <footer>
          <button class="module-picker-reset" type="button" @click="resetModuleFilter">
            Reset · Show all
          </button>
          <span>
            Apply 后预计显示
            {{
              modules.filter(
                module =>
                  modulePickerDraft.projectIds.includes(projectIdentity(module)) &&
                  modulePickerDraft.moduleIds.includes(moduleIdentity(module))
              ).length
            }}
            / {{ modules.length }}
          </span>
          <div>
            <button class="btn btn-sm btn-default" type="button" @click="closeModulePicker">
              Cancel
            </button>
            <button class="btn btn-sm" type="button" @click="applyModulePicker">Apply</button>
          </div>
        </footer>
      </section>
    </div>

    <!-- 用户管理 -->
    <template v-if="activeTab === 'users' && !loading">
      <div class="card">
        <div class="card-header">新增用户</div>
        <div class="card-body">
          <div class="form-row">
            <input v-model="newUser.username" placeholder="用户名" autocomplete="off" />
            <input
              v-model="newUser.password"
              type="password"
              placeholder="密码"
              autocomplete="new-password"
            />
            <select v-model="newUser.role">
              <option value="admin">管理员</option>
              <option value="owner">Owner</option>
              <option value="viewer">观察者</option>
            </select>
            <input v-model="newUser.display_name" placeholder="显示名称" autocomplete="off" />
            <button class="btn" @click="handleCreateUser">创建</button>
          </div>
        </div>
      </div>
      <div class="card" style="margin-top: 12px">
        <div class="card-header">用户列表 ({{ users.length }})</div>
        <div class="card-body">
          <table v-if="users.length > 0" class="table">
            <thead>
              <tr>
                <th
                  :class="['sortable', usersSort.getSortClass('username')]"
                  @click="usersSort.sortBy('username')"
                >
                  用户名 {{ usersSort.getSortIcon('username') }}
                </th>
                <th
                  :class="['sortable', usersSort.getSortClass('role')]"
                  @click="usersSort.sortBy('role')"
                >
                  角色 {{ usersSort.getSortIcon('role') }}
                </th>
                <th
                  :class="['sortable', usersSort.getSortClass('display_name')]"
                  @click="usersSort.sortBy('display_name')"
                >
                  显示名称 {{ usersSort.getSortIcon('display_name') }}
                </th>
                <th
                  :class="['sortable', usersSort.getSortClass('created_at')]"
                  @click="usersSort.sortBy('created_at')"
                >
                  创建时间 {{ usersSort.getSortIcon('created_at') }}
                </th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in sortedUsers" :key="u.id">
                <td>{{ u.username }}</td>
                <td>
                  <span
                    class="tag"
                    :style="{
                      background: u.role === 'admin' ? '#e74c3c' : '#3498db',
                      color: '#fff'
                    }"
                    >{{ roleLabels[u.role] || u.role }}</span
                  >
                </td>
                <td>{{ u.display_name || '-' }}</td>
                <td>{{ u.created_at || '-' }}</td>
                <td>
                  <button class="btn btn-sm btn-default" @click="handleResetPassword(u.id)">
                    重置密码
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color: var(--color-text-secondary)">暂无用户</p>
        </div>
      </div>
    </template>

    <!-- YAML 评审层级 -->
    <template v-if="activeTab === 'hierarchy' && !loading">
      <ReviewHierarchyTree
        v-if="hierarchyStatus"
        :status="hierarchyStatus"
        @updated="hierarchyStatus = $event"
      />
    </template>

    <DataUploadModal v-model="showUploadModal" />
    <BatchReleaseDirDialog
      :open="showBatchReleaseDirDialog"
      :records="selectedRecords"
      :saving="batchReleaseDirSaving"
      :error="batchReleaseDirError"
      @close="closeBatchReleaseDirDialog"
      @submit="batchUpdateReleaseDir"
    />
    <ReleaseDirEditDialog
      :open="Boolean(releaseDirEditRecord)"
      :record="releaseDirEditRecord"
      :saving="releaseDirEditSaving"
      :error="releaseDirEditError"
      @close="closeReleaseDirEditDialog"
      @submit="editReleaseDir"
    />
  </div>
</template>

<style scoped>
.admin-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.admin-page h1 {
  margin: 0;
  font-size: 24px;
}
.review-star-cell {
  text-align: center;
}
.record-review-star {
  padding: 2px 5px;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 20px;
  line-height: 1;
}
.record-review-star:not(:disabled) {
  cursor: pointer;
}
.record-review-star:not(:disabled):hover {
  color: #2eea7a;
}
.record-review-star.selected {
  color: #2eea7a;
  text-shadow: 0 0 8px color-mix(in srgb, #2eea7a 60%, transparent);
}
.record-review-star:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
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
.project-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.project-lock-hint {
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 11px;
}
.project-help {
  margin: 0 0 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.record-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.record-pagination select {
  width: auto;
}
.muted-action {
  color: var(--color-text-secondary);
  font-size: 0.92em;
}
.records-table .release-dir-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 300px;
  font-family: ui-monospace, Consolas, Monaco, monospace;
}
.records-table .release-dir-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.records-table .release-status-tag {
  font-size: 0.92em;
}
.records-table .table-inline-action {
  padding: 0 3px;
  margin-left: 4px;
  font-size: 0.85em;
}
.records-table .release-dir-edit-btn {
  flex-shrink: 0;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.6;
  border: 1px solid var(--color-primary);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-primary);
  white-space: nowrap;
}
.records-table .release-dir-edit-btn:hover {
  background: var(--color-primary);
  color: var(--color-surface);
}
.records-table .release-dir-edit-btn.is-empty {
  border-style: dashed;
}
.records-table .table-row-action {
  padding: 2px 8px;
  font-size: 0.92em;
}
.hierarchy-status .card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.hierarchy-badge {
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
}
.hierarchy-badge.is-valid {
  background: var(--color-success);
  color: var(--color-success-background);
}
.hierarchy-badge.is-invalid {
  background: var(--color-danger, #c0392b);
  color: #fff;
}
.hierarchy-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  margin: 0 0 16px;
}
.hierarchy-meta div {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--color-border);
}
.hierarchy-meta dt {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.hierarchy-meta dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}
.hierarchy-errors {
  color: var(--color-danger, #c0392b);
}
.hierarchy-project {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid var(--color-border);
}
.hierarchy-project header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.hierarchy-project h3 {
  margin: 0;
}
.hierarchy-thresholds {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin: 10px 0;
  font-size: 12px;
}
.hierarchy-group {
  margin-top: 8px;
  padding-left: 10px;
  border-left: 3px solid var(--color-primary);
}
.hierarchy-group > span {
  margin-left: 8px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.btn-success {
  background: var(--color-success);
  color: var(--color-success-background);
}
.btn-success:hover {
  background: color-mix(in srgb, var(--color-success) 88%, var(--color-text));
  color: var(--color-success-background);
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
  color: var(--color-text-on-hover);
}

/* 排序表头样式 */
.sortable {
  cursor: pointer;
  user-select: none;
  transition: background-color 0.15s ease;
}
.sortable:hover {
  background-color: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.sortable.sorted {
  background-color: rgba(var(--color-primary-rgb), 0.05);
  color: var(--color-primary);
}
.module-list-header > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.module-list-header small {
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 500;
}
.module-picker-trigger {
  padding: 5px 10px;
  border: 1px solid var(--color-primary);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-primary);
  font-weight: 700;
}
.module-picker-trigger:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.module-picker-trigger span {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.module-empty {
  color: var(--color-text-secondary);
}
.module-filter-empty {
  display: grid;
  justify-items: center;
  gap: 7px;
  padding: 32px 20px;
  border: 1px dashed var(--color-border-strong);
  color: var(--color-text-secondary);
  text-align: center;
}
.module-filter-empty strong {
  color: var(--color-text);
}
.module-filter-empty .btn {
  margin-top: 5px;
}
.module-picker-mask {
  position: fixed;
  z-index: 1200;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: var(--color-overlay);
}
.module-picker {
  display: flex;
  flex-direction: column;
  width: min(820px, 100%);
  max-height: min(720px, 92vh);
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-top: 4px solid var(--color-primary);
  border-radius: 4px;
  background: var(--color-surface-elevated);
  color: var(--color-text);
  box-shadow: 0 20px 54px var(--color-shadow);
}
.module-picker > header,
.module-picker > footer {
  position: sticky;
  z-index: 2;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 18px;
}
.module-picker > header {
  top: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-elevated);
}
.module-picker > header h2 {
  margin: 0;
  font-size: 18px;
}
.module-picker > header p {
  margin: 3px 0 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.module-picker-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
}
.module-picker-close {
  padding: 2px 8px;
  border: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 24px;
}
.module-picker-close:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.module-picker-grid {
  flex: 1 1 auto;
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.35fr);
  gap: 14px;
  min-height: 0;
  overflow: auto;
  padding: 18px;
}
.module-picker fieldset {
  position: relative;
  min-width: 0;
  margin: 0;
  padding: 36px 10px 10px;
  border: 1px solid var(--color-border);
  border-radius: 5px;
}
.module-picker legend {
  position: absolute;
  top: 10px;
  left: 10px;
  padding: 0;
  font-size: 12px;
  font-weight: 800;
}
.module-picker legend b {
  margin-left: 5px;
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
}
.module-picker-actions {
  position: absolute;
  top: 7px;
  right: 8px;
  display: flex;
  gap: 4px;
}
.module-picker-actions button {
  padding: 2px 7px;
  border: 1px solid var(--color-border);
  border-radius: 3px;
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 11px;
}
.module-picker-actions button:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.module-picker-options {
  max-height: 360px;
  overflow: auto;
}
.module-picker-options label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 6px;
  border-bottom: 1px solid var(--color-border);
  font-size: 12px;
  cursor: pointer;
}
.module-picker-options label:last-of-type {
  border-bottom: 0;
}
.module-picker-options label:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.module-picker-options label span {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.module-picker-options label small {
  color: var(--color-text-secondary);
  font-size: 10px;
}
.module-picker-options label:hover small {
  color: inherit;
}
.module-picker-empty {
  padding: 18px 8px;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-align: center;
}
.module-picker > footer {
  bottom: 0;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}
.module-picker > footer > span {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.module-picker > footer > div {
  display: flex;
  gap: 8px;
}
.module-picker-reset {
  border: 0;
  background: transparent;
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
}
.module-picker-reset:hover {
  color: var(--color-primary-hover);
  text-decoration: underline;
}
@media (max-width: 680px) {
  .form-row {
    align-items: stretch;
    flex-direction: column;
  }
  .module-picker-grid {
    grid-template-columns: 1fr;
    overscroll-behavior: contain;
  }
  .module-picker-options {
    max-height: 220px;
  }
  .module-picker > footer {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
    padding: 10px 12px;
  }
  .module-picker > footer > div {
    justify-content: flex-end;
  }
}
@media (max-width: 420px) {
  .module-picker-mask {
    padding: 8px;
  }
  .module-picker {
    max-height: calc(100dvh - 16px);
  }
}
</style>
