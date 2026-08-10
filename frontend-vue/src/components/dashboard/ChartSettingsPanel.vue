<script setup>
import { computed } from 'vue'

const props = defineProps({
  orientation: { type: String, default: 'vertical' },
  height: { type: Number, default: 500 },
  labelMode: { type: String, default: 'both' },
  chartType: { type: String, default: 'bar' },
  tableWidth: { type: Number, default: 0 },
  showCombined: { type: Boolean, default: false },
  showTransposed: { type: Boolean, default: false },
  showDirAggregate: { type: Boolean, default: false },
  showDirModules: { type: Boolean, default: false }
})

const emit = defineEmits([
  'update:orientation',
  'update:height',
  'update:labelMode',
  'update:chartType',
  'update:tableWidth',
  'update:showCombined',
  'update:showTransposed',
  'update:showDirAggregate',
  'update:showDirModules'
])

const isTableMode = computed(() => props.chartType === 'table')
</script>

<template>
  <div class="chart-settings card">
    <div class="card-body settings-body">
      <div class="setting-group">
        <label>图表方向</label>
        <select :value="orientation" @change="$emit('update:orientation', ($event.target).value)">
          <option value="vertical">纵向</option>
          <option value="horizontal">横向</option>
        </select>
      </div>
      <div class="setting-group">
        <label>图表高度</label>
        <select :value="String(height)" @change="$emit('update:height', Number(($event.target).value))">
          <option value="360">小 (360px)</option>
          <option value="500">中 (500px)</option>
          <option value="640">大 (640px)</option>
          <option value="800">超大 (800px)</option>
        </select>
      </div>
      <div class="setting-group">
        <label>X轴标签</label>
        <select :value="labelMode" @change="$emit('update:labelMode', ($event.target).value)">
          <option value="both">模块+标签</option>
          <option value="module">仅模块名</option>
          <option value="tag">仅标签</option>
          <option value="module_tag_dir">模块+标签+目录</option>
        </select>
      </div>
      <div class="setting-group">
        <label>图表类型</label>
        <select :value="chartType" @change="$emit('update:chartType', ($event.target).value)">
          <option value="bar">柱状图</option>
          <option value="line">折线图</option>
          <option value="table">表格 (可排序)</option>
        </select>
      </div>
      <div v-if="isTableMode" class="setting-group">
        <label>表格宽度</label>
        <div class="table-width-control">
          <input
            type="range"
            min="500"
            max="2400"
            step="50"
            :value="tableWidth || 0"
            @input="$emit('update:tableWidth', Number(($event.target).value))"
          />
          <span class="width-label">{{ tableWidth || '自动' }}</span>
          <button class="btn btn-sm" @click="$emit('update:tableWidth', 0)">↺</button>
        </div>
      </div>
      <div class="setting-group">
        <label>CSV 导出</label>
        <button class="btn btn-sm" @click="$emit('update:showCombined', !showCombined)">
          合并导出 CSV
        </button>
      </div>
      <div class="setting-group">
        <label>全量合并</label>
        <div class="view-buttons">
          <button class="btn btn-sm" @click="$emit('update:showCombined', !showCombined)">
            {{ showCombined ? '关闭' : '' }}合并表格
          </button>
          <button class="btn btn-sm" @click="$emit('update:showTransposed', !showTransposed)">
            {{ showTransposed ? '关闭' : '' }}转置表格
          </button>
          <button class="btn btn-sm" @click="$emit('update:showDirAggregate', !showDirAggregate)">
            {{ showDirAggregate ? '关闭' : '' }}目录聚合
          </button>
          <button class="btn btn-sm" @click="$emit('update:showDirModules', !showDirModules)">
            {{ showDirModules ? '关闭' : '' }}目录模块
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chart-settings {
  margin-bottom: 12px;
}
.settings-body {
  display: flex;
  gap: 20px;
  align-items: flex-end;
  padding: 10px 16px;
  flex-wrap: wrap;
}
.setting-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.setting-group label {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.setting-group select {
  font-size: 13px;
  min-width: 120px;
}
.table-width-control {
  display: flex;
  align-items: center;
  gap: 4px;
}
.table-width-control input[type="range"] {
  width: 80px;
  cursor: pointer;
}
.width-label {
  font-size: 11px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  min-width: 32px;
}
.view-buttons {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>