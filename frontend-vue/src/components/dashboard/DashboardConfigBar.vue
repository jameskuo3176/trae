<script setup>
import { computed, onMounted, ref } from 'vue'
import { useDashboardConfigsStore } from '@/stores/dashboardConfigs'

const props = defineProps({ modelValue: { type: Object, required: true } })
const emit = defineEmits(['update:modelValue'])
const configs = useDashboardConfigsStore()
const name = ref('')
const makeDefault = ref(false)
const selected = computed(() =>
  configs.configs.find(config => String(config.id) === configs.activeId)
)

async function apply() {
  const detail = await configs.loadConfig()
  const payload = detail?.config || selected.value?.config
  if (payload) emit('update:modelValue', { ...props.modelValue, ...payload })
}
async function save() {
  if (!name.value.trim()) return
  await configs.save(name.value.trim(), props.modelValue, makeDefault.value)
  name.value = ''
}
onMounted(async () => {
  await configs.load()
  if (configs.activeId) await apply()
})
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
