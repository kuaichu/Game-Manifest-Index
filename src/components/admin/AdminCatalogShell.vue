<script setup lang="ts">
defineProps<{
  workspaceClass: string;
  listPaneClass: string;
  formPaneClass: string;
  kicker: string;
  countLabel: string;
  createLabel: string;
  catalogMutations: boolean;
  searchQuery: string;
  searchPlaceholder: string;
  itemCount: number;
  emptyTitle: string;
  emptyHint: string;
}>();

const emit = defineEmits<{
  (event: "start"): void;
  (event: "update:search-query", value: string): void;
  (event: "submit"): void;
}>();

function updateSearchQuery(event: Event): void {
  emit("update:search-query", (event.target as HTMLInputElement).value);
}

function preventEnterSubmit(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  if (target && target.tagName === "INPUT") event.preventDefault();
}
</script>

<template>
  <section class="admin-master-detail" :class="workspaceClass">
    <!-- 左侧索引栏 -->
    <aside class="admin-list-pane" :class="listPaneClass">
      <div class="pane-header">
        <div class="pane-title">
          <span class="pane-kicker">{{ kicker }}</span>
          <strong>{{ countLabel }}</strong>
        </div>
        <button v-if="catalogMutations" class="admin-btn primary small create-module-btn" type="button" @click="emit('start')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          <span>{{ createLabel }}</span>
        </button>
      </div>

      <slot name="filters" />

      <div class="pane-search">
        <div class="search-input-wrapper">
          <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            :value="searchQuery"
            @input="updateSearchQuery"
            class="admin-input search-styled"
            :placeholder="searchPlaceholder"
            type="search"
          />
        </div>
      </div>

      <div class="pane-scroll-list">
        <slot />
        <div v-if="!itemCount" class="admin-empty-state">
          <span>{{ emptyTitle }}</span>
          <span>{{ emptyHint }}</span>
        </div>
      </div>
    </aside>

    <!-- 右侧卡片化编辑器 -->
    <form
      v-if="catalogMutations"
      class="admin-form-pane"
      :class="formPaneClass"
      @keydown.enter="preventEnterSubmit"
      @submit.prevent="emit('submit')"
    >
      <slot name="form" />
    </form>
  </section>
</template>
