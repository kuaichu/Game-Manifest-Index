<script setup lang="ts">
defineProps<{
  icon?: string;
  title: string;
  subtitle: string;
  tag?: string;
  extraClass?: string;
}>();
</script>

<template>
  <div class="form-section-card domain-card" :class="extraClass">
    <div class="section-card-header">
      <div class="section-header-left">
        <span v-if="icon" class="section-icon">{{ icon }}</span>
        <div>
          <div class="section-card-title">{{ title }}</div>
          <p class="section-card-subtitle">{{ subtitle }}</p>
        </div>
      </div>
      <div v-if="tag" class="section-header-badge">
        <span class="block-tag-pill">{{ tag }}</span>
      </div>
    </div>
    <slot />
  </div>
</template>
