<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api, isAbortError } from "../api";
import { artifactUrlStateCounts, isAvailabilityActionable, latestLiveProbeTime } from "../domain-presentation";
import type { Artifact, ArtifactTreePage, AvailabilityState } from "../types";
import AvailabilityBadge from "./AvailabilityBadge.vue";
import FragmentFileRow from "./FragmentFileRow.vue";

const props = withDefaults(
  defineProps<{
    domainId: string;
    version: string;
    kind: string;
    availabilityState?: AvailabilityState;
    allowActions?: boolean;
  }>(),
  { allowActions: false }
);

const emit = defineEmits<{
  (e: "probe-time-change", value: string | null): void;
}>();

const page = ref<ArtifactTreePage>({ prefix: "", folders: [], items: [], next_cursor: null });
const loading = ref(true);
const loadingMore = ref(false);
const error = ref("");
const expanded = ref<number | null>(null);
let controller: AbortController | null = null;
let requestGeneration = 0;

const crumbs = computed(() => page.value.prefix.split("/").filter(Boolean));
const showsUrlDetails = computed(() => props.kind !== "file");

async function load(prefix: string, append = false): Promise<void> {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  const generation = ++requestGeneration;
  append ? (loadingMore.value = true) : (loading.value = true);
  if (!append) emit("probe-time-change", null);
  error.value = "";
  try {
    const result = await api.artifactTree(
      props.domainId,
      props.version,
      {
        kind: props.kind,
        prefix,
        cursor: append ? page.value.next_cursor : null,
        state: showsUrlDetails.value ? props.availabilityState : undefined,
        limit: 100,
      },
      request.signal
    );
    if (controller !== request || generation !== requestGeneration) return;
    page.value = append ? { ...result, items: [...page.value.items, ...result.items] } : result;
    emit("probe-time-change", latestLiveProbeTime(page.value.items));
    if (!append) expanded.value = null;
  } catch (reason) {
    if (isAbortError(reason) || controller !== request || generation !== requestGeneration) return;
    error.value = reason instanceof Error ? reason.message : "目录加载失败";
    emit("probe-time-change", null);
  } finally {
    if (controller === request && generation === requestGeneration) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

function goCrumb(index: number): void {
  void load(crumbs.value.slice(0, index + 1).join("/"));
}

function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 2 : 0)} ${units[unit]}`;
}

function filename(item: Artifact): string {
  return item.name.replaceAll("\\", "/").split("/").at(-1) || item.name;
}

function artifactPath(item: Artifact): string {
  const normalized = item.name.replaceAll("\\", "/");
  return normalized === filename(item) ? "" : normalized;
}

function toggle(item: Artifact): void {
  expanded.value = expanded.value === item.id ? null : item.id;
}

function candidateIsActionable(candidate: Artifact["urls"][number]): boolean {
  return props.allowActions && isAvailabilityActionable(candidate.current, candidate.url);
}

function stateRows(item: Artifact): Array<{ state: AvailabilityState; label: string; count: number }> {
  const counts = artifactUrlStateCounts(item);
  return (
    [
      { state: "available", label: "可用", count: counts.available },
      { state: "unavailable", label: "失效", count: counts.unavailable },
      { state: "unknown", label: "未判定", count: counts.unknown },
    ] as Array<{ state: AvailabilityState; label: string; count: number }>
  ).filter((row) => row.count > 0);
}

watch(
  () => [props.domainId, props.version, props.kind],
  () => void load("")
);
watch(
  () => props.availabilityState,
  () => void load(page.value.prefix)
);
onMounted(() => void load(""));
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <div class="remote-tree-container">
    <!-- 加载中 -->
    <div v-if="loading" class="tree-state-box">
      <div class="tree-spinner"></div>
      <span>正在读取目录索引…</span>
    </div>

    <!-- 错误重试 -->
    <div v-else-if="error" class="tree-state-box error">
      <strong>目录加载失败</strong>
      <span>{{ error }}</span>
      <button class="tool-button" type="button" @click="load(page.prefix)">重试</button>
    </div>

    <!-- 主表格结构 (统一融合导航与数据表) -->
    <div v-else-if="page.folders.length || page.items.length" class="tree-table-wrapper">
      <!-- 顶部集成导航栏 (面包屑 + 统计) -->
      <div class="tree-table-nav">
        <div class="nav-breadcrumbs">
          <button
            type="button"
            class="nav-crumb-btn"
            :class="{ active: !crumbs.length }"
            @click="load('')"
          >
            <svg class="nav-crumb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              <polyline points="9 22 9 12 15 12 15 22" />
            </svg>
            <span>根目录</span>
          </button>

          <template v-for="(part, index) in crumbs" :key="`${part}:${index}`">
            <span class="nav-crumb-sep">/</span>
            <button
              type="button"
              class="nav-crumb-btn"
              :class="{ active: index === crumbs.length - 1 }"
              @click="goCrumb(index)"
            >
              {{ part }}
            </button>
          </template>
        </div>

        <div class="nav-stats">
          <span v-if="page.folders.length">{{ page.folders.length }} 文件夹</span>
          <span v-if="page.folders.length && page.items.length"> · </span>
          <span v-if="page.items.length">{{ page.items.length }} 文件</span>
          <span class="visually-hidden">当前目录：{{ page.folders.length ? `${page.folders.length} 个文件夹` : '' }} {{ page.items.length ? `${page.items.length} 个文件` : '' }}</span>
        </div>
      </div>

      <!-- 表头 Header -->
      <div class="tree-grid-header">
        <div class="col-name">名称</div>
        <div class="col-hash">校验值</div>
        <div class="col-size">大小</div>
        <div class="col-action">操作</div>
      </div>

      <!-- 表体 Body -->
      <div class="tree-grid-body">
        <!-- 文件夹行 -->
        <div
          v-for="folder in page.folders"
          :key="folder.path"
          class="tree-grid-row folder-grid-row folder-row"
          role="button"
          tabindex="0"
          @click="load(folder.path)"
          @keydown.enter="load(folder.path)"
        >
          <div class="row-main">
            <div class="col-name">
              <span class="tree-item-icon folder" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M20 5h-8.586L9.707 3.293A1 1 0 0 0 9 3H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2z" />
                </svg>
              </span>
              <strong class="item-foldername">{{ folder.name }}</strong>
              <span class="folder-subcount">{{ folder.artifact_count }} 个文件</span>
            </div>
            <div class="col-hash dim-text">—</div>
            <div class="col-size mono-text">{{ formatBytes(folder.total_size) }}</div>
            <div class="col-action">
              <span class="folder-enter-chevron" aria-hidden="true">›</span>
              <span class="visually-hidden">进入</span>
            </div>
          </div>
        </div>

        <!-- 文件行 -->
        <template v-for="artifact in page.items" :key="artifact.id">
          <FragmentFileRow v-if="!showsUrlDetails" :artifact="artifact" />
          <div v-else class="tree-grid-row file-grid-row file-row" :class="{ 'is-expanded': expanded === artifact.id }">
            <div class="row-main" role="button" tabindex="0" @click="toggle(artifact)" @keydown.enter="toggle(artifact)">
              <div class="col-name">
                <span class="tree-item-icon file" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </span>
                <strong class="item-filename">{{ filename(artifact) }}</strong>
                <small v-if="artifactPath(artifact)" class="item-subpath">({{ artifactPath(artifact) }})</small>
              </div>
              <div class="col-hash">
                <span class="hash-code-chip">{{ artifact.checksum_value || '—' }}</span>
              </div>
              <div class="col-size mono-text">{{ formatBytes(artifact.size) }}</div>
              <div class="col-action">
                <span class="expand-trigger" :class="{ open: expanded === artifact.id }">
                  <span class="trigger-label">{{ expanded === artifact.id ? '收起' : `${artifact.urls.length} 个候选` }}</span>
                  <svg class="chevron-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </span>
              </div>
            </div>

            <!-- 展开候选 URL 列表 (针对非普通 file 的 resource 模式) -->
            <div v-if="expanded === artifact.id" class="row-drawer">
              <div class="drawer-header">
                <div class="drawer-status-line">
                  <strong class="drawer-target-title">{{ artifact.checksum_type || 'checksum' }}: {{ artifact.checksum_value || '—' }}</strong>
                  <span class="dim-text">({{ artifact.urls.length }} 个 provider 候选)</span>
                </div>
              </div>
              <div class="browser-url-list">
                <div v-for="candidate in artifact.urls" :key="candidate.id" class="browser-url-row">
                  <AvailabilityBadge :value="candidate.current || null" />
                  <strong>{{ candidate.provider || candidate.source_kind || 'unknown' }}</strong>
                  <span :title="candidate.url">{{ candidate.url }}</span>
                  <a v-if="candidateIsActionable(candidate)" class="icon-button" :href="candidate.url" target="_blank" rel="noreferrer">打开</a>
                  <span v-else class="stale-link">不可操作</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 加载更多 -->
    <div v-if="page.next_cursor" class="tree-load-more">
      <button class="tree-load-btn" :disabled="loadingMore" type="button" @click="load(page.prefix, true)">
        <span v-if="loadingMore" class="tree-btn-spinner"></span>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
        <span>{{ loadingMore ? '读取中…' : '加载更多文件' }}</span>
      </button>
    </div>

    <!-- 空目录 -->
    <div v-if="!loading && !page.folders.length && !page.items.length" class="tree-state-box">
      当前目录为空。
    </div>
  </div>
</template>
