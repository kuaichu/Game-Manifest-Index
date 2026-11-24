<script setup lang="ts">
defineProps<{
  title: string;
  subtitle: string;
  extraClass?: string;
}>();
</script>

<template>
  <div class="form-section-card domain-card" :class="extraClass">
    <div class="section-card-header">
      <div class="section-header-left">
        <div>
          <div class="section-card-title">{{ title }}</div>
          <p class="section-card-subtitle">{{ subtitle }}</p>
        </div>
      </div>
    </div>
    <slot />
  </div>
</template>
