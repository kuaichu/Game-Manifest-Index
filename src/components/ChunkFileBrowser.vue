<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, chunkContentUrl, isAbortError } from "../api";
import { formatBytes, formatObservedDate, hoyoLanguageLabel } from "../domain-presentation";
import { chunkUrl, ChunkDownloadError, MAX_BROWSER_SYNTHESIS_SIZE, saveBlob, synthesizeChunkFile, type ChunkDownloadProgress } from "../chunk-download";
import type {
  ArchiveDomain,
  ChunkFileDetail,
  ChunkFileItem,
  ChunkFilesPage,
  ChunkManifestDetail,
  ChunkManifestSummaryItem,
  Game,
  VersionSummary,
} from "../types";

const props = defineProps<{
  domainId: string;
  version: string;
  game: Game | null;
  domain: ArchiveDomain | null;
  chunkDetail: ChunkManifestDetail | null;
  versionSummary?: VersionSummary | null;
  chunkCollection?: ChunkManifestSummaryItem[];
  searchQuery?: string;
}>();

const route = useRoute();
const router = useRouter();

// Source resolution (package vs chunk vs auto)
const hasPackage = computed(() => {
  const kinds = props.versionSummary?.artifact_kinds;
  return Boolean(
    kinds?.package?.count ||
      kinds?.file?.count ||
      (props.domain?.capabilities?.includes("packages") && props.domain?.adapter === "hoyo"),
  );
});

const hasChunk = computed(() => {
  const kinds = props.versionSummary?.artifact_kinds;
  return Boolean(
    kinds?.chunk?.count ||
      props.chunkCollection?.some((c) => c.version === props.version) ||
      props.chunkDetail?.manifests?.length,
  );
});

function resolveDefaultSource(): "package" | "chunk" {
  if (hasPackage.value) return "package";
  if (hasChunk.value) return "chunk";
  return "package";
}

const activeSource = ref<"package" | "chunk">("package");
const selectedIdentity = ref<string>("game");
const currentPath = ref<string>("");
const filePage = ref<ChunkFilesPage | null>(null);
const loading = ref<boolean>(true);
const loadingMore = ref<boolean>(false);
const error = ref<string | null>(null);

// Detect if package is unavailable / expired on CDN
const isUnavailablePackage = computed(() => {
  const pkgKinds = props.versionSummary?.artifact_kinds?.package;
  const isAllUnavailable = Boolean(
    pkgKinds &&
      pkgKinds.count > 0 &&
      pkgKinds.availability_states?.available === 0 &&
      pkgKinds.availability_states?.unavailable === pkgKinds.count,
  );
  const isRangeOrUpstreamError = Boolean(
    error.value &&
      (error.value.includes("Range") ||
        error.value.includes("502") ||
        error.value.includes("404") ||
        error.value.includes("失效") ||
        error.value.includes("超时") ||
        error.value.includes("package")),
  );
  return activeSource.value === "package" && (isAllUnavailable || isRangeOrUpstreamError);
});

function navigateToPatches(): void {
  void router.push({
    name: "archive",
    params: {
      gameId: String(route.params.gameId || props.game?.id || props.domain?.game_id || ""),
      domainId: String(route.params.domainId || props.domainId),
      version: props.version,
      mode: "patches",
    },
  });
}

// File Detail Modal State
const selectedFile = ref<ChunkFileItem | null>(null);
const fileDetail = ref<ChunkFileDetail | null>(null);
const fileDetailLoading = ref<boolean>(false);
const fileDetailError = ref<string | null>(null);
const showDetailModal = ref<boolean>(false);
const toastMessage = ref<string>("");
const downloadController = ref<AbortController | null>(null);
const downloadProgress = ref<ChunkDownloadProgress | null>(null);
const downloadError = ref<string | null>(null);
const downloading = ref(false);

let listController: AbortController | null = null;
let detailController: AbortController | null = null;
let detailGeneration = 0;
let requestId = 0;

function copyText(text: string, label: string): void {
  void navigator.clipboard.writeText(text);
  toastMessage.value = `已复制 ${label}`;
  window.setTimeout(() => {
    toastMessage.value = "";
  }, 2000);
}

// Identities available in this chunk manifest
const identities = computed(() => {
  if (activeSource.value === "chunk" && props.chunkDetail?.manifests?.length) {
    const result: Array<{ key: string; label: string; component: string; count: number }> = [];
    for (const m of props.chunkDetail.manifests) {
      const key = m.matching_field || m.language || m.component;
      let label = m.category?.name || "";
      if (!label) {
        if (m.component === "game") label = "游戏主资源";
        else if (m.language) label = `${hoyoLanguageLabel(m.language)}语音包`;
        else label = `${m.component} 组件`;
      }
      result.push({
        key,
        label,
        component: m.component,
        count: m.stats?.file_count || 0,
      });
    }
    return result;
  }
  return [{ key: "game", label: "游戏主资源", component: "game", count: 0 }];
});

// Active Manifest Recipe for chunk downloading
const activeManifest = computed(() => {
  if (!props.chunkDetail?.manifests?.length) return null;
  return (
    props.chunkDetail.manifests.find(
      (m) => (m.matching_field || m.language || m.component) === selectedIdentity.value,
    ) || props.chunkDetail.manifests[0]
  );
});

function chunkDownloadUrl(chunkName: string): string {
  const recipe = activeManifest.value?.chunk_download;
  if (!recipe || !chunkName) return "";
  try { return chunkUrl(recipe, chunkName); } catch { return ""; }
}

