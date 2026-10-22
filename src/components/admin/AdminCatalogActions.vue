<script setup lang="ts">
defineProps<{
  canDelete: boolean;
  deleteTitle: string;
  deleteLabel: string;
  showRevert: boolean;
  loading: boolean;
  saveDisabled: boolean;
  saveLabel: string;
  cancelLabel?: string;
  deleteDisabled?: boolean;
}>();

const emit = defineEmits<{
  (event: "remove"): void;
  (event: "revert"): void;
  (event: "cancel"): void;
}>();
</script>

<template>
  <div class="publish-actions-row">
    <div class="actions-left">
      <button
        v-if="cancelLabel"
        type="button"
        class="admin-btn secondary"
        :disabled="loading"
        @click="emit('cancel')"
      >
        <span>{{ cancelLabel }}</span>
      </button>
      <button
        v-if="canDelete"
        type="button"
        class="admin-btn danger outline"
        :title="deleteTitle"
        :disabled="deleteDisabled"
        @click="emit('remove')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"/>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        </svg>
        <span>{{ deleteLabel }}</span>
      </button>
    </div>

    <div class="actions-right">
      <button
        v-if="showRevert"
        type="button"
        class="admin-btn secondary"
        :disabled="loading"
        @click="emit('revert')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
          <path d="M3 3v5h5"/>
        </svg>
        <span>还原配置</span>
      </button>

      <button
        class="admin-btn primary domain-save-btn"
        type="submit"
        :disabled="saveDisabled"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
          <polyline points="17 21 17 13 7 13 7 21"/>
          <polyline points="7 3 7 8 15 8"/>
        </svg>
        <span>{{ saveLabel }}</span>
      </button>
    </div>
  </div>
</template>
