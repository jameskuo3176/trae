<script setup>
import { computed, ref, toRef } from 'vue'
import { useDialogFocus } from '@/composables/useDialogFocus'

const props = defineProps({
  open: Boolean,
  draft: { type: Object, required: true },
  sections: { type: Array, required: true },
  metrics: { type: Array, required: true },
  timingTypes: { type: Array, required: true },
  pathGroups: { type: Array, required: true }
})
const localDraft = computed(() => props.draft)

const emit = defineEmits(['close', 'apply', 'set-all'])
const closeButton = ref(null)
const { dialogRef, handleDialogKeydown } = useDialogFocus(toRef(props, 'open'), {
  initialFocus: closeButton,
  onEscape: () => emit('close')
})
</script>

<template>
  <div v-if="open" class="display-picker-mask" @mousedown.self="$emit('close')">
    <section
      ref="dialogRef"
      class="display-picker"
      role="dialog"
      aria-modal="true"
      aria-labelledby="display-picker-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
    >
      <header>
        <div>
          <span class="dialog-kicker">MATRIX CONFIGURATION</span>
          <h2 id="display-picker-title">#pick 全局显示配置</h2>
          <p>配置当前评审矩阵 · 草稿仅在 Apply 后生效</p>
        </div>
        <button
          ref="closeButton"
          type="button"
          class="picker-close"
          aria-label="关闭"
          @click="$emit('close')"
        >
          ×
        </button>
      </header>
      <div class="display-picker-grid">
        <fieldset>
          <legend>QoR Sections</legend>
          <div class="picker-mini-actions">
            <button type="button" @click="$emit('set-all', 'sectionIds', sections)">All</button>
            <button type="button" @click="$emit('set-all', 'sectionIds', [])">None</button>
          </div>
          <label v-for="section in sections" :key="section">
            <input v-model="localDraft.sectionIds" type="checkbox" :value="section" />
            <span>{{ section }}</span>
          </label>
          <div class="picker-subsection">
            <strong>Aggregate Metrics</strong>
            <label v-for="metric in metrics" :key="metric.id">
              <input
                v-model="localDraft.metricIds"
                type="checkbox"
                :value="metric.id"
                :disabled="!localDraft.sectionIds.includes(metric.section)"
              />
              <span
                >{{ metric.label }} <small>{{ metric.section }}</small></span
              >
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Timing Analysis Types</legend>
          <div class="picker-mini-actions">
            <button type="button" @click="$emit('set-all', 'timingTypes', timingTypes)">All</button>
            <button type="button" @click="$emit('set-all', 'timingTypes', [])">None</button>
          </div>
          <label v-for="timingType in timingTypes" :key="timingType">
            <input v-model="localDraft.timingTypes" type="checkbox" :value="timingType" />
            <span>{{ timingType }}</span>
          </label>
          <p v-if="!timingTypes.length" class="muted">当前范围没有 Timing Analysis Type</p>
          <div class="picker-subsection path-group-filter-setting">
            <strong>Path Group Filter</strong>
            <label>
              <input v-model="localDraft.showAllPathGroups" type="checkbox" />
              <span>显示全部 Path Groups（含 WNS ≥ 0 或缺失）</span>
            </label>
            <small>默认仅显示数值 WNS &lt; 0 的 Path Groups</small>
          </div>
        </fieldset>
        <fieldset class="path-group-options">
          <legend>Path Groups</legend>
          <div class="picker-mini-actions">
            <button
              type="button"
              @click="
                $emit(
                  'set-all',
                  'pathGroupIds',
                  pathGroups.map(option => option.id)
                )
              "
            >
              All
            </button>
            <button type="button" @click="$emit('set-all', 'pathGroupIds', [])">None</button>
          </div>
          <label v-for="pathGroup in pathGroups" :key="pathGroup.id">
            <input v-model="localDraft.pathGroupIds" type="checkbox" :value="pathGroup.id" />
            <span>
              {{ pathGroup.name }}
              <small>{{ pathGroup.timingType }} · {{ pathGroup.scenario || '—' }}</small>
            </span>
          </label>
          <p v-if="!pathGroups.length" class="muted">当前范围没有 Path Group 信息</p>
        </fieldset>
      </div>
      <footer>
        <span class="muted">
          已选择 {{ localDraft.sectionIds.length }} 个 Section，
          {{ localDraft.timingTypes.length }} 个 Type， {{ localDraft.pathGroupIds.length }} 个 Path
          Group
        </span>
        <div>
          <button class="btn btn-sm" type="button" @click="$emit('close')">Cancel</button>
          <button class="btn btn-sm btn-primary" type="button" @click="$emit('apply')">
            Apply
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>
