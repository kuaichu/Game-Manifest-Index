<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

export interface ConfirmDialogRequest {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  tone: "default" | "danger";
}

const props = defineProps<{ request: ConfirmDialogRequest | null }>();
const emit = defineEmits<{ resolve: [accepted: boolean] }>();

const acceptButton = ref<HTMLButtonElement | null>(null);

watch(
  () => props.request,
  async (request) => {
    if (!request) return;
    await nextTick();
    acceptButton.value?.focus();
  },
);

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;
  event.preventDefault();
  emit("resolve", false);
}
</script>

<template>
  <div
    v-if="request"
    class="admin-confirm-backdrop"
    data-testid="admin-confirm-backdrop"
    @keydown="onKeydown"
    @click.self="emit('resolve', false)"
  >
    <div
      class="admin-confirm-dialog"
      :class="{ 'is-danger': request.tone === 'danger' }"
      role="dialog"
      aria-modal="true"
      :aria-label="request.title"
    >
      <div class="admin-confirm-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M10 3.4 17.2 16H2.8L10 3.4Z" stroke-linejoin="round" />
          <path d="M10 8v3.6" stroke-linecap="round" />
          <circle cx="10" cy="13.9" r="0.85" fill="currentColor" stroke="none" />
        </svg>
      </div>
      <h3 class="admin-confirm-title">{{ request.title }}</h3>
      <p class="admin-confirm-message">{{ request.message }}</p>
      <div class="admin-confirm-actions">
        <button
          type="button"
          class="admin-confirm-btn"
          data-testid="admin-confirm-cancel"
          @click="emit('resolve', false)"
        >
          {{ request.cancelLabel }}
        </button>
        <button
          ref="acceptButton"
          type="button"
          class="admin-confirm-btn is-primary"
          data-testid="admin-confirm-accept"
          @click="emit('resolve', true)"
        >
          {{ request.confirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>
