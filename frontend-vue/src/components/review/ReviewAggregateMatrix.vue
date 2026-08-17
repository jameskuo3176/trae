<script setup>
defineProps({
  groupName: { type: String, required: true },
  ownerName: { type: String, default: '' }
})
</script>

<template>
  <section class="review-aggregate-matrix" :aria-label="`${groupName} 聚合评审矩阵`">
    <header class="matrix-scope">
      <h2>{{ groupName }}</h2>
      <p class="muted">负责人：{{ ownerName }}</p>
    </header>
    <slot />
  </section>
</template>