const breadcrumbs = computed(() => {
  if (!currentPath.value) return [];
  const parts = currentPath.value.split("/").filter(Boolean);
  const result: Array<{ name: string; path: string }> = [];
  let accum = "";
  for (const p of parts) {
    accum = accum ? `${accum}/${p}` : p;
    result.push({ name: p, path: accum });
  }
  return result;
});

function syncRouteQuery(): void {
  const nextQuery: Record<string, string> = { ...route.query } as Record<string, string>;
  if (activeSource.value) nextQuery.source = activeSource.value;
  if (selectedIdentity.value && selectedIdentity.value !== "game") {
    nextQuery.identity = selectedIdentity.value;
  } else {
    delete nextQuery.identity;
  }
  if (currentPath.value) {
    nextQuery.path = currentPath.value;
  } else {
    delete nextQuery.path;
  }
  if (props.searchQuery?.trim()) {
    nextQuery.q = props.searchQuery.trim();
  } else {
    delete nextQuery.q;
  }
  if (JSON.stringify(route.query) !== JSON.stringify(nextQuery)) {
    void router.replace({ query: nextQuery });
  }
}

async function loadFiles(path: string, append = false): Promise<void> {
  listController?.abort();
  const request = new AbortController();
  listController = request;
  const currentReq = ++requestId;

  if (append) {
    loadingMore.value = true;
  } else {
    loading.value = true;
  }
  error.value = null;

  try {
    const q = props.searchQuery?.trim() || undefined;
    const cursor = append ? filePage.value?.next_cursor : undefined;
    const res = await api.versionFiles(
      props.domainId,
      props.version,
      {
        source: activeSource.value,
        identity: selectedIdentity.value,
        path: path || undefined,
        q,
        limit: 100,
        cursor,
      },
      request.signal,
    );

    if (currentReq !== requestId) return;

    if (append && filePage.value) {
      filePage.value = {
        ...res,
        items: [...filePage.value.items, ...res.items],
      };
    } else {
      filePage.value = res;
    }
    syncRouteQuery();
  } catch (err) {
    if (isAbortError(err) || currentReq !== requestId) return;
    error.value = err instanceof Error ? err.message : "读取文件列表失败";
  } finally {
    if (currentReq === requestId) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

function setSource(src: "package" | "chunk"): void {
  if (activeSource.value === src) return;
  activeSource.value = src;
  currentPath.value = "";
  if (src === "package") {
    selectedIdentity.value = "game";
  }
  void loadFiles("");
}

function selectIdentity(id: string): void {
  if (selectedIdentity.value === id) return;
  selectedIdentity.value = id;
  currentPath.value = "";
  void loadFiles("");
}

function navigateToPath(path: string): void {
  currentPath.value = path;
  void loadFiles(path);
}

function goUp(): void {
  const parts = currentPath.value.split("/").filter(Boolean);
  parts.pop();
  const newPath = parts.join("/");
  navigateToPath(newPath);
}

async function openFileDetail(item: ChunkFileItem): Promise<void> {
  const generation = ++detailGeneration;
  downloadController.value?.abort();
  downloadController.value = null;
  downloadProgress.value = null;
  downloadError.value = null;
  downloading.value = false;
  selectedFile.value = item;
  showDetailModal.value = true;
  fileDetailLoading.value = true;
  fileDetailError.value = null;
  fileDetail.value = null;

  detailController?.abort();
  const request = new AbortController();
  detailController = request;

  try {
    const detail = await api.versionFileDetail(
      props.domainId,
      props.version,
      {
        source: activeSource.value,
        identity: selectedIdentity.value,
        path: item.path,
      },
      request.signal,
    );
    if (generation === detailGeneration) fileDetail.value = detail;
  } catch (err) {
    if (isAbortError(err) || generation !== detailGeneration) return;
    fileDetailError.value = err instanceof Error ? err.message : "获取文件明细失败";
  } finally {
    if (generation === detailGeneration) fileDetailLoading.value = false;
  }
}

function closeModal(): void {
  detailGeneration += 1;
  downloadController.value?.abort();
  downloadController.value = null;
  downloading.value = false;
  showDetailModal.value = false;
  selectedFile.value = null;
  fileDetail.value = null;
  downloadProgress.value = null;
  downloadError.value = null;
  detailController?.abort();
}

async function downloadCompleteFile(): Promise<void> {
  if (!fileDetail.value || downloading.value) return;
  if (fileDetail.value.size > MAX_BROWSER_SYNTHESIS_SIZE) {
    downloadError.value = "文件超过 512 MiB，暂不支持浏览器合成";
    return;
  }
  downloadController.value?.abort();
  const controller = new AbortController();
  downloadController.value = controller;
  downloading.value = true;
  downloadError.value = null;
  const chunks = fileDetail.value.chunks || [];
  downloadProgress.value = { completed: 0, total: chunks.length, receivedBytes: 0, totalBytes: chunks.reduce((sum, chunk) => sum + chunk.size, 0) };
  try {
    const blob = await synthesizeChunkFile(fileDetail.value, controller.signal, (progress) => { downloadProgress.value = progress; }, (chunk) => chunkContentUrl(props.domainId, props.version, selectedIdentity.value, chunk.name));
    const filename = fileDetail.value.path.split("/").filter(Boolean).pop() || "download.bin";
    saveBlob(blob, filename);
  } catch (err) {
    if (!isAbortError(err)) downloadError.value = err instanceof ChunkDownloadError || err instanceof Error ? err.message : "完整文件合成失败";
  } finally {
    if (downloadController.value === controller) {
      downloadController.value = null;
      downloading.value = false;
    }
  }
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && showDetailModal.value) {
    closeModal();
  }
}

function initFromRoute(): void {
  const reqSource = String(route.query.source || "");
  if (reqSource === "chunk" && hasChunk.value) {
    activeSource.value = "chunk";
  } else if (reqSource === "package" && hasPackage.value) {
    activeSource.value = "package";
  } else {
    activeSource.value = resolveDefaultSource();
  }

  const reqIdentity = String(route.query.identity || "");
  if (reqIdentity && identities.value.some((i) => i.key === reqIdentity)) {
    selectedIdentity.value = reqIdentity;
  } else if (identities.value.length > 0) {
    selectedIdentity.value = identities.value[0].key;
  }

  const reqPath = String(route.query.path || "");
  currentPath.value = reqPath;
}

// Watchers
watch(
  () => [props.domainId, props.version],
  () => {
    initFromRoute();
    void loadFiles(currentPath.value);
  },
);

watch(
  () => props.searchQuery,
  () => {
    void loadFiles(currentPath.value);
  },
);

onMounted(() => {
  initFromRoute();
  void loadFiles(currentPath.value);
  window.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  listController?.abort();
  detailController?.abort();
  downloadController.value?.abort();
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <div class="cfb-wrapper">
    <!-- 顶部工具栏：来源模式切换 (当该版本同时具有 Package 和 Chunk 时显示) 与组件身份 -->
    <div class="cfb-top-toolbar">
      <!-- 来源选择：完整包散文件 vs Chunk 蓝图 -->
      <div v-if="hasPackage && hasChunk" class="cfb-source-switch-group">
        <span class="cfb-toolbar-label">数据来源</span>
        <div class="cfb-source-pills">
          <button
            type="button"
            class="cfb-source-pill"
            :class="{ active: activeSource === 'package' }"
            @click="setSource('package')"
          >
            <span>📦 完整包直链 (Package)</span>
          </button>
          <button
            type="button"
            class="cfb-source-pill"
            :class="{ active: activeSource === 'chunk' }"
            @click="setSource('chunk')"
          >
            <span>🧩 Chunk 分块蓝图 (Chunk)</span>
          </button>
        </div>
      </div>

      <!-- 组件/语音包分类切换栏 (Chunk 模式多分类时展示) -->
      <div v-if="identities.length > 1" class="cfb-identities-row">
        <span class="cfb-toolbar-label">组件清单</span>
        <div class="cfb-identity-chips">
          <button
            v-for="item in identities"
            :key="item.key"
            type="button"
            class="cfb-chip"
            :class="{ active: selectedIdentity === item.key }"
            @click="selectIdentity(item.key)"
          >
            <span class="cfb-chip-dot"></span>
            <span>{{ item.label }}</span>
            <b v-if="item.count > 0">{{ item.count.toLocaleString() }}</b>
          </button>
        </div>
      </div>
    </div>

    <!-- 面包屑导航与目录状态栏 -->
    <div class="cfb-navbar">
      <div class="cfb-breadcrumbs">
        <button
          type="button"
          class="cfb-crumb-root"
          :class="{ active: !breadcrumbs.length }"
          @click="navigateToPath('')"
        >
          <svg viewBox="0 0 24 24" class="cfb-crumb-icon" aria-hidden="true">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          </svg>
          <span>根目录</span>
        </button>

        <template v-for="(crumb, idx) in breadcrumbs" :key="crumb.path">
          <span class="cfb-crumb-sep">/</span>
          <button
            type="button"
            class="cfb-crumb-item"
            :class="{ active: idx === breadcrumbs.length - 1 }"
            @click="navigateToPath(crumb.path)"
          >
            {{ crumb.name }}
          </button>
        </template>

        <button
          v-if="breadcrumbs.length > 0"
          type="button"
          class="cfb-up-btn"
          title="返回上一级目录"
          @click="goUp()"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          <span>上一级</span>
        </button>
      </div>

      <div class="cfb-nav-stats-group">
        <div v-if="filePage?.totals" class="cfb-nav-stats">
          <span>当前目录：</span>
          <strong v-if="filePage.totals.directories > 0">{{ filePage.totals.directories }} 个文件夹</strong>
          <span v-if="filePage.totals.directories > 0 && filePage.totals.files > 0">/</span>
          <strong>{{ filePage.totals.files }} 个文件</strong>
          <span class="cfb-meta-dot">·</span>
          <span class="cfb-stats-size">{{ formatBytes(filePage.totals.size) }}</span>
        </div>
        <div v-else-if="props.searchQuery" class="cfb-nav-stats">
          <span>搜索结果：<strong>{{ filePage?.items.length || 0 }} 个匹配项</strong></span>
        </div>

        <span v-if="filePage?.network_bytes === 0" class="cfb-cache-badge" title="数据已从本地快速解析缓存提供">
          ⚡ 命中缓存
        </span>
      </div>
    </div>

    <!-- 加载中状态 -->
    <div v-if="loading" class="cfb-state-box">
      <div class="cfb-spinner"></div>
      <p>正在读取并解析文件索引…</p>
    </div>

    <!-- 资源失效状态 -->
    <div v-else-if="error && isUnavailablePackage" class="cfb-state-box cfb-unavail-box">
      <svg viewBox="0 0 24 24" class="cfb-empty-icon" aria-hidden="true">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        <line x1="2" y1="2" x2="22" y2="22" />
      </svg>
      <div class="cfb-unavail-texts">
        <strong>官方资源已失效下架</strong>
        <p>该版本的官方完整包下载链接已失效，无法读取文件列表</p>
      </div>
    </div>

    <!-- 普通错误状态 -->
    <div v-else-if="error" class="cfb-state-box cfb-error-box">
      <strong>文件目录读取失败</strong>
      <span>{{ error }}</span>
      <button class="tool-button cfb-retry-btn" type="button" @click="loadFiles(currentPath)">
        重试
      </button>
    </div>

    <!-- 空数据 -->
    <div v-else-if="!filePage?.items.length" class="cfb-state-box cfb-empty-box">
      <svg viewBox="0 0 24 24" class="cfb-empty-icon" aria-hidden="true">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
      </svg>
      <p>{{ props.searchQuery ? `未找到匹配 "${props.searchQuery}" 的文件` : '当前目录为空' }}</p>
    </div>

    <!-- 文件与目录网格列表 -->
    <div v-else class="cfb-table-container">
      <div class="cfb-grid-table">
        <!-- 表头 Header Row -->
        <div class="cfb-grid-header">
          <div class="cfb-col cfb-col-name">名称</div>
          <div class="cfb-col cfb-col-size">大小</div>
          <div class="cfb-col cfb-col-chunks">结构 / 分块</div>
          <div class="cfb-col cfb-col-hash">MD5 校验值</div>
          <div class="cfb-col cfb-col-action">操作</div>
        </div>

        <!-- 列表 Rows -->
        <div class="cfb-grid-body">
          <div
            v-for="item in filePage.items"
            :key="item.path"
            class="cfb-grid-row"
            :class="item.type === 'directory' ? 'row-is-dir' : 'row-is-file'"
            @click="item.type === 'directory' ? navigateToPath(item.path) : openFileDetail(item)"
          >
            <!-- 1. 名称列 -->
            <div class="cfb-col cfb-col-name">
              <div class="cfb-name-block">
                <span v-if="item.type === 'directory'" class="cfb-type-icon dir-icon">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3 6.5h6l2 2h10v9H3z" />
                  </svg>
                </span>
                <span v-else class="cfb-type-icon file-icon">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </span>

                <div class="cfb-name-texts">
                  <strong class="cfb-main-name">{{ item.name }}</strong>
                  <span v-if="props.searchQuery && item.path !== item.name" class="cfb-sub-path">
                    {{ item.path }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 2. 大小列 -->
            <div class="cfb-col cfb-col-size mono-text">
              {{ formatBytes(item.size || 0) }}
            </div>

            <!-- 3. 分块数 / 子文件数 -->
            <div class="cfb-col cfb-col-chunks">
              <span v-if="item.type === 'directory'" class="cfb-badge-dir">
                {{ (item.file_count || 0).toLocaleString() }} 个文件
              </span>
              <span v-else-if="item.chunk_count !== null && item.chunk_count !== undefined" class="cfb-badge-file">
                {{ item.chunk_count.toLocaleString() }} 块
              </span>
              <span v-else-if="item.download_url" class="cfb-badge-pkg">
                官方直链
              </span>
              <span v-else class="cfb-dim-text">—</span>
            </div>

            <!-- 4. MD5 哈希列 -->
            <div class="cfb-col cfb-col-hash">
              <code
                v-if="item.md5 || item.hash"
                class="cfb-hash-code"
                title="点击复制 MD5 校验值"
                @click.stop="copyText(item.md5 || item.hash || '', 'MD5')"
              >
                {{ item.md5 || item.hash }}
              </code>
              <span v-else class="cfb-dim-text">—</span>
            </div>

            <!-- 5. 操作列 -->
            <div class="cfb-col cfb-col-action" @click.stop>
              <button
                v-if="item.type === 'directory'"
                type="button"
                class="cfb-act-btn dir-act"
                @click="navigateToPath(item.path)"
              >
                <span>进入目录</span>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
              <template v-else>
                <div class="cfb-row-action-group">
                  <a
                    v-if="item.download_url"
                    class="cfb-act-btn dl-act"
                    :href="item.download_url"
                    target="_blank"
                    rel="noreferrer"
                    title="在浏览器中直接下载该文件"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    <span>下载</span>
                  </a>
                  <button
                    v-if="item.download_url"
                    type="button"
                    class="cfb-act-btn copy-act"
                    title="复制文件下载直链"
                    @click="copyText(item.download_url, '直链')"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <rect x="9" y="9" width="11" height="11" rx="2" />
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                    </svg>
                    <span>复制</span>
                  </button>
                  <button
                    v-else
                    type="button"
                    class="cfb-act-btn file-act"
                    @click="openFileDetail(item)"
                  >
                    <span>查看分块</span>
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <circle cx="12" cy="12" r="3" />
                      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                    </svg>
                  </button>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 分页加载按钮 -->
      <div v-if="filePage?.next_cursor" class="cfb-pagination-bar">
        <button
          type="button"
          class="cfb-loadmore-btn"
          :disabled="loadingMore"
          @click="loadFiles(currentPath, true)"
        >
          {{ loadingMore ? '正在载入更多条目…' : '加载下一页文件' }}
        </button>
      </div>
    </div>

    <!-- 单文件明细弹窗 (Modal) -->
    <Teleport to="body">
      <div
        v-if="showDetailModal"
        class="cfb-modal-overlay"
        @click.self="closeModal()"
      >
        <div class="cfb-modal-card">
          <!-- 弹窗头部 -->
          <div class="cfb-modal-top">
            <div class="cfb-modal-head-title">
              <span class="cfb-modal-tag">{{ fileDetail?.chunks?.length ? 'Chunk 分块蓝图' : '官方完整文件' }}</span>
              <h3 class="cfb-modal-title-text">{{ selectedFile?.name }}</h3>
            </div>
            <button
              type="button"
              class="cfb-modal-close"
              title="关闭 (Esc)"
              @click="closeModal()"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <!-- 弹窗元信息格点 -->
          <div class="cfb-modal-meta-grid">
            <div class="cfb-meta-item">
              <span class="cfb-meta-label">文件相对路径</span>
              <code
                class="cfb-meta-code-val"
                title="点击复制完整路径"
                @click="copyText(selectedFile?.path || '', '文件路径')"
              >
                {{ selectedFile?.path }}
              </code>
            </div>
            <div class="cfb-meta-item">
              <span class="cfb-meta-label">解压总体积</span>
              <span class="cfb-meta-val-bold mono-text">{{ formatBytes(selectedFile?.size || 0) }}</span>
            </div>
            <div class="cfb-meta-item">
              <span class="cfb-meta-label">完整 MD5 校验</span>
              <code
                class="cfb-meta-code-val"
                title="点击复制 MD5"
                @click="copyText(selectedFile?.md5 || selectedFile?.hash || '', 'MD5')"
              >
                {{ selectedFile?.md5 || selectedFile?.hash || '—' }}
              </code>
            </div>
            <div class="cfb-meta-item">
              <span class="cfb-meta-label">{{ fileDetail?.chunks?.length ? '分块数量' : '数据源' }}</span>
              <span v-if="fileDetail?.chunks?.length" class="cfb-meta-val-highlight font-mono">{{ fileDetail.chunks.length.toLocaleString() }} 块</span>
              <span v-else class="cfb-meta-val-highlight font-mono">官方散文件直链</span>
            </div>
          </div>

          <!-- 弹窗主体：Package 直链下载 或 Chunk 列表 -->
          <div class="cfb-modal-body">
            <div v-if="fileDetailLoading" class="cfb-modal-status-box">
              <div class="cfb-spinner"></div>
              <p>正在读取文件明细与下载信息…</p>
            </div>

            <div v-else-if="fileDetailError" class="cfb-modal-status-box cfb-error-box">
              <strong>文件明细加载失败</strong>
              <span>{{ fileDetailError }}</span>
            </div>

            <!-- 情况 1: Package 官方直链 -->
            <div v-else-if="fileDetail?.download_url || selectedFile?.download_url" class="cfb-pkg-detail-box">
              <div class="cfb-pkg-url-card">
                <div class="cfb-pkg-url-head">
                  <span class="cfb-pkg-url-badge">HTTP 官方直链</span>
                  <span class="cfb-dim-text">支持多线程下载加速</span>
                </div>
                <div class="cfb-pkg-url-row">
                  <input
                    type="text"
                    readonly
                    class="cfb-pkg-url-input"
                    :value="fileDetail?.download_url || selectedFile?.download_url"
                  />
                  <button
                    type="button"
                    class="tool-button copy-btn"
                    @click="copyText(fileDetail?.download_url || selectedFile?.download_url || '', '下载直链')"
                  >
                    复制直链
                  </button>
                  <a
                    class="tool-button dl-btn"
                    :href="fileDetail?.download_url || selectedFile?.download_url"
                    target="_blank"
                    rel="noreferrer"
                  >
                    立即下载
                  </a>
                </div>
              </div>
            </div>

            <!-- 情况 2: Chunk 物理分块列表 -->
            <div v-else-if="fileDetail?.chunks?.length || (fileDetail?.chunk_download && fileDetail.size === 0)" class="cfb-chunks-container">
              <div v-if="fileDetail?.chunk_download" class="cfb-complete-download">
                <button type="button" class="tool-button dl-btn" :disabled="downloading" @click="downloadCompleteFile">
                  {{ downloading ? '正在合成…' : '下载完整文件' }}
                </button>
                <button v-if="downloading" type="button" class="tool-button copy-btn" @click="downloadController?.abort()">取消</button>
                <span v-if="downloadProgress" class="cfb-download-progress">
                  {{ downloadProgress.completed }}/{{ downloadProgress.total }} 块 · {{ formatBytes(downloadProgress.receivedBytes) }}/{{ formatBytes(downloadProgress.totalBytes) }}
                </span>
                <span v-if="downloadError" class="cfb-download-error">{{ downloadError }}</span>
              </div>
              <div class="cfb-chunk-grid-header">
                <div class="c-col c-col-num">#</div>
                <div class="c-col c-col-hash">Chunk 校验值 (Hash)</div>
                <div class="c-col c-col-offset">偏移量 (Offset)</div>
                <div class="c-col c-col-size">压缩体积</div>
                <div class="c-col c-col-decomp">解压体积</div>
                <div class="c-col c-col-act">操作</div>
              </div>

              <div class="cfb-chunk-grid-body">
                <div
                  v-for="(chunk, idx) in fileDetail.chunks"
                  :key="chunk.hash || idx"
                  class="cfb-chunk-grid-row"
                >
                  <div class="c-col c-col-num cfb-dim-text">{{ idx + 1 }}</div>
                  <div class="c-col c-col-hash">
                    <code
                      class="cfb-hash-code"
                      title="点击复制 Chunk Hash"
                      @click="copyText(chunk.hash, 'Chunk Hash')"
                    >
                      {{ chunk.hash }}
                    </code>
                  </div>
                  <div class="c-col c-col-offset mono-text cfb-dim-text">
                    {{ formatBytes(chunk.offset) }} ({{ chunk.offset.toLocaleString() }})
                  </div>
                  <div class="c-col c-col-size mono-text">
                    {{ formatBytes(chunk.size) }}
                  </div>
                  <div class="c-col c-col-decomp mono-text cfb-highlight-cyan">
                    {{ formatBytes(chunk.size_decompressed) }}
                  </div>
                  <div class="c-col c-col-act">
                    <div class="cfb-chunk-acts">
                      <button
                        v-if="chunkDownloadUrl(chunk.name)"
                        type="button"
                        class="cfb-mini-btn copy-btn"
                        title="复制 Chunk 下载直链"
                        @click="copyText(chunkDownloadUrl(chunk.name), 'Chunk 直链')"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <rect x="9" y="9" width="11" height="11" rx="2" />
                          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                        </svg>
                        <span>复制</span>
                      </button>
                      <a
                        v-if="chunkDownloadUrl(chunk.name)"
                        class="cfb-mini-btn dl-btn"
                        :href="chunkDownloadUrl(chunk.name)"
                        target="_blank"
                        rel="noreferrer"
                        title="在浏览器中直接下载该 Chunk 分块"
                      >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                        <span>下载</span>
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 弹窗底部 -->
          <div class="cfb-modal-bottom">
            <span class="cfb-foot-note">
              {{ fileDetail?.chunks?.length ? '* Chunk 数据使用 LZ4 / ZSTD 压缩算法。下载后按 Manifest 蓝图解压即可还原为该文件的对应扇区。' : '* 官方散文件直链来自米哈游官方下载服务器，无需解压即可直接提取使用。' }}
            </span>
            <button
              type="button"
              class="tool-button cfb-modal-done"
              @click="closeModal()"
            >
              完成并关闭
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 复制轻提示 Toast -->
    <Transition name="fade">
      <div v-if="toastMessage" class="cfb-toast">
        {{ toastMessage }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.cfb-wrapper {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  box-sizing: border-box;
}

/* --- 顶部工具栏 --- */
.cfb-top-toolbar {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cfb-toolbar-label {
  font-size: 11.5px;
  font-weight: 750;
  color: var(--muted);
  white-space: nowrap;
  letter-spacing: 0.02em;
}

/* 来源选择器 (Package vs Chunk) */
.cfb-source-switch-group {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.07);
}

.cfb-source-pills {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cfb-source-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.cfb-source-pill:hover {
  background: rgba(56, 189, 248, 0.08);
  color: #f1f5f9;
  border-color: rgba(56, 189, 248, 0.3);
}

.cfb-source-pill.active {
  background: rgba(56, 189, 248, 0.18);
  border-color: #38bdf8;
  color: #38bdf8;
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.25);
  font-weight: 750;
}

/* 身份切换栏 */
.cfb-identities-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.cfb-identity-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cfb-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.cfb-chip:hover {
  background: rgba(56, 189, 248, 0.08);
  color: #f1f5f9;
  border-color: rgba(56, 189, 248, 0.3);
}

.cfb-chip.active {
  background: rgba(56, 189, 248, 0.16);
  border-color: #38bdf8;
  color: #38bdf8;
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.2);
}

.cfb-chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.3);
}

.cfb-chip.active .cfb-chip-dot {
  background: #38bdf8;
  box-shadow: 0 0 6px #38bdf8;
}

.cfb-chip b {
  font-family: var(--font-mono);
  font-size: 11px;
  opacity: 0.8;
}

/* --- 面包屑导航栏 --- */
.cfb-navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 16px;
  border-radius: 10px;
  background: rgba(14, 22, 35, 0.7);
  border: 1px solid var(--line-soft);
}

.cfb-breadcrumbs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.cfb-crumb-root,
.cfb-crumb-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  padding: 4px 8px;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cfb-crumb-root:hover,
.cfb-crumb-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #f1f5f9;
}

