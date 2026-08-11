<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useDcComparisonStore } from '@/stores/dcComparison'

const props = defineProps({
  records: { type: Array, default: () => [] },
  sections: { type: Array, default: () => [] }
})
const dc = useDcComparisonStore()
const dialog = ref(null)
let returnFocus = null
const metrics = computed(() =>
  props.sections.flatMap(section =>
    section.metrics.map(metric => ({
      id: `${section.id}.${metric}`,
      label: metric,
      section: section.label
    }))
  )
)

function setAll(key, values, checked) {
  dc.draft[key] = checked ? values : []
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
            <button
              type="button"
              @click="
                setAll(
                  'runIds',
                  records.map(r => String(r.id)),
                  true
                )
              "
            >
              All
            </button>
            <button type="button" @click="setAll('runIds', [], false)">None</button>
          </div>
          <label v-for="record in records" :key="record.id">
            <input v-model="dc.draft.runIds" type="checkbox" :value="String(record.id)" />
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
          <label v-for="metric in metrics" :key="metric.id">
            <input v-model="dc.draft.metricIds" type="checkbox" :value="metric.id" />
            <span
              ><small>{{ metric.section }}</small> {{ metric.label }}</span
            >
          </label>
        </fieldset>
        <fieldset>
          <legend>Display options</legend>
          <label
            ><input v-model="dc.draft.showChange" type="checkbox" /> Baseline-aware changes</label
          >
          <label><input v-model="dc.draft.compactTiming" type="checkbox" /> Compact timing</label>
          <label
            ><input v-model="dc.draft.onlyWithRaw" type="checkbox" /> Runs with DC report</label
          >
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
  background: rgba(0, 0, 0, 0.72);
}
.picker {
  width: min(1120px, 96vw);
  max-height: 92vh;
  overflow: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-primary);
  box-shadow: var(--glow-primary);
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
  grid-template-columns: 1.25fr 1fr 1.4fr 1fr;
  gap: 8px;
  padding: 8px;
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
.sort-selector button {
  padding: 2px 6px;
  border: 1px solid var(--color-border);
  background: var(--color-background);
  color: var(--color-text);
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
