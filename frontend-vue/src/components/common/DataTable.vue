<script setup>
import { computed, ref } from 'vue'
import { useTableSort } from '@/composables/useTableSort'
import { useClipboard } from '@/composables/useClipboard'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  columns: { type: Array, required: true },
  rowKey: { type: String, default: 'id' },
  emptyText: { type: String, default: 'No data' },
  filename: { type: String, default: 'qor-data.csv' },
  copyOnClick: Boolean,
  maxHeight: { type: String, default: '60vh' }
})

const widths = ref({})
const { sortKey, sortOrder, sortBy, computeSorted } = useTableSort()
const { copied, copy } = useClipboard()
const valueOf = (row, column) => (column.value ? column.value(row) : row[column.key])
const columnByKey = key => props.columns.find(column => column.key === key)
const sortValueOf = (row, key) => {
  const column = columnByKey(key)
  if (!column) return row[key]
  return column.sortValue ? column.sortValue(row) : valueOf(row, column)
}
const sortedRows = computed(() => computeSorted(props.rows, sortValueOf))
const formatted = (row, column) =>
  column.format ? column.format(valueOf(row, column), row) : (valueOf(row, column) ?? '-')
const cellClass = (row, column) =>
  typeof column.class === 'function' ? column.class(row, valueOf(row, column)) : column.class
const csvCell = value => `"${String(value ?? '').replaceAll('"', '""')}"`

function exportText(markdown = false) {
  const visible = props.columns.filter(column => !column.hidden)
  if (markdown) {
    const header = `| ${visible.map(column => column.label).join(' | ')} |`
    const divider = `| ${visible.map(() => '---').join(' | ')} |`
    return [
      header,
      divider,
      ...sortedRows.value.map(
        row =>
          `| ${visible.map(column => String(formatted(row, column)).replaceAll('|', '\\|')).join(' | ')} |`
      )
    ].join('\n')
  }
  return [
    visible.map(column => csvCell(column.label)).join(','),
    ...sortedRows.value.map(row => visible.map(column => csvCell(valueOf(row, column))).join(','))
  ].join('\n')
}

function download() {
  const blob = new Blob(['\uFEFF', exportText()], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = props.filename
  link.click()
  URL.revokeObjectURL(url)
}

function beginResize(event, column) {
  const startX = event.clientX
  const startWidth = widths.value[column.key] || event.currentTarget.parentElement.offsetWidth
  const move = moveEvent => {
    widths.value = {
      ...widths.value,
      [column.key]: Math.max(64, startWidth + moveEvent.clientX - startX)
    }
  }
  const stop = () => {
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', stop)
  }
  document.addEventListener('mousemove', move)
  document.addEventListener('mouseup', stop)
}

defineExpose({ exportText, download })
</script>

<template>
  <div class="data-table-shell">
    <div class="data-table-actions">
      <span aria-live="polite">{{ copied ? `${copied} copied` : `${rows.length} rows` }}</span>
      <button
        class="btn btn-sm btn-default"
        type="button"
        @click="copy(exportText(true), 'Markdown')"
      >
        Copy Markdown
      </button>
      <button class="btn btn-sm btn-default" type="button" @click="copy(exportText(), 'CSV')">
        Copy CSV
      </button>
      <button class="btn btn-sm btn-default" type="button" @click="download">Export CSV</button>
    </div>
    <div class="data-table-scroll" :style="{ maxHeight }">
      <table class="table data-table">
        <thead>
          <tr>
            <th
              v-for="column in columns"
              v-show="!column.hidden"
              :key="column.key"
              :style="{ width: widths[column.key] ? `${widths[column.key]}px` : column.width }"
              :aria-sort="
                sortKey === column.key ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none'
              "
            >
              <button
                v-if="column.sortable !== false"
                class="sort-button"
                type="button"
                @click="sortBy(column.key)"
              >
                {{ column.label }}
                <span aria-hidden="true">{{
                  sortKey === column.key ? (sortOrder === 'asc' ? '↑' : '↓') : '↕'
                }}</span>
              </button>
              <span v-else>{{ column.label }}</span>
              <span class="resize-handle" @mousedown.prevent="beginResize($event, column)" />
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in sortedRows" :key="row[rowKey] ?? index">
            <td
              v-for="column in columns"
              v-show="!column.hidden"
              :key="column.key"
              :class="[cellClass(row, column), { numeric: column.numeric, copyable: copyOnClick }]"
              :title="String(formatted(row, column))"
              @click="copyOnClick && copy(formatted(row, column), column.label)"
            >
              <slot :name="`cell-${column.key}`" :row="row" :value="valueOf(row, column)">
                {{ formatted(row, column) }}
              </slot>
            </td>
          </tr>
          <tr v-if="!sortedRows.length">
            <td :colspan="columns.length" class="empty-state">{{ emptyText }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.data-table-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  color: var(--color-text-secondary);
  font-size: 11px;
  border-bottom: 1px solid var(--color-border);
}
.data-table-scroll {
  overflow: auto;
}
.data-table {
  table-layout: auto;
  font-size: 11px;
  font-family: Consolas, Monaco, monospace;
}
.data-table th {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 0;
  white-space: nowrap;
  border-right: 1px solid var(--color-border);
}
.data-table td {
  padding: 5px 8px;
  white-space: nowrap;
  border-right: 1px solid var(--color-border);
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 420px;
}
.sort-button {
  width: 100%;
  padding: 6px 16px 6px 8px;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  font-weight: 600;
}
.resize-handle {
  position: absolute;
  right: -2px;
  top: 0;
  width: 5px;
  height: 100%;
  cursor: col-resize;
}
.resize-handle:hover {
  background: var(--color-primary);
}
.numeric {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.copyable {
  cursor: copy;
}
.copyable:active {
  color: var(--color-primary);
}
</style>
