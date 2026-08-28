<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { api, isAbortError } from "../api";
import type { CompareItem, ComparePage } from "../types";

const props = defineProps<{ domainId: string; fromVersion: string; toVersion: string; kind?: string }>();
const filter = ref<"all" | "added" | "removed" | "changed">("all");
const page = ref<ComparePage | null>(null);
const items = ref<CompareItem[]>([]);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref("");
let controller: AbortController | null = null;

const filters = [
  { id: "all", label: "全部" },
  { id: "added", label: "新增" },
  { id: "removed", label: "删除" },
  { id: "changed", label: "修改" },
] as const;

function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Math.abs(value), unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${value < 0 ? "−" : ""}${size.toFixed(unit ? 2 : 0)} ${units[unit]}`;
}

async function load(append = false): Promise<void> {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  append ? loadingMore.value = true : loading.value = true;
  error.value = "";
  try {
    const result = await api.compare(props.domainId, {
      fromVersion: props.fromVersion,
      toVersion: props.toVersion,
      kind: props.kind,
      change: filter.value,
      limit: 100,
      cursor: append ? page.value?.next_cursor : null,
    }, request.signal);
    page.value = result;
    items.value = append ? [...items.value, ...result.items] : result.items;
  } catch (reason) {
    if (isAbortError(reason)) return;
    error.value = reason instanceof Error ? reason.message : "版本对比加载失败";
  } finally {
    if (controller === request) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

watch(
  () => [props.domainId, props.fromVersion, props.toVersion, props.kind, filter.value],
  () => void load(false),
  { immediate: true },
);
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <div class="compare-view">
    <div class="compare-summary" v-if="page">
      <div class="compare-stat green"><span>+ 新增</span><strong>{{ page.summary.added }} 个</strong></div>
      <div class="compare-stat rose"><span>− 删除</span><strong>{{ page.summary.removed }} 个</strong></div>
      <div class="compare-stat violet"><span>~ 修改</span><strong>{{ page.summary.changed }} 个</strong><small>净变化 {{ formatBytes(page.summary.size_delta) }}</small></div>
    </div>
    <div class="diff-filter" aria-label="变化类型">
      <button v-for="entry in filters" :key="entry.id" :class="{ active: filter === entry.id }" @click="filter = entry.id">{{ entry.label }}</button>
    </div>
    <div v-if="loading" class="empty">正在计算版本差异…</div>
    <div v-else-if="error" class="empty error-state"><strong>版本对比加载失败</strong><span>{{ error }}</span><button class="tool-button" type="button" @click="load(false)">重试</button></div>
    <div v-else-if="items.length" class="diff-table">
      <article v-for="(item, index) in items" :key="`${item.change}:${JSON.stringify(item.identity)}`" class="diff-row" :class="`diff-${item.change === 'changed' ? 'modified' : item.change}`">
        <b class="diff-marker">{{ item.change === "added" ? "+" : item.change === "removed" ? "−" : "~" }}</b>
        <div class="diff-body">
          <div class="diff-title"><strong>{{ item.after?.name || item.before?.name }}</strong><span>{{ index + 1 }}</span></div>
          <div class="diff-path">{{ item.after?.kind || item.before?.kind }} · part {{ item.after?.part || item.before?.part }}</div>
          <div class="diff-change"><span>size:</span><code>{{ item.before ? formatBytes(item.before.size) : "—" }}</code><span>→</span><code>{{ item.after ? formatBytes(item.after.size) : "—" }}</code></div>
          <div class="diff-change"><span>checksum:</span><code>{{ item.before?.checksum_value || "—" }}</code><span>→</span><code>{{ item.after?.checksum_value || "—" }}</code></div>
        </div>
      </article>
    </div>
    <div v-else class="empty">当前筛选没有变化记录。</div>
    <button v-if="page?.next_cursor" class="load-more" :disabled="loadingMore" @click="load(true)">{{ loadingMore ? "读取中…" : "加载更多变化" }}</button>
  </div>
</template>