.cfb-crumb-root.active,
.cfb-crumb-item.active {
  color: #38bdf8;
  font-weight: 750;
}

.cfb-crumb-icon {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
}

.cfb-crumb-sep {
  color: rgba(255, 255, 255, 0.2);
  font-weight: 700;
  user-select: none;
}

.cfb-up-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  padding: 3px 9px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cfb-up-btn svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.5;
}

.cfb-up-btn:hover {
  background: rgba(255, 255, 255, 0.09);
  color: #f1f5f9;
  border-color: rgba(255, 255, 255, 0.2);
}

.cfb-nav-stats-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cfb-nav-stats {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}

.cfb-nav-stats strong {
  color: #cbd5e1;
}

.cfb-meta-dot {
  color: rgba(255, 255, 255, 0.2);
}

.cfb-stats-size {
  font-family: var(--font-mono);
  color: #93c5fd;
  font-weight: 750;
}

.cfb-cache-badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.12);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.25);
  font-weight: 700;
}

/* --- 状态容器 --- */
.cfb-state-box {
  width: 100%;
  padding: 56px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  border-radius: 10px;
  background: rgba(14, 22, 35, 0.5);
  border: 1px solid var(--line-soft);
  color: var(--muted);
  font-size: 13px;
  box-sizing: border-box;
}

.cfb-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid rgba(56, 189, 248, 0.15);
  border-top-color: #38bdf8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.cfb-error-box strong {
  color: #fb7185;
  font-size: 14px;
}

.cfb-unavail-texts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  text-align: center;
}

.cfb-unavail-texts strong {
  color: #cbd5e1;
  font-size: 14.5px;
  font-weight: 700;
}

.cfb-unavail-texts p {
  margin: 0;
  color: #64748b;
  font-size: 12.5px;
}

.cfb-action-link-btn {
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid rgba(56, 189, 248, 0.25);
  background: rgba(56, 189, 248, 0.06);
  color: #38bdf8;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cfb-action-link-btn:hover {
  background: rgba(56, 189, 248, 0.16);
  border-color: #38bdf8;
  color: #fff;
}

.cfb-action-link-btn svg {
  width: 12px;
  height: 12px;
  stroke: currentColor;
  stroke-width: 2.5;
  fill: none;
}

.cfb-empty-icon {
  width: 36px;
  height: 36px;
  stroke: rgba(255, 255, 255, 0.2);
  fill: none;
  stroke-width: 1.5;
}

/* --- 文件与目录表格 (CSS Grid 架构) --- */
.cfb-table-container {
  width: 100%;
  border-radius: 10px;
  border: 1px solid var(--line-soft);
  background: rgba(14, 22, 35, 0.5);
  overflow-x: auto;
}

