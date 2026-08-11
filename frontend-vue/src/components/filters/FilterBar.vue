<script setup>
import { computed, ref } from 'vue'
import { useFiltersStore } from '@/stores/filters'
import { useDashboardData } from '@/composables/useDashboardData'

const filters = useFiltersStore()
const { loadModules, loadVersions, loadDashboardData } = useDashboardData()
const moduleQuery = ref('')
const versionQuery = ref('')
const visibleModules = computed(() =>
  filters.modules.filter(item => item.name.toLowerCase().includes(moduleQuery.value.toLowerCase()))
)
const visibleVersions = computed(() =>
  filters.versions.filter(item =>
    String(item).toLowerCase().includes(versionQuery.value.toLowerCase())
  )
)

async function projectChanged() {
  filters.moduleIds = []
  filters.versionIds = []
  await Promise.all([loadModules(), loadVersions()])
  loadDashboardData()
}
function toggle(key, id) {
  const value = String(id)
  const list = filters[key]
  filters[key] = list.includes(value) ? list.filter(item => item !== value) : [...list, value]
  loadDashboardData()
}
function resetFilters() {
  filters.reset()
  projectChanged()
}
</script>

<template>
  <section class="filter-bar" aria-label="Dashboard filters">
    <label class="project-filter"
      ><span>Project</span>
      <select v-model="filters.projectId" @change="projectChanged">
        <option value="">All projects · compatibility view</option>
        <option v-for="project in filters.projects" :key="project.id" :value="project.id">
          {{ project.name }}
        </option>
      </select>
    </label>
    <div class="chip-filter">
      <label
        ><span>Global modules</span
        ><input v-model="moduleQuery" type="search" placeholder="Search modules"
      /></label>
      <div class="chips" role="group" aria-label="Global module filters">
        <button
          v-for="module in visibleModules"
          :key="module.id"
          type="button"
          :aria-pressed="filters.moduleIds.includes(String(module.id))"
          @click="toggle('moduleIds', module.id)"
        >
          {{ module.name }}
        </button>
        <span v-if="filters.projectId && !visibleModules.length">No modules</span>
      </div>
    </div>
    <div class="chip-filter">
      <label
        ><span>Path-derived versions</span
        ><input v-model="versionQuery" type="search" placeholder="Search regr_*"
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
        <span v-if="filters.projectId && !visibleVersions.length">No path-derived versions</span>
      </div>
    </div>
    <label class="path-filter"
      ><span>Directory prefix</span>
      <input
        v-model.trim="filters.dirPrefix"
        type="text"
        placeholder="/workspace/regr_…/main"
        @keyup.enter="loadDashboardData"
      />
    </label>
    <button class="btn btn-sm" type="button" @click="loadDashboardData">Apply</button>
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
