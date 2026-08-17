<script setup>
import { computed, ref, watch } from 'vue'
import { adminApi } from '@/api/admin'

const props = defineProps({
  status: { type: Object, required: true }
})
const emit = defineEmits(['updated'])

const expandedProjects = ref(new Set())
const expandedGroups = ref(new Set())
const editingKey = ref('')
const ownerDrafts = ref({})
const savingKey = ref('')
const rowErrors = ref({})
const rowSuccess = ref({})
const treeInitialized = ref(false)
const selectedProject = ref('')

const canEdit = computed(() => props.status.permissions?.can_edit_module_owner === true)
const ownerOptions = computed(() => props.status.owner_options || [])
const displayedProjects = computed(() =>
  selectedProject.value
    ? (props.status.projects || []).filter(project => project.name === selectedProject.value)
    : props.status.projects || []
)

const projectKey = project => project.name
const groupKey = (project, group) => `${project.name}::${group.name}`
const moduleKey = (project, group, module) =>
  `${project.name}::${group.name}::${module.name}`
const moduleCount = project =>
  (project.groups || []).reduce((count, group) => count + (group.modules?.length || 0), 0)

watch(
  () => props.status.projects,
  projects => {
    if (
      selectedProject.value &&
      !(projects || []).some(project => project.name === selectedProject.value)
    ) {
      selectedProject.value = ''
    }
    if (!treeInitialized.value) {
      const nextProjects = new Set()
      const nextGroups = new Set()
      for (const project of projects || []) {
        nextProjects.add(projectKey(project))
        for (const group of project.groups || []) {
          nextGroups.add(groupKey(project, group))
        }
      }
      expandedProjects.value = nextProjects
      expandedGroups.value = nextGroups
      treeInitialized.value = true
    }
  },
  { immediate: true }
)

function toggleProject(project) {
  const next = new Set(expandedProjects.value)
  const key = projectKey(project)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedProjects.value = next
}

function toggleGroup(project, group) {
  const next = new Set(expandedGroups.value)
  const key = groupKey(project, group)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedGroups.value = next
}

function startEdit(project, group, module) {
  if (!canEdit.value) return
  const key = moduleKey(project, group, module)
  editingKey.value = key
  rowErrors.value = { ...rowErrors.value, [key]: '' }
  rowSuccess.value = { ...rowSuccess.value, [key]: '' }
  const currentOwner = ownerOptions.value.find(owner => owner.username === module.release_owner)
  ownerDrafts.value = {
    ...ownerDrafts.value,
    [key]: currentOwner ? String(currentOwner.id) : ''
  }
}

function cancelEdit() {
  if (savingKey.value) return
  editingKey.value = ''
}

async function saveOwner(project, group, module) {
  const key = moduleKey(project, group, module)
  const ownerId = Number(ownerDrafts.value[key])
  if (!ownerId || savingKey.value) return
  savingKey.value = key
  rowErrors.value = { ...rowErrors.value, [key]: '' }
  rowSuccess.value = { ...rowSuccess.value, [key]: '' }
  try {
    const response = await adminApi.updateReviewHierarchyModuleOwner({
      project: project.name,
      group: group.name,
      module: module.name,
      owner_id: ownerId,
      config_checksum: props.status.config_checksum
    })
    editingKey.value = ''
    rowSuccess.value = {
      ...rowSuccess.value,
      [key]: `已更新为 ${response.updated.release_owner}`
    }
    emit('updated', response.status)
  } catch (error) {
    rowErrors.value = {
      ...rowErrors.value,
      [key]:
        error.response?.data?.error ||
        error.response?.data?.detail ||
        error.message ||
        'Owner 更新失败'
    }
  } finally {
    savingKey.value = ''
  }
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}
</script>

<template>
  <section class="hierarchy-console" aria-labelledby="hierarchy-title">
    <header class="hierarchy-console__header">
      <div>
        <span class="hierarchy-kicker">REVIEW CONTROL PLANE</span>
        <h2 id="hierarchy-title">评审层级同步状态</h2>
        <p>Project → Group → Module → Release Owner</p>
      </div>
      <div class="hierarchy-state">
        <span
          :class="['status-badge', status.validation.valid ? 'is-valid' : 'is-invalid']"
        >
          {{ status.validation.valid ? '配置有效' : '配置无效' }}
        </span>
        <span
          v-if="status.current_db_diff"
          :class="['status-badge', status.current_db_diff.in_sync ? 'is-sync' : 'is-pending']"
        >
          {{
            status.current_db_diff.in_sync
              ? 'DB 已同步'
              : `${status.current_db_diff.total_changes} 项待同步`
          }}
        </span>
        <span v-if="status.excluded_projects?.length" class="status-badge is-excluded">
          已排除 {{ status.excluded_projects.length }} 个离线项目
        </span>
      </div>
    </header>

    <dl class="sync-diagnostics">
      <div class="diagnostic-wide">
        <dt>配置路径</dt>
        <dd :title="status.config_path">{{ status.config_path }}</dd>
      </div>
      <div>
        <dt>当前版本</dt>
        <dd>{{ status.config_version || '-' }}</dd>
      </div>
      <div>
        <dt>配置校验和</dt>
        <dd class="checksum" :title="status.config_checksum">
          {{ status.config_checksum || '-' }}
        </dd>
      </div>
      <div>
        <dt>最后应用</dt>
        <dd>
          {{
            status.last_applied
              ? `${status.last_applied.config_version} · ${formatDateTime(
                  status.last_applied.applied_at
                )}`
              : '尚未应用'
          }}
        </dd>
      </div>
      <div>
        <dt>最后应用变更</dt>
        <dd>
          {{
            status.last_applied?.summary
              ? `${status.last_applied.summary.total_changes} 项`
              : '-'
          }}
        </dd>
      </div>
    </dl>

    <ul v-if="status.validation.errors.length" class="validation-errors" role="alert">
      <li v-for="message in status.validation.errors" :key="message">{{ message }}</li>
    </ul>

    <p v-if="!canEdit" class="read-only-note">
      当前为只读视图。只有管理员可以修改 Release Owner 并写回 YAML。
    </p>

    <div v-if="status.projects.length" class="tree-toolbar">
      <label for="hierarchy-project-filter">筛选 Project</label>
      <select id="hierarchy-project-filter" v-model="selectedProject">
        <option value="">全部项目</option>
        <option v-for="project in status.projects" :key="project.name" :value="project.name">
          {{ project.name }}{{ project.status === 'locked' ? '（已锁定）' : '' }}
        </option>
      </select>
      <span aria-live="polite">
        显示 {{ displayedProjects.length }} / {{ status.projects.length }} 个项目
      </span>
    </div>

    <div v-if="status.projects.length" class="hierarchy-tree" role="tree" aria-label="评审层级">
      <section
        v-for="project in displayedProjects"
        :key="project.name"
        class="project-node"
        role="treeitem"
        :aria-expanded="expandedProjects.has(projectKey(project))"
      >
        <button
          class="tree-toggle project-toggle"
          type="button"
          :aria-expanded="expandedProjects.has(projectKey(project))"
          :aria-controls="`project-${projectKey(project)}`"
          @click="toggleProject(project)"
        >
          <span class="chevron" aria-hidden="true">›</span>
          <span class="node-mark project-mark" aria-hidden="true">P</span>
          <span class="node-main">
            <strong>{{ project.name }}</strong>
            <small>Project Owner · {{ project.owner }}</small>
          </span>
          <span class="node-count">{{ project.groups.length }} Groups</span>
          <span class="node-count">{{ moduleCount(project) }} Modules</span>
          <span v-if="project.status === 'locked'" class="node-count is-locked">已锁定</span>
        </button>

        <div
          v-show="expandedProjects.has(projectKey(project))"
          :id="`project-${projectKey(project)}`"
          class="project-children"
          role="group"
        >
          <details class="threshold-details">
            <summary>Effective thresholds</summary>
            <div>
              <span
                v-for="(levels, metric) in project.effective_thresholds"
                :key="metric"
              >
                <b>{{ metric }}</b>
                medium {{ levels.medium_percent }}% · high {{ levels.high_percent }}%
              </span>
            </div>
          </details>

          <section
            v-for="group in project.groups"
            :key="group.name"
            class="group-node"
            role="treeitem"
            :aria-expanded="expandedGroups.has(groupKey(project, group))"
          >
            <button
              class="tree-toggle group-toggle"
              type="button"
              :aria-expanded="expandedGroups.has(groupKey(project, group))"
              :aria-controls="`group-${groupKey(project, group)}`"
              @click="toggleGroup(project, group)"
            >
              <span class="chevron" aria-hidden="true">›</span>
              <span class="node-mark group-mark" aria-hidden="true">G</span>
              <span class="node-main">
                <strong>{{ group.name }}</strong>
                <small>Group Owner · {{ group.owner }}</small>
              </span>
              <span class="node-count">{{ group.modules.length }} Modules</span>
            </button>

            <div
              v-show="expandedGroups.has(groupKey(project, group))"
              :id="`group-${groupKey(project, group)}`"
              class="module-list"
              role="group"
            >
              <article
                v-for="module in group.modules"
                :key="module.name"
                class="module-node"
                role="treeitem"
              >
                <span class="module-rail" aria-hidden="true"></span>
                <span class="node-mark module-mark" aria-hidden="true">M</span>
                <span class="module-name">{{ module.name }}</span>
                <span class="owner-label">Release Owner</span>

                <form
                  v-if="editingKey === moduleKey(project, group, module)"
                  class="owner-editor"
                  @submit.prevent="saveOwner(project, group, module)"
                >
                  <label :for="`owner-${moduleKey(project, group, module)}`">
                    新 Owner
                  </label>
                  <select
                    :id="`owner-${moduleKey(project, group, module)}`"
                    v-model="ownerDrafts[moduleKey(project, group, module)]"
                    :disabled="savingKey === moduleKey(project, group, module)"
                    required
                  >
                    <option value="" disabled>选择 Owner</option>
                    <option v-for="owner in ownerOptions" :key="owner.id" :value="String(owner.id)">
                      {{ owner.display_name }} ({{ owner.username }})
                    </option>
                  </select>
                  <button
                    class="owner-save"
                    type="submit"
                    :disabled="
                      !ownerDrafts[moduleKey(project, group, module)] ||
                      savingKey === moduleKey(project, group, module)
                    "
                  >
                    {{
                      savingKey === moduleKey(project, group, module) ? '保存中…' : '保存'
                    }}
                  </button>
                  <button
                    class="owner-cancel"
                    type="button"
                    :disabled="savingKey === moduleKey(project, group, module)"
                    @click="cancelEdit"
                  >
                    取消
                  </button>
                </form>
                <div v-else class="owner-display">
                  <strong>{{ module.release_owner }}</strong>
                  <button
                    v-if="canEdit"
                    class="owner-edit"
                    type="button"
                    :aria-label="`修改 ${project.name} / ${group.name} / ${module.name} 的 Release Owner`"
                    @click="startEdit(project, group, module)"
                  >
                    修改
                  </button>
                  <span v-else class="read-only-tag">只读</span>
                </div>
                <p
                  v-if="rowErrors[moduleKey(project, group, module)]"
                  class="row-message is-error"
                  role="alert"
                >
                  {{ rowErrors[moduleKey(project, group, module)] }}
                </p>
                <p
                  v-if="rowSuccess[moduleKey(project, group, module)]"
                  class="row-message is-success"
                  role="status"
                >
                  {{ rowSuccess[moduleKey(project, group, module)] }}
                </p>
              </article>
            </div>
          </section>
        </div>
      </section>
    </div>
    <p v-else class="hierarchy-empty">没有可显示的有效评审层级。</p>
  </section>
