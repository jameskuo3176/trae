<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useDcComparisonStore } from '@/stores/dcComparison'

const props = defineProps({
  records: { type: Array, default: () => [] },
  sections: { type: Array, default: () => [] },
  timingScenarios: { type: Array, default: () => [] },
  timingPathGroups: { type: Array, default: () => [] }
})
const dc = useDcComparisonStore()
const dialog = ref(null)
let returnFocus = null
const sectionMetrics = computed(() =>
  props.sections.map(section => ({
    ...section,
    items: section.metrics.map(metric => {
      const id = typeof metric === 'object' ? metric.id : metric
      const label = typeof metric === 'object' ? metric.label : metric.replaceAll('_', ' ')
      return { id: `${section.id}.${id}`, label, section: section.label }
    })
  }))
)
const metrics = computed(() => sectionMetrics.value.flatMap(section => section.items))
const recordKey = record => String(record.__selectionKey ?? record.id)

function setAll(key, values, checked) {
  dc.draft[key] = checked ? values : []
}

function setSectionMetrics(section, checked) {
  const sectionIds = new Set(section.items.map(metric => metric.id))
  const retained = dc.draft.metricIds.filter(id => !sectionIds.has(id))
  dc.draft.metricIds = checked ? [...retained, ...sectionIds] : retained
}

function closeOnEscape(event) {
  if (event.key === 'Escape') dc.cancel()
  if (event.key !== 'Tab' || !dialog.value) return
  const focusable = [...dialog.value.querySelectorAll('button,input,select')].filter(
    el => !el.disabled
  )
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(
  () => dc.pickerOpen,
  async open => {
    if (open) {
      returnFocus = document.activeElement
      await nextTick()
      dialog.value?.querySelector('input,button')?.focus()
      document.addEventListener('keydown', closeOnEscape)
    } else {
      document.removeEventListener('keydown', closeOnEscape)
      returnFocus?.focus?.()
    }
  }
)
onBeforeUnmount(() => document.removeEventListener('keydown', closeOnEscape))
</script>

<template>
  <div
    v-if="dc.pickerOpen && dc.draft"
    class="picker-mask"
    role="presentation"
    @mousedown.self="dc.cancel"
  >
    <section
      ref="dialog"
      class="picker"
      role="dialog"
      aria-modal="true"
      aria-labelledby="picker-title"
    >
      <header>
        <div>
          <h2 id="picker-title">DC Comparison Picker</h2>
          <p>Draft selections apply only when confirmed.</p>
        </div>
        <button class="icon-button" type="button" aria-label="Cancel and close" @click="dc.cancel">
          ×
        </button>
      </header>
      <div class="picker-grid">
        <fieldset>
          <legend>
            Runs <b>{{ dc.draft.runIds.length }} / {{ records.length }}</b>
          </legend>
          <div class="mini-actions">
            <button type="button" @click="setAll('runIds', records.map(recordKey), true)">
              All
            </button>
            <button type="button" @click="setAll('runIds', [], false)">None</button>
          </div>
          <label v-for="record in records" :key="recordKey(record)">
            <input v-model="dc.draft.runIds" type="checkbox" :value="recordKey(record)" />
            <span>{{ record.module_name }} · {{ record.version }}</span>
          </label>
        </fieldset>
        <fieldset>
          <legend>Sections</legend>
          <div class="mini-actions">
            <button
              type="button"
              @click="
                setAll(
                  'sectionIds',
                  sections.map(s => s.id),
                  true
                )
              "
            >
              All
            </button>
            <button type="button" @click="setAll('sectionIds', [], false)">None</button>
          </div>
          <label v-for="section in sections" :key="section.id">
            <input v-model="dc.draft.sectionIds" type="checkbox" :value="section.id" />
            <span>{{ section.label }}</span>
          </label>
        </fieldset>
        <fieldset>
          <legend>Metrics</legend>
          <div class="mini-actions">
            <button
              type="button"
              @click="
                setAll(
                  'metricIds',
                  metrics.map(m => m.id),
                  true
                )
              "
            >
              All
            </button>
            <button type="button" @click="setAll('metricIds', [], false)">None</button>
          </div>
          <section v-for="section in sectionMetrics" :key="section.id" class="metric-group">
            <div class="metric-group-heading">
              <strong>{{ section.label }}</strong>
              <span>
                <button type="button" @click="setSectionMetrics(section, true)">All</button>
                <button type="button" @click="setSectionMetrics(section, false)">None</button>
              </span>
            </div>
            <label v-for="metric in section.items" :key="metric.id">
              <input v-model="dc.draft.metricIds" type="checkbox" :value="metric.id" />
              <span>{{ metric.label }}</span>
            </label>
          </section>
        </fieldset>
        <fieldset>
          <legend>Timing scope</legend>
          <div class="metric-group-heading">
            <strong>Scenario</strong>
            <span>
              <button type="button" @click="setAll('scenarioIds', timingScenarios, true)">
                All
              </button>
              <button type="button" @click="setAll('scenarioIds', [], false)">Any</button>
            </span>
          </div>
          <label v-for="scenario in timingScenarios" :key="scenario">
            <input v-model="dc.draft.scenarioIds" type="checkbox" :value="scenario" />
            <span>{{ scenario }}</span>
          </label>
          <div class="metric-group-heading timing-path-heading">
            <strong>Path group</strong>
            <span>
              <button type="button" @click="setAll('pathGroupIds', timingPathGroups, true)">
                All
              </button>
              <button type="button" @click="setAll('pathGroupIds', [], false)">Any</button>
            </span>
          </div>
          <label v-for="pathGroup in timingPathGroups" :key="pathGroup">
            <input v-model="dc.draft.pathGroupIds" type="checkbox" :value="pathGroup" />
            <span>{{ pathGroup }}</span>
          </label>
          <small>Any 表示不限制；同时控制 WNS/TNS 聚合范围。</small>
        </fieldset>
        <fieldset>
          <legend>Display options</legend>
          <label
            ><input v-model="dc.draft.showChange" type="checkbox" /> Baseline-aware changes</label
          >
          <label><input v-model="dc.draft.compactTiming" type="checkbox" /> Compact timing</label>
          <label
            ><input v-model="dc.draft.copyOnClick" type="checkbox" /> Click cells to copy</label
          >
          <label><input v-model="dc.draft.pathLinks" type="checkbox" /> Safe gvim:// links</label>
          <label><input v-model="dc.draft.vsMode" type="checkbox" /> VS draft-selection mode</label>
        </fieldset>
      </div>
      <footer>
        <div class="sort-selector" role="group" aria-label="Timing sort metric">
          <span>Sort timing by</span>
          <button
            v-for="metric in ['WNS', 'TNS', 'NVP']"
            :key="metric"
            type="button"
            :class="{ active: dc.draft.sortMetric === metric }"
            @click="dc.draft.sortMetric = metric"
          >
            {{ metric }}
          </button>
        </div>
        <div>
          <button class="btn btn-sm btn-default" type="button" @click="dc.cancel">Cancel</button>
          <button class="btn btn-sm" type="button" @click="dc.apply">Apply</button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.picker-mask {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: grid;
  place-items: center;
  padding: 16px;
  background: var(--color-overlay);
}
.picker {
  width: min(1240px, 96vw);
  max-height: 92vh;
  overflow: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-primary);
  box-shadow: 0 18px 52px var(--color-shadow);
}
header,
footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
}
header h2 {
  font-size: 15px;
}
header p {
  font-size: 11px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}
