<script setup>
import { useFiltersStore } from '@/stores/filters'
import { useDashboardStore } from '@/stores/dashboard'
import { useDashboardData } from '@/composables/useDashboardData'

const filters = useFiltersStore()
const dashboard = useDashboardStore()
const { loadProjects, loadModules, loadVersions, loadDashboardData } = useDashboardData()

function handleProjectChange() {
  filters.moduleIds = []
  loadModules()
  loadVersions()
  loadDashboardData()
}

function handleModuleSelectAll() {
  filters.moduleIds = filters.modules.map(m => m.id)
  loadDashboardData()
}

function handleModuleClear() {
  filters.moduleIds = []
  loadDashboardData()
}

function handleVersionSelectAll() {
  filters.versionIds = filters.versions.map(v => v.id || v)
  loadDashboardData()
}

function handleVersionClear() {
  filters.versionIds = []
  loadDashboardData()
}
</script>

<template>
  <div class="filter-bar card">
    <div class="filter-group">
      <label>项目</label>
      <select v-model="filters.projectId" @change="handleProjectChange">
        <option value="">全部项目</option>
        <option
          v-for="p in filters.projects"
          :key="p.id"
          :value="p.id"
        >
          {{ p.name }}
        </option>
      </select>
    </div>
    <div class="filter-group">
      <label>模块</label>
      <select v-model="filters.moduleIds" multiple @change="loadDashboardData">
        <option
          v-for="m in filters.modules"
          :key="m.id"
          :value="m.id"
        >
          {{ m.name }}
        </option>
      </select>
      <div class="version-actions">
        <button class="btn btn-sm btn-default" @click="handleModuleSelectAll">全选</button>
        <button class="btn btn-sm btn-default" @click="handleModuleClear">清空</button>
      </div>
    </div>
    <div class="filter-group">
      <label>版本</label>
      <select v-model="filters.versionIds" multiple @change="loadDashboardData">
        <option
          v-for="v in filters.versions"
          :key="v"
          :value="v"
        >
          {{ v }}
        </option>
      </select>
      <div class="version-actions">
        <button class="btn btn-sm btn-default" @click="handleVersionSelectAll">全选</button>
        <button class="btn btn-sm btn-default" @click="handleVersionClear">清空</button>
      </div>
    </div>
    <div class="filter-group">
      <label>目录前缀</label>
      <input
        v-model="filters.dirPrefix"
        type="text"
        placeholder="筛选目录"
        @change="loadDashboardData"
      />
    </div>
  </div>
</template>

<style scoped>
.filter-bar {
  padding: 16px 20px;
  display: flex;
  gap: 16px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.filter-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.filter-group label {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.filter-group select {
  min-width: 160px;
  max-width: 240px;
}
.filter-group select[multiple] {
  height: 100px;
}
.filter-group input {
  min-width: 140px;
}
.version-actions {
  display: flex;
  gap: 4px;
  margin-top: 4px;
}
</style>