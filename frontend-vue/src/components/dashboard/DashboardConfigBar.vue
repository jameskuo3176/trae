<script setup>
import { computed, ref } from 'vue'
import { useDashboardConfigsStore } from '@/stores/dashboardConfigs'
import { useAuthStore } from '@/stores/auth'
import { useDashboardConfigState } from '@/composables/useDashboardConfigState'

const props = defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue', 'applied'])
const configs = useDashboardConfigsStore()
const auth = useAuthStore()
const { snapshot, apply: applyState } = useDashboardConfigState()
const name = ref('')
const makeDefault = ref(false)
const canSave = computed(() => !auth.isViewer)
const selected = computed(() =>
  configs.configs.find(config => String(config.id) === configs.activeId)
)

async function apply() {
  if (!configs.activeId) {
    emit('applied', null)
    return
  }
  const detail = await configs.loadConfig()
  const payload = detail?.config || selected.value?.config
  if (!payload) {
    emit('applied', null)
    return
  }
  // Replace settings (not shallow-merge leftovers) and restore filters/selection.
  const settingsTarget = { ...props.modelValue }
  await applyState(payload, settingsTarget)
  emit('update:modelValue', { ...settingsTarget })
  emit('applied', payload)
}

async function save() {
  if (!name.value.trim()) return
  const payload = snapshot(props.modelValue)
  await configs.save(name.value.trim(), payload, makeDefault.value)
  name.value = ''
}

async function remove() {
  if (!configs.activeId || !canSave.value) return
  const label = selected.value?.name || 'this configuration'
  if (!window.confirm(`Delete saved configuration "${label}"? This cannot be undone.`)) return
  const ok = await configs.remove(configs.activeId)
  if (!ok) return
  await apply()
}

const canDelete = computed(() => canSave.value && Boolean(configs.activeId))

const didApply = ref(false)

/** Parent-driven bootstrap so filters/data load after projects are ready. */
async function bootstrap() {
  didApply.value = false
  await configs.load()
  if (!configs.activeId) return false
  await apply()
  // 404 / missing detail clears activeId — treat as not applied so parent loads defaults.
  didApply.value = Boolean(configs.activeId)
  return didApply.value
}

defineExpose({ bootstrap, didApply, apply })
</script>

<template>
  <section class="config-bar" aria-label="Saved dashboard configurations">
    <strong>Dashboard</strong>
    <select v-model="configs.activeId" aria-label="Saved configuration" @change="apply">
      <option value="">Unsaved configuration</option>
      <option v-for="config in configs.configs" :key="config.id" :value="String(config.id)">
        {{ config.name }}{{ config.is_default ? ' · default' : '' }}
      </option>
    </select>
    <template v-if="canSave">
      <input
        v-model="name"
        type="text"
        placeholder="Configuration name"
        aria-label="Configuration name"
        @keyup.enter="save"
      />
      <label><input v-model="makeDefault" type="checkbox" /> Default</label>
      <button
        class="btn btn-sm"
        type="button"
        :disabled="!name.trim() || configs.loading"
        @click="save"
      >
        Save current
      </button>
      <button
        v-if="canDelete"
        class="btn btn-sm"
        type="button"
        :disabled="configs.loading"
        @click="remove"
      >
        Delete
      </button>
    </template>
    <span v-else class="config-note">Read-only dashboard</span>
    <span v-if="configs.error" class="config-note" role="status">{{ configs.error }}</span>
  </section>
</template>

<style scoped>
.config-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  font-size: 11px;
}
.config-bar strong {
  color: var(--color-primary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.config-bar select {
  min-width: 200px;
}
.config-bar input[type='text'] {
  width: 180px;
}
.config-bar label {
  display: flex;
  gap: 4px;
  align-items: center;
}
.config-note {
  margin-left: auto;
  color: var(--color-text-secondary);
}
@media (max-width: 900px) {
  .config-bar {
    flex-wrap: wrap;
  }
  .config-note {
    width: 100%;
  }
}
</style>
