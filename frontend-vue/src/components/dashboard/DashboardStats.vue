<script setup>
defineProps({ stats: { type: Object, required: true } })
</script>
<template>
  <section class="stats-strip" aria-label="Dashboard statistics">
    <div>
      <span>Records</span><strong>{{ stats.total }}</strong>
    </div>
    <div>
      <span>Modules</span><strong>{{ stats.modules }}</strong>
    </div>
    <div>
      <span>Projects</span><strong>{{ stats.projects }}</strong>
    </div>
    <div>
      <span>Latest path version</span><strong class="version">{{ stats.latest }}</strong>
    </div>
  </section>
</template>
<style scoped>
.stats-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(100px, 1fr)) minmax(180px, 2fr);
  margin-bottom: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.stats-strip div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 10px;
  border-right: 1px solid var(--color-border);
}
.stats-strip div:last-child {
  border-right: 0;
}
.stats-strip span {
  color: var(--color-text-secondary);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
}
.stats-strip strong {
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}
.stats-strip .version {
  color: var(--color-primary);
  font:
    600 12px Consolas,
    monospace;
}
@media (max-width: 800px) {
  .stats-strip {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
