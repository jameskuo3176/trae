<script setup>
defineProps({
  orientation: { type: String, default: 'vertical' },
  height: { type: Number, default: 500 },
  labelMode: { type: String, default: 'both' },
  chartType: { type: String, default: 'bar' },
  tableWidth: { type: Number, default: 0 },
  tableFontSize: { type: Number, default: 12 },
  activeView: { type: String, default: 'charts' }
})
defineEmits([
  'update:orientation',
  'update:height',
  'update:labelMode',
  'update:chartType',
  'update:tableWidth',
  'update:tableFontSize',
  'update:activeView'
])
const views = [
  ['charts', 'Charts'],
  ['combined', 'Combined'],
  ['transposed', 'Transposed'],
  ['aggregate', 'Directory aggregate'],
  ['directory-modules', 'Directory modules']
]
</script>
<template>
  <section class="settings-panel" aria-label="Chart and view settings">
    <div class="view-tabs" role="tablist" aria-label="Dashboard view">
      <button
        v-for="[id, label] in views"
        :key="id"
        type="button"
        role="tab"
        :aria-selected="activeView === id"
        @click="$emit('update:activeView', id)"
      >
        {{ label }}
      </button>
    </div>
    <label
      ><span>Orientation</span
      ><select :value="orientation" @change="$emit('update:orientation', $event.target.value)">
        <option value="vertical">Vertical</option>
        <option value="horizontal">Horizontal</option>
      </select></label
    >
    <label
      ><span>Height</span
      ><select :value="height" @change="$emit('update:height', Number($event.target.value))">
        <option v-for="value in [360, 500, 640, 800]" :key="value" :value="value">
          {{ value }} px
        </option>
      </select></label
    >
    <label
      ><span>Labels</span
      ><select :value="labelMode" @change="$emit('update:labelMode', $event.target.value)">
        <option value="both">Module + tag</option>
        <option value="module">Module</option>
        <option value="tag">Tag</option>
        <option value="module_tag_dir">Module + tag + directory</option>
      </select></label
    >
    <label
      ><span>Render</span
      ><select :value="chartType" @change="$emit('update:chartType', $event.target.value)">
        <option value="bar">Bar</option>
        <option value="line">Line</option>
        <option value="table">Table</option>
      </select></label
    >
    <label v-if="chartType === 'table'"
      ><span>Table width</span>
      <input
        type="range"
        min="0"
        max="2400"
        step="50"
        :value="tableWidth"
        @input="$emit('update:tableWidth', Number($event.target.value))"
      />
      <small>{{ tableWidth || 'auto' }}</small></label
    >
    <label
      ><span>Table font</span>
      <input
        type="range"
        min="10"
        max="18"
        step="1"
        aria-label="Table font size"
        :value="tableFontSize"
        @input="$emit('update:tableFontSize', Number($event.target.value))"
      />
      <small>{{ tableFontSize }}px</small></label
    >
  </section>
</template>
<style scoped>
.settings-panel {
  display: flex;
  align-items: end;
  gap: 12px;
  padding: 7px 10px;
  margin-bottom: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.view-tabs {
  display: flex;
  align-self: stretch;
}
.view-tabs button {
  padding: 4px 9px;
  border: 0;
  border-right: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 11px;
}
.view-tabs button[aria-selected='true'] {
  color: var(--color-primary);
  box-shadow: inset 0 -2px var(--color-primary);
}
label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
label span {
  color: var(--color-text-secondary);
  font-size: 9px;
  text-transform: uppercase;
}
select {
  min-width: 100px;
  padding: 4px 6px;
  font-size: 11px;
}
small {
  font-size: 9px;
}
@media (max-width: 1000px) {
  .settings-panel {
    flex-wrap: wrap;
  }
}
</style>