.cfb-grid-table {
  min-width: 860px;
  display: flex;
  flex-direction: column;
  width: 100%;
}

.cfb-grid-header {
  display: grid;
  grid-template-columns: minmax(260px, 3.2fr) 120px 130px minmax(220px, 2fr) 150px;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  background: rgba(10, 16, 26, 0.85);
  border-bottom: 1px solid var(--line-soft);
}

.cfb-grid-header .cfb-col {
  font-size: 11.5px;
  font-weight: 750;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  white-space: nowrap;
}

.cfb-grid-body {
  display: flex;
  flex-direction: column;
}

.cfb-grid-row {
  display: grid;
  grid-template-columns: minmax(260px, 3.2fr) 120px 130px minmax(220px, 2fr) 150px;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  transition: background 0.15s ease;
  cursor: pointer;
}

.cfb-grid-row:hover {
  background: rgba(56, 189, 248, 0.04);
}

.cfb-col-name { min-width: 0; }
.cfb-col-size { white-space: nowrap; }
.cfb-col-chunks { white-space: nowrap; }
.cfb-col-hash { min-width: 0; overflow: hidden; }
.cfb-col-action { display: flex; justify-content: flex-end; }

.cfb-name-block {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.cfb-type-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  flex-shrink: 0;
}

.dir-icon {
  background: rgba(245, 158, 11, 0.14);
  color: #fbbf24;
}

