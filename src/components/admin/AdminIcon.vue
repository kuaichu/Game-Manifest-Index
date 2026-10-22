<script setup lang="ts">
withDefaults(
  defineProps<{
    name: "game" | "box" | "contents" | "pulse" | "logout";
    size?: number;
  }>(),
  { size: 18 },
);
</script>

<template>
  <svg
    class="admin-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'game'">
      <path d="M7.5 8.2h9a4.3 4.3 0 0 1 4.2 3.4l.8 4a2.6 2.6 0 0 1-4.6 2.2l-1.3-1.7H8.4l-1.3 1.7a2.6 2.6 0 0 1-4.6-2.2l.8-4a4.3 4.3 0 0 1 4.2-3.4Z" />
      <path d="M8 11.4v2.4M6.8 12.6h2.4" />
      <circle cx="15.6" cy="11.7" r=".9" fill="currentColor" stroke="none" />
      <circle cx="17.6" cy="13.6" r=".9" fill="currentColor" stroke="none" />
    </template>
    <template v-else-if="name === 'box'">
      <path d="m12 3 7.5 4.2v9.6L12 21l-7.5-4.2V7.2L12 3Z" />
      <path d="m4.7 7.4 7.3 4 7.3-4M12 11.4V21" />
    </template>
    <template v-else-if="name === 'contents'">
      <path d="M5 4.5h9.5L19 9v10.5H5z" />
      <path d="M14 4.6V9h4.4M8.2 13h7.6M8.2 16.4h5" />
    </template>
    <template v-else-if="name === 'pulse'">
      <path d="M3 12h3.4L9 5.5l3.6 13L15.4 12H21" />
    </template>
    <template v-else>
      <path d="M14.5 4.5h5v5M19.5 4.5 12 12" />
      <path d="M10.2 6H6.4A1.9 1.9 0 0 0 4.5 7.9v9.7a1.9 1.9 0 0 0 1.9 1.9h9.7a1.9 1.9 0 0 0 1.9-1.9v-3.8" />
    </template>
  </svg>
</template>
