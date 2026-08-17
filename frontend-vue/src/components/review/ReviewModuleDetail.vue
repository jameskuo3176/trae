<script setup>
defineProps({
  moduleName: { type: String, required: true },
  risk: { type: String, default: 'unrated' }
})
</script>

<template>
  <article class="module-card">
    <header>
      <strong>{{ moduleName }}</strong>
      <div class="module-header-actions">
        <span :class="['risk', `risk-${risk}`]">{{ risk }}</span>
      </div>
    </header>
    <slot />
  </article>
</template>
