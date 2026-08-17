<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardData } from '@/composables/useDashboardData'

const filters = useFiltersStore()
const { loadModules, loadVersions, loadDashboardData } = useDashboardData()
const projectQuery = ref('')
const moduleQuery = ref('')
const versionQuery = ref('')
const dirPrefixDraft = ref(filters.dirPrefix)
const projectPickerOpen = ref(false)
const modulePickerOpen = ref(false)
const projectPickerEl = ref(null)
const modulePickerEl = ref(null)
const visibleProjects = computed(() =>
  filters.projects.filter(item =>
    item.name.toLowerCase().includes(projectQuery.value.toLowerCase())
  )
)
const visibleModules = computed(() =>
  filters.modules.filter(item => item.name.toLowerCase().includes(moduleQuery.value.toLowerCase()))
)
const visibleVersions = computed(() =>
  filters.versions.filter(item => matchesVersion(String(item), versionQuery.value))
)
const selectedProjectCount = computed(
  () => filters.projectIds.filter(id => filters.projects.some(p => String(p.id) === String(id)))
    .length
)
const selectedModuleCount = computed(
  () => filters.moduleIds.filter(id => filters.modules.some(m => String(m.id) === String(id))).length
)

/** 将含 * 通配符的模式转换为正则表达式（* 匹配任意字符） */
function wildcardToRegExp(pattern) {
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')
  return new RegExp(`^${escaped}$`, 'i')
}

/** 版本匹配：含 * 时按通配符匹配，否则按子串包含匹配 */
function matchesVersion(version, query) {
  const q = query.trim()
  if (!q) return true
  if (q.includes('*')) {
    return wildcardToRegExp(q).test(version)
  }
  return version.toLowerCase().includes(q.toLowerCase())
}

/** 将版本搜索框内容应用到版本过滤（支持 * 通配符），然后加载数据 */
async function applyVersionFilter() {
  const q = versionQuery.value.trim()
  if (!q) return
  const matched = filters.versions
    .map(String)
    .filter(version => matchesVersion(version, q))
    .sort()
  filters.versionIds = matched
  filters.versionFilterApplied = true
  await loadDashboardData()
}

async function applyFilters() {
  filters.dirPrefix = dirPrefixDraft.value.trim()
  if (versionQuery.value.trim()) {
    await applyVersionFilter()
  } else {
    filters.versionFilterApplied = false
    await loadDashboardData()
  }
}

function openProjectPicker() {
  projectQuery.value = ''
  projectPickerOpen.value = true
}
function closeProjectPicker() {
  projectPickerOpen.value = false
}
function selectAllProjects() {
  filters.projectIds = filters.projects.map(p => String(p.id))
  projectChanged()
}
function clearProjects() {
  filters.projectIds = []
  projectChanged()
}
function openModulePicker() {
  moduleQuery.value = ''
  modulePickerOpen.value = true
}
function closeModulePicker() {
  modulePickerOpen.value = false
}
function selectAllModules() {
  filters.moduleIds = filters.modules.map(m => String(m.id))
  loadDashboardData()
}
function clearModules() {
  filters.moduleIds = []
  loadDashboardData()
}
function onPickerClick(event) {
  const inProject = projectPickerEl.value?.contains(event.target) ?? false
  const inModule = modulePickerEl.value?.contains(event.target) ?? false
  if (!inProject && !inModule) {
    closeProjectPicker()
    closeModulePicker()
  }
}
onMounted(() => document.addEventListener('pointerdown', onPickerClick))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onPickerClick))


async function projectChanged() {
  filters.moduleIds = []
  filters.versionIds = []
  filters.versionFilterApplied = false
  await Promise.all([loadModules(), loadVersions()])
  await loadDashboardData()
}
async function toggle(key, id) {
  const value = String(id)
  const list = filters[key]
  filters[key] = list.includes(value) ? list.filter(item => item !== value) : [...list, value]
  if (key === 'versionIds') filters.versionFilterApplied = false
  if (key === 'projectIds') {
    await Promise.all([loadModules(), loadVersions()])
  }
  loadDashboardData()
}
function resetFilters() {
  filters.reset()
  dirPrefixDraft.value = ''
  projectChanged()
}
</script>

