<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{
  page: number;
  total: number;
  pageSize: number;
  pageSizeOptions?: number[];
  loading?: boolean;
}>(), {
  pageSizeOptions: () => [50, 100, 200, 500],
  loading: false,
});

const emit = defineEmits<{
  (event: "update:page", value: number): void;
  (event: "update:pageSize", value: number): void;
}>();

const pageCount = computed(() => Math.max(1, Math.ceil(Math.max(0, props.total) / props.pageSize)));
const pages = computed<Array<number | "ellipsis">>(() => {
  const count = pageCount.value;
  if (count <= 7) return Array.from({ length: count }, (_, index) => index + 1);
  const current = Math.min(Math.max(props.page, 1), count);
  const result: Array<number | "ellipsis"> = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(count - 1, current + 1);
  if (start > 2) result.push("ellipsis");
  for (let value = start; value <= end; value += 1) result.push(value);
  if (end < count - 1) result.push("ellipsis");
  result.push(count);
  return result;
});

function selectPage(page: number): void {
  if (page < 1 || page > pageCount.value || page === props.page || props.loading) return;
  emit("update:page", page);
}

function selectPageSize(event: Event): void {
  const value = Number((event.target as HTMLSelectElement).value);
  if (Number.isInteger(value) && value > 0) emit("update:pageSize", value);
}
</script>

<template>
  <div v-if="total > 0" class="artifact-pagination" aria-label="分页">
    <label class="artifact-page-size">
      <span>每页</span>
      <select :value="pageSize" :disabled="loading" @change="selectPageSize">
        <option v-for="option in pageSizeOptions" :key="option" :value="option">{{ option }}</option>
      </select>
      <span>条</span>
    </label>
    <button type="button" class="artifact-page-button" :disabled="page <= 1 || loading" @click="selectPage(page - 1)">上一页</button>
    <template v-for="(item, index) in pages" :key="`${item}-${index}`">
      <span v-if="item === 'ellipsis'" class="artifact-page-ellipsis">…</span>
      <button v-else type="button" class="artifact-page-button" :class="{ active: item === page }" :disabled="loading" @click="selectPage(item)">{{ item }}</button>
    </template>
    <button type="button" class="artifact-page-button" :disabled="page >= pageCount || loading" @click="selectPage(page + 1)">下一页</button>
    <span class="artifact-page-total">共 {{ total.toLocaleString() }} 条</span>
  </div>
</template>

<style scoped>
.artifact-pagination { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; padding: 18px 4px 4px; }
.artifact-page-size, .artifact-page-total { align-items: center; color: var(--text-muted, #8b9ab5); display: inline-flex; font-size: 12px; gap: 5px; }
.artifact-page-size { margin-right: 8px; }
.artifact-page-size select { background: var(--surface-2, #172337); border: 1px solid var(--border, #2a3a52); border-radius: 6px; color: inherit; padding: 5px 22px 5px 7px; }
.artifact-page-button { background: var(--surface-2, #172337); border: 1px solid var(--border, #2a3a52); border-radius: 6px; color: var(--text-secondary, #b6c3d7); cursor: pointer; min-width: 32px; padding: 6px 9px; }
.artifact-page-button:hover:not(:disabled), .artifact-page-button.active { background: var(--accent, #0ea5e9); border-color: var(--accent, #0ea5e9); color: white; }
.artifact-page-button:disabled { cursor: default; opacity: .45; }
.artifact-page-ellipsis { color: var(--text-muted, #8b9ab5); padding: 0 2px; }
</style>