.file-icon {
  background: rgba(56, 189, 248, 0.12);
  color: #38bdf8;
}

.cfb-type-icon svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
}

.cfb-name-texts {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cfb-main-name {
  color: #f1f5f9;
  font-weight: 650;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-is-dir .cfb-main-name {
  color: #fbbf24;
}

.cfb-sub-path {
  font-size: 11px;
  color: var(--muted);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono-text {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: #cbd5e1;
  font-weight: 600;
}

.cfb-badge-dir {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(245, 158, 11, 0.12);
  color: #fcd34d;
  font-weight: 650;
}

.cfb-badge-file {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.12);
  color: #7dd3fc;
  font-family: var(--font-mono);
  font-weight: 650;
}

.cfb-badge-pkg {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.12);
  color: #34d399;
  font-weight: 650;
}

.cfb-hash-code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #94a3b8;
  background: rgba(0, 0, 0, 0.35);
  padding: 3px 7px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.cfb-hash-code:hover {
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.14);
}

.cfb-dim-text {
  color: var(--muted);
}

.cfb-row-action-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cfb-act-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
  text-decoration: none;
  transition: all 0.15s ease;
}

.dir-act {
  border: 1px solid rgba(245, 158, 11, 0.3);
  background: rgba(245, 158, 11, 0.08);
  color: #fbbf24;
}