<template>
  <section class="filter-bar" aria-label="Dashboard filters">
    <div ref="projectPickerEl" class="chip-filter module-picker">
      <label
        ><span>Project</span
        ><button type="button" class="module-picker-trigger" @click="openProjectPicker">
          <template v-if="selectedProjectCount">已选 {{ selectedProjectCount }} 个项目</template>
          <template v-else>选择项目</template>
          <span class="module-picker-caret">▾</span>
        </button></label
      >
      <div v-if="projectPickerOpen" class="module-picker-panel">
        <div class="module-picker-actions">
          <input v-model="projectQuery" type="search" placeholder="搜索项目" />
          <button type="button" class="btn btn-xs btn-default" @click="selectAllProjects">
            全选
          </button>
          <button type="button" class="btn btn-xs btn-default" @click="clearProjects">清空</button>
        </div>
        <div class="chips module-chips" role="group" aria-label="Project filters">
          <button
            v-for="project in visibleProjects"
            :key="project.id"
            type="button"
            :aria-pressed="filters.projectIds.includes(String(project.id))"
            @click="toggle('projectIds', project.id)"
          >
            {{ project.name }}
          </button>
          <span v-if="!visibleProjects.length">无匹配项目</span>
        </div>
        <div class="module-picker-foot">
          <span>{{ selectedProjectCount }} / {{ filters.projects.length }} 已选</span>
          <button type="button" class="btn btn-xs" @click="closeProjectPicker">完成</button>
        </div>
      </div>
    </div>
    <div ref="modulePickerEl" class="chip-filter module-picker">
      <label
        ><span>Global modules</span
        ><button type="button" class="module-picker-trigger" @click="openModulePicker">
          <template v-if="selectedModuleCount">已选 {{ selectedModuleCount }} 个模块</template>
          <template v-else>选择模块</template>
          <span class="module-picker-caret">▾</span>
        </button></label
      >
      <div v-if="modulePickerOpen" class="module-picker-panel">
        <div class="module-picker-actions">
          <input v-model="moduleQuery" type="search" placeholder="搜索模块" />
          <button type="button" class="btn btn-xs btn-default" @click="selectAllModules">
            全选
          </button>
          <button type="button" class="btn btn-xs btn-default" @click="clearModules">清空</button>
        </div>
        <div class="chips module-chips" role="group" aria-label="Global module filters">
          <button
            v-for="module in visibleModules"
            :key="module.id"
            type="button"
            :aria-pressed="filters.moduleIds.includes(String(module.id))"
            @click="toggle('moduleIds', module.id)"
          >
            {{ module.name }}
          </button>
          <span v-if="!visibleModules.length">无匹配模块</span>
        </div>
        <div class="module-picker-foot">
          <span>{{ selectedModuleCount }} / {{ filters.modules.length }} 已选</span>
          <button type="button" class="btn btn-xs" @click="closeModulePicker">完成</button>
        </div>
      </div>
    </div>
    <div class="chip-filter">
      <label
        ><span>Path-derived versions</span
        ><input
          v-model="versionQuery"
          type="search"
          placeholder="如 regr_* 或 *w1_demo*（支持 * 通配符）"
          @keyup.enter="applyFilters"
      /></label>
      <div class="chips" role="group" aria-label="Version filters">
        <button
          v-for="version in visibleVersions"
          :key="version"
          type="button"
          :aria-pressed="filters.versionIds.includes(String(version))"
          @click="toggle('versionIds', version)"
        >
          {{ version }}
        </button>
        <span v-if="filters.projectIds.length && !visibleVersions.length">No path-derived versions</span>
      </div>
    </div>
    <label class="path-filter"
      ><span>Directory prefix</span>
      <input
        v-model="dirPrefixDraft"
        type="text"
        name="qor-directory-prefix"
        autocomplete="off"
        placeholder="/workspace/regr_…/main"
        @keyup.enter="applyFilters"
      />
    </label>
    <button class="btn btn-sm" type="button" @click="applyFilters">Apply</button>
    <button class="btn btn-sm btn-default" type="button" @click="resetFilters">Reset</button>
  </section>
</template>

<style scoped>
.filter-bar {
  display: grid;
  grid-template-columns: 190px minmax(230px, 1fr) minmax(230px, 1fr) minmax(210px, 1fr) auto auto;
  align-items: end;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
label span {
  display: block;
  margin-bottom: 3px;
  color: var(--color-text-secondary);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
select,
input {
  width: 100%;
  min-height: 31px;
  font-size: 11px;
  font-family: inherit;
}
.chip-filter {
  min-width: 0;
}
.module-picker {
  position: relative;
}
.module-picker-trigger {
  width: 100%;
  min-height: 31px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-background);
  color: var(--color-text);
  font-size: 12px;
  cursor: pointer;
  text-align: left;
}
.module-picker-trigger:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-hover);
}
.module-picker-caret {
  color: var(--color-text-secondary);
  font-size: 10px;
}
.module-picker-panel {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 50;
  width: 340px;
  max-width: calc(100vw - 24px);
  padding: 8px;
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: var(--color-surface);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
}
.module-picker-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.module-picker-actions input {
  flex: 1;
  min-width: 0;
}
.module-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-height: 260px;
  overflow: auto;
  padding: 4px 2px 2px;
}
.module-picker-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--color-border);
}
.module-picker-foot span {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.chip-filter label {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 6px;
}
.chip-filter label span {
  margin: 0;
  white-space: nowrap;
}
.chips {
  display: flex;
  gap: 3px;
  overflow: auto;
  min-height: 27px;
  padding-top: 3px;
}
.chips button {
  flex: none;
  padding: 2px 7px;
  border: 1px solid var(--color-border);
  background: var(--color-background);
  color: var(--color-text-secondary);
  font-size: 10px;
}
.chips button[aria-pressed='true'] {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-surface-hover);
}
.chips span {
  padding: 4px;
  color: var(--color-text-secondary);
  font-size: 10px;
}
@media (max-width: 1100px) {
  .filter-bar {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