.icon-button {
  border: 0;
  background: none;
  color: var(--color-text);
  font-size: 24px;
}
.picker-grid {
  display: grid;
  grid-template-columns: 1.2fr 0.9fr 1.3fr 1fr 0.9fr;
  gap: 8px;
  padding: 8px;
}
.timing-path-heading {
  margin-top: 12px;
}
fieldset small {
  display: block;
  margin-top: 8px;
  color: var(--color-text-secondary);
  font-size: 10px;
}
fieldset {
  position: relative;
  min-width: 0;
  max-height: 430px;
  overflow: auto;
  border: 1px solid var(--color-border);
  padding: 34px 8px 8px;
}
legend {
  position: absolute;
  top: 8px;
  left: 8px;
  font-size: 12px;
  font-weight: 700;
}
fieldset label {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  padding: 4px;
  font-size: 11px;
  cursor: pointer;
}
fieldset label:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
fieldset label:hover small {
  color: inherit;
}
fieldset small {
  color: var(--color-text-secondary);
}
.mini-actions {
  position: absolute;
  top: 5px;
  right: 6px;
  display: flex;
  gap: 3px;
}
.mini-actions button,
.sort-selector button,
.metric-group-heading button {
  padding: 2px 6px;
  border: 1px solid var(--color-border);
  background: var(--color-background);
  color: var(--color-text);
}
.mini-actions button:hover,
.sort-selector button:hover,
.metric-group-heading button:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-hover);
  color: var(--color-text-on-hover);
}
.metric-group + .metric-group {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
}
.metric-group-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 3px 4px;
  color: var(--color-text);
  font-size: 10px;
}
.metric-group-heading span {
  display: flex;
  gap: 3px;
}
footer {
  border-top: 1px solid var(--color-border);
  border-bottom: 0;
}
footer > div {
  display: flex;
  gap: 6px;
  align-items: center;
}
.sort-selector {
  font-size: 11px;
  color: var(--color-text-secondary);
}
.sort-selector button.active {
  background: var(--color-primary);
  color: var(--color-on-primary);
  border-color: var(--color-primary);
}
@media (max-width: 900px) {
  .picker-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