.dir-act:hover {
  background: rgba(245, 158, 11, 0.18);
  color: #fff;
}

.file-act {
  border: 1px solid rgba(56, 189, 248, 0.25);
  background: rgba(56, 189, 248, 0.06);
  color: #38bdf8;
}

.file-act:hover {
  background: rgba(56, 189, 248, 0.16);
  color: #fff;
  border-color: #38bdf8;
}

.dl-act {
  border: 1px solid rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.1);
  color: #34d399;
}

.dl-act:hover {
  background: #10b981;
  color: #0b1320;
}

.copy-act {
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: #cbd5e1;
}

.copy-act:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.cfb-act-btn svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.2;
}

.cfb-pagination-bar {
  padding: 12px;
  display: flex;
  justify-content: center;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.cfb-loadmore-btn {
  padding: 6px 22px;
  border-radius: 6px;
  border: 1px solid rgba(56, 189, 248, 0.3);
  background: rgba(56, 189, 248, 0.08);
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cfb-loadmore-btn:hover:not(:disabled) {
  background: rgba(56, 189, 248, 0.18);
  color: #f1f5f9;
}

/* --- 单文件明细弹窗 (Modal) --- */
.cfb-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(5, 10, 20, 0.82);
  backdrop-filter: blur(12px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  box-sizing: border-box;
}

.cfb-modal-card {
  width: 100%;
  max-width: 980px;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  background: #0d1524;
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.75);
  overflow: hidden;
  box-sizing: border-box;
}

.cfb-modal-top {
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(15, 23, 42, 0.8);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.cfb-modal-head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.cfb-modal-tag {
  font-size: 11px;
  font-weight: 750;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.cfb-modal-title-text {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: #f1f5f9;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cfb-modal-close {
  background: transparent;
  border: none;
  color: var(--muted);
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cfb-modal-close svg {
  width: 18px;
  height: 18px;
  stroke: currentColor;
  stroke-width: 2.2;
}

.cfb-modal-close:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.cfb-modal-meta-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1.5fr 1fr;
  gap: 8px;
  padding: 12px 20px;
  background: rgba(10, 16, 26, 0.6);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.cfb-meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.cfb-meta-label {
  font-size: 10.5px;
  font-weight: 700;
  color: var(--muted);
}

.cfb-meta-val-bold {
  font-size: 13px;
  font-weight: 700;
  color: #f1f5f9;
}

.cfb-meta-code-val {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #93c5fd;
  background: rgba(0, 0, 0, 0.3);
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cfb-meta-val-highlight {
  font-size: 13px;
  font-weight: 700;
  color: #38bdf8;
}

.cfb-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.cfb-modal-status-box {
  padding: 36px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--muted);
}

/* Package 直链下载容器 */
.cfb-pkg-detail-box {
  padding: 20px 0;
}

.cfb-pkg-url-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 18px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.cfb-pkg-url-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cfb-pkg-url-badge {
  font-size: 11.5px;
  font-weight: 750;
  color: #34d399;
}

.cfb-pkg-url-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cfb-pkg-url-input {
  flex: 1;
  min-width: 0;
  height: 34px;
  padding: 0 12px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  font-family: var(--font-mono);
  font-size: 12px;
  outline: none;
}

/* Chunk 容器 */
.cfb-chunks-container {
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
  overflow-x: auto;
}

.cfb-chunk-grid-header,
.cfb-chunk-grid-body { min-width: 760px; }

.cfb-complete-download {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.cfb-download-progress { color: var(--muted); font-size: 11.5px; font-family: var(--font-mono); }
.cfb-download-error { flex-basis: 100%; color: #fb7185; font-size: 12px; }

.cfb-chunk-grid-header {
  display: grid;
  grid-template-columns: 40px minmax(220px, 2.5fr) 140px 110px 110px 140px;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  background: rgba(15, 23, 42, 0.9);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 11px;
  font-weight: 750;
  color: var(--muted);
  white-space: nowrap;
}

.cfb-chunk-grid-body {
  display: flex;
  flex-direction: column;
}

.cfb-chunk-grid-row {
  display: grid;
  grid-template-columns: 40px minmax(220px, 2.5fr) 140px 110px 110px 140px;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  transition: background 0.15s ease;
}

.cfb-chunk-grid-row:hover {
  background: rgba(56, 189, 248, 0.05);
}

.c-col-act {
  display: flex;
  justify-content: flex-end;
}

.cfb-chunk-acts {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cfb-mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.15s ease;
}

.copy-btn {
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: #cbd5e1;
}

.copy-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.dl-btn {
  border: 1px solid rgba(56, 189, 248, 0.3);
  background: rgba(56, 189, 248, 0.1);
  color: #38bdf8;
}

.dl-btn:hover {
  background: #38bdf8;
  color: #0b1320;
}

.cfb-mini-btn svg {
  width: 11px;
  height: 11px;
  stroke: currentColor;
  stroke-width: 2.2;
}

.cfb-highlight-cyan {
  color: #38bdf8;
}

.cfb-modal-bottom {
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(10, 16, 26, 0.8);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.cfb-foot-note {
  font-size: 11.5px;
  color: var(--muted);
}

.cfb-modal-done {
  padding: 6px 16px;
  font-size: 12.5px;
}

/* Toast */
.cfb-toast {
  position: fixed;
  bottom: 30px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid #38bdf8;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
  color: #f1f5f9;
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 650;
  z-index: 10000;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translate(-50%, 10px);
}

@media (max-width: 860px) {
  /* 1. 顶部工具栏与数据源切换 */
  .cfb-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }

  .cfb-source-switch {
    width: 100%;
    display: flex;
    gap: 6px;
  }

  .cfb-source-pill {
    flex: 1 1 0;
    min-height: 36px;
    padding: 0 8px;
    font-size: 11.5px;
    justify-content: center;
    text-align: center;
  }

  .cfb-identities-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }

  .cfb-identity-chips {
    width: 100%;
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
    flex-wrap: nowrap;
    padding-bottom: 2px;
  }

  .cfb-identity-chips::-webkit-scrollbar {
    display: none;
  }

  /* 2. 面包屑与导航状态栏 */
  .cfb-navbar {
    padding: 8px 10px;
    gap: 8px;
  }

  .cfb-breadcrumbs {
    width: 100%;
    overflow-x: auto;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
    flex-wrap: nowrap;
    white-space: nowrap;
  }

  .cfb-nav-stats-group {
    width: 100%;
    justify-content: space-between;
    font-size: 11.5px;
  }

  /* 3. 表格与文件列表自适应 */
  .cfb-table-container {
    border-radius: 8px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .cfb-grid-table {
    min-width: 620px;
  }

  .cfb-grid-header,
  .cfb-grid-row {
    grid-template-columns: minmax(180px, 2.5fr) 90px 100px minmax(120px, 1.2fr) 110px;
    padding: 8px 12px;
    gap: 8px;
  }

  .cfb-main-name {
    font-size: 12.5px;
  }

  .cfb-act-btn {
    padding: 4px 8px;
    font-size: 11px;
  }

  /* 4. 单文件明细弹窗移动端适配 */
  .cfb-modal-overlay {
    padding: 10px;
    align-items: flex-end;
  }

  .cfb-modal-card {
    max-height: 92vh;
    border-radius: 14px 14px 0 0;
    max-width: 100%;
  }

  .cfb-modal-meta-grid {
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    padding: 12px;
  }

  .cfb-meta-card {
    padding: 8px 10px;
  }

  .cfb-meta-val {
    font-size: 12.5px;
  }

  .cfb-chunk-grid-table {
    min-width: 580px;
  }

  .cfb-chunk-grid-header,
  .cfb-chunk-grid-row {
    grid-template-columns: 32px minmax(130px, 2fr) 90px 75px 75px 95px;
    padding: 6px 10px;
    gap: 6px;
  }
}

@media (max-width: 480px) {
  .cfb-modal-meta-grid {
    grid-template-columns: 1fr;
  }

  .cfb-grid-table {
    min-width: 540px;
  }
}
</style>