</template>

<style scoped>
.hierarchy-console {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-top: 4px solid var(--color-primary);
  border-radius: 5px;
  background: var(--color-surface);
  color: var(--color-text);
}
.hierarchy-console__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 20px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-elevated);
}
.hierarchy-kicker {
  color: var(--color-primary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
}
.hierarchy-console h2 {
  margin: 4px 0 2px;
  font-size: 20px;
}
.hierarchy-console__header p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.hierarchy-state {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}
.status-badge,
.node-count,
.read-only-tag {
  padding: 3px 7px;
  border: 1px solid var(--color-border);
  border-radius: 3px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
.status-badge.is-valid,
.status-badge.is-sync {
  border-color: var(--color-success-border);
  background: var(--color-success-background);
  color: var(--color-success);
}
.status-badge.is-invalid {
  border-color: var(--color-danger-border);
  background: var(--color-danger-background);
  color: var(--color-danger);
}
.status-badge.is-pending {
  border-color: var(--color-warning-border);
  background: var(--color-warning-background);
  color: var(--color-warning);
}
.status-badge.is-excluded {
  background: var(--color-disabled-background);
  color: var(--color-disabled-text);
}
.sync-diagnostics {
  display: grid;
  grid-template-columns: minmax(220px, 1.6fr) repeat(4, minmax(125px, 0.75fr));
  margin: 0;
  border-bottom: 1px solid var(--color-border);
}
.sync-diagnostics > div {
  min-width: 0;
  padding: 12px 14px;
  border-right: 1px solid var(--color-border);
}
.sync-diagnostics > div:last-child {
  border-right: 0;
}
.sync-diagnostics dt {
  color: var(--color-text-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.sync-diagnostics dd {
  margin: 5px 0 0;
  overflow: hidden;
  color: var(--color-text);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.checksum {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.validation-errors,
.read-only-note {
  margin: 14px 18px 0;
  padding: 10px 12px;
  border: 1px solid var(--color-danger-border);
  background: var(--color-danger-background);
  color: var(--color-danger);
  font-size: 12px;
}
.read-only-note {
  border-color: var(--color-info-border);
  background: var(--color-info-background);
  color: var(--color-info);
}
.tree-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px 0;
}
.tree-toolbar label {
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 700;
}
.tree-toolbar select {
  width: min(320px, 100%);
}
.tree-toolbar span {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: 11px;
}
.hierarchy-tree {
  display: grid;
  gap: 12px;
  padding: 18px;
}
.project-node {
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-radius: 4px;
}
.tree-toggle {
  display: grid;
  grid-template-columns: 18px 28px minmax(180px, 1fr) auto auto auto;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 11px 13px;
  border: 0;
  background: var(--color-surface-elevated);
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
}
.tree-toggle:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.tree-toggle:focus-visible,
.owner-edit:focus-visible,
.owner-save:focus-visible,
.owner-cancel:focus-visible {
  outline: 2px solid var(--color-focus-ring);
  outline-offset: -2px;
}
.chevron {
  color: var(--color-primary);
  font-size: 22px;
  line-height: 1;
  transition: transform 0.16s ease;
}
.tree-toggle[aria-expanded='true'] .chevron {
  transform: rotate(90deg);
}
.node-mark {
  display: inline-grid;
  place-items: center;
  width: 25px;
  height: 25px;
  border: 1px solid currentColor;
  border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  font-weight: 900;
}
.project-mark {
  background: var(--color-surface-selected);
  color: var(--color-primary);
}
.group-mark {
  background: var(--color-info-background);
  color: var(--color-info);
}
.module-mark {
  background: var(--color-success-background);
  color: var(--color-success);
}
.node-main {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.node-main strong,
.module-name {
  overflow-wrap: anywhere;
}
.node-main small {
  color: var(--color-text-secondary);
  font-size: 11px;
}
.node-count {
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
.node-count.is-locked {
  border-color: var(--color-warning-border);
  background: var(--color-warning-background);
  color: var(--color-warning);
}
.project-children {
  padding: 0 12px 12px 38px;
  background: var(--color-surface);
}
.threshold-details {
  margin: 10px 0;
  color: var(--color-text-secondary);
  font-size: 11px;
}
.threshold-details summary {
  width: max-content;
  cursor: pointer;
}
.threshold-details div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  padding: 8px 0 2px;
}
.threshold-details span {
  padding-right: 12px;
  border-right: 1px solid var(--color-border);
}
.group-node {
  position: relative;
  margin-top: 8px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
}
.group-node::before {
  position: absolute;
  top: 21px;
  right: 100%;
  width: 27px;
  border-top: 1px solid var(--color-border-strong);
  content: '';
}
.group-toggle {
  grid-template-columns: 18px 28px minmax(160px, 1fr) auto;
  background: var(--color-surface);
}
.module-list {
  padding: 0 12px 10px 50px;
}
.module-node {
  position: relative;
  display: grid;
  grid-template-columns: 28px minmax(160px, 1fr) 110px minmax(220px, auto);
  align-items: center;
  gap: 10px;
  min-height: 48px;
  padding: 7px 0;
  border-top: 1px solid var(--color-border);
}
.module-rail {
  position: absolute;
  top: -1px;
  right: 100%;
  width: 38px;
  height: calc(50% + 1px);
  border-bottom: 1px solid var(--color-border);
  border-left: 1px solid var(--color-border);
}
.module-name {
  font-size: 13px;
  font-weight: 700;
}
.owner-label {
  color: var(--color-text-muted);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.owner-display,
.owner-editor {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  min-width: 0;
}
.owner-display strong {
  color: var(--color-success);
  overflow-wrap: anywhere;
}
.owner-editor label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
}
.owner-editor select {
  min-width: 170px;
  max-width: 260px;
}
.owner-edit,
.owner-save,
.owner-cancel {
  padding: 5px 8px;
  border: 1px solid var(--color-border-strong);
  border-radius: 3px;
  background: var(--color-surface);
  color: var(--color-text);
  font-size: 11px;
  cursor: pointer;
}
.owner-edit:hover,
.owner-cancel:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.owner-save {
  border-color: var(--color-success-border);
  background: var(--color-success-background);
  color: var(--color-success);
  font-weight: 800;
}
.owner-save:disabled,
.owner-cancel:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.read-only-tag {
  color: var(--color-text-muted);
  font-weight: 500;
}
.row-message {
  grid-column: 2 / -1;
  margin: -2px 0 4px;
  font-size: 11px;
  text-align: right;
}
.row-message.is-error {
  color: var(--color-danger);
}
.row-message.is-success {
  color: var(--color-success);
}
.hierarchy-empty {
  padding: 30px;
  color: var(--color-text-secondary);
  text-align: center;
}
@media (max-width: 900px) {
  .sync-diagnostics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sync-diagnostics > div {
    border-bottom: 1px solid var(--color-border);
  }
  .diagnostic-wide {
    grid-column: 1 / -1;
  }
  .module-node {
    grid-template-columns: 28px minmax(120px, 1fr) minmax(190px, auto);
  }
  .owner-label {
    display: none;
  }
}
@media (max-width: 620px) {
  .hierarchy-console__header {
    align-items: stretch;
    flex-direction: column;
  }
  .hierarchy-state {
    justify-content: flex-start;
  }
  .sync-diagnostics {
    grid-template-columns: 1fr;
  }
  .tree-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .tree-toolbar select {
    width: 100%;
  }
  .tree-toolbar span {
    margin-left: 0;
  }
  .diagnostic-wide {
    grid-column: auto;
  }
  .tree-toggle {
    grid-template-columns: 18px 26px minmax(0, 1fr);
  }
  .tree-toggle .node-count {
    grid-column: 3;
    width: max-content;
  }
  .project-children {
    padding-left: 18px;
  }
  .module-list {
    padding-left: 24px;
  }
  .module-node {
    grid-template-columns: 26px minmax(0, 1fr);
    padding: 10px 0;
  }
  .owner-display,
  .owner-editor {
    grid-column: 2;
    align-items: stretch;
    justify-content: flex-start;
    flex-wrap: wrap;
  }
  .owner-editor select {
    flex: 1 1 100%;
    max-width: none;
  }
  .row-message {
    grid-column: 2;
    text-align: left;
  }
}
@media (prefers-reduced-motion: reduce) {
  .chevron {
    transition: none;
  }
}
</style>
