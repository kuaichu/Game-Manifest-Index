<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, isAbortError } from "../api";
import { copyTextToClipboard } from "../clipboard";
import { formatBytes, hoyoLanguageLabel, isChunkOnlyVersion, repairMojibake } from "../domain-presentation";
import { saveBlob } from "../chunk-download";
import { downloadChunkDirectory, type DirectoryDownloadProgress } from "../chunk-directory-download";
import { downloadSelectedFiles, selectedFileExport, selectedFilePlan, type SelectedFileContext } from "../selected-file-download";
import ChunkFileDetailModal from "./chunk/ChunkFileDetailModal.vue";
import type {
  ArchiveDomain,
  ChunkFileItem,
  ChunkFilesPage,
  ChunkManifestDetail,
  ChunkManifestEntry,
  ChunkManifestSummaryItem,
  Game,
  FileTimeChange,
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

const emit = defineEmits<{
  (e: "file-time-change", value: FileTimeChange): void;
}>();

const route = useRoute();
const router = useRouter();

// Source resolution (package vs chunk vs auto)
const hasPackage = computed(() => {
  const kinds = props.versionSummary?.artifact_kinds;
  return Boolean(
    kinds?.package?.count ||
      kinds?.file?.count ||
      (props.domain?.capabilities?.includes("packages")
        && props.domain?.adapter === "hoyo"
        && !isChunkOnlyVersion(props.versionSummary)),
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
const pageIndex = ref(0);
const pageCursors = ref<Array<string | undefined>>([undefined]);
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

// File Detail Modal State
const selectedFile = ref<ChunkFileItem | null>(null);
const showDetailModal = ref<boolean>(false);
const toastMessage = ref<string>("");
const downloading = ref(false);
const directoryPanelOpen = ref(false);
const directoryIdentities = ref<string[]>([]);
const directoryController = ref<AbortController | null>(null);
const directoryProgress = ref<DirectoryDownloadProgress | null>(null);
const directoryMessage = ref("");
const directoryError = ref("");
const directoryDownloading = ref(false);
const selectedFiles = ref(new Map<string, number>());
const selectedPaths = computed(() => [...selectedFiles.value.keys()]);
const selectedController = ref<AbortController | null>(null);
const selectedBusy = ref(false);
const selectedProgress = ref<DirectoryDownloadProgress | null>(null);
const selectedMessage = ref("");
const selectedError = ref("");
const selectionHelpOpen = ref(false);
const loadedFiles = computed(() => filePage.value?.items.filter((item) => item.type !== "directory") || []);
const selectedSize = computed(() => [...selectedFiles.value.values()].reduce((sum, size) => sum + size, 0));
const allLoadedSelected = computed(() => loadedFiles.value.length > 0 && loadedFiles.value.every((item) => selectedFiles.value.has(item.path)));
const anyDownloadBusy = computed(() => selectedBusy.value || downloading.value || directoryDownloading.value);

function resetSelection(): void {
  selectedController.value?.abort();
  selectedController.value = null;
  selectedBusy.value = false;
  selectedFiles.value.clear();
  selectedProgress.value = null;
  selectedMessage.value = "";
  selectedError.value = "";
}

function toggleSelected(item: ChunkFileItem): void {
  if (selectedBusy.value) return;
  if (selectedFiles.value.has(item.path)) selectedFiles.value.delete(item.path);
  else selectedFiles.value.set(item.path, item.size || 0);
}

function toggleLoadedFiles(): void {
  if (selectedBusy.value) return;
  const clear = allLoadedSelected.value;
  for (const item of loadedFiles.value) {
    if (clear) selectedFiles.value.delete(item.path);
    else selectedFiles.value.set(item.path, item.size || 0);
  }
}

async function selectedAction(action: "download" | "copy" | "export"): Promise<void> {
  if (anyDownloadBusy.value || !selectedPaths.value.length) return;
  if (action === "download" && !canSaveDirectory.value) { selectedError.value = directoryUnavailableReason.value; return; }
  const controller = new AbortController();
  selectedController.value = controller;
  selectedBusy.value = true;
  selectedMessage.value = "";
  selectedError.value = "";
  selectedProgress.value = null;
  const context: SelectedFileContext = { domainId: props.domainId, version: props.version, source: activeSource.value,
    identity: selectedIdentity.value, paths: [...selectedPaths.value], signal: controller.signal, recipe: activeManifest.value?.chunk_download };
  const isCurrent = () => selectedController.value === controller && !controller.signal.aborted;
  try {
    if (action === "download") {
      const root = await (window as DownloadPickerWindow).showDirectoryPicker!({ mode: "readwrite" });
      if (!isCurrent()) return;
      const result = await downloadSelectedFiles({ ...context, root,
        baseName: `${props.game?.id || props.domain?.game_id || props.domainId}-${context.version}-selected`,
        onProgress: (progress) => { if (isCurrent()) selectedProgress.value = progress; } });
      if (isCurrent()) selectedMessage.value = `已保存 ${result.files} 个文件（${formatBytes(result.bytes)}）到 ${result.directoryName}`;
    } else {
      const files = await selectedFilePlan(context);
      if (!isCurrent()) return;
      const output = selectedFileExport(context, files);
      if (action === "copy") {
        const copied = await copyTextToClipboard(output.text);
        if (!isCurrent()) return;
        if (!copied) {
          selectedError.value = "复制失败，请手动复制或改用导出功能。";
          return;
        }
      } else {
        saveBlob(new Blob([output.text], { type: output.mime }), `selected-${context.version}.${output.extension}`);
      }
      if (isCurrent()) selectedMessage.value = `已${action === "copy" ? "复制" : "导出"} ${files.length} 个文件的${context.source === "chunk" ? "合成清单" : "官方直链"}`;
    }
  } catch (error) {
    if (selectedController.value === controller) {
      if (isAbortError(error)) selectedMessage.value = "操作已取消，已完成的文件保留在新建目录中。";
      else selectedError.value = `${error instanceof Error ? error.message : "所选文件操作失败"}。已完成的文件会保留。`;
    }
  } finally {
    if (selectedController.value === controller) { selectedController.value = null; selectedBusy.value = false; }
  }
}
type DownloadPickerWindow = Window & {
  showDirectoryPicker?: (options: { mode: "readwrite" }) => Promise<FileSystemDirectoryHandle>;
  showSaveFilePicker?: (options: { suggestedName: string }) => Promise<FileSystemFileHandle>;
};
const directoryUnavailableReason = computed(() => {
  if (typeof window === "undefined") return "当前环境无法选择本地目录。";
  if (window.isSecureContext === false) return "当前页面不是安全上下文，请通过 HTTPS 打开本站后下载游戏目录。";
  if (typeof (window as DownloadPickerWindow).showDirectoryPicker !== "function") {
    return "当前浏览器未提供目录选择功能，请改用支持该功能的桌面 Chrome 或 Edge。";
  }
  return "";
});
const canSaveDirectory = computed(() => !directoryUnavailableReason.value);
const canSaveFile = computed(() => typeof window !== "undefined" && typeof (window as DownloadPickerWindow).showSaveFilePicker === "function");

let listController: AbortController | null = null;
let requestId = 0;
let toastTimer: number | null = null;

async function copyText(text: string, label: string): Promise<void> {
  if (!text) return;
  const copied = await copyTextToClipboard(text);
  if (toastTimer !== null) window.clearTimeout(toastTimer);
  toastMessage.value = copied ? `已复制 ${label}` : "复制失败，请手动复制";
  toastTimer = window.setTimeout(() => {
    toastMessage.value = "";
    toastTimer = null;
  }, 2000);
}

function manifestLabel(manifest: ChunkManifestEntry): string {
  const label = repairMojibake(manifest.category?.name || "").trim();
  if (label && !/^(null|undefined)$/i.test(label)) return label;
  if (manifest.component === "game") return "游戏主资源";
  if (manifest.language) return `${hoyoLanguageLabel(manifest.language)}语音包`;
  return `资源组件 ${manifest.matching_field || manifest.component}`;
}

// Identities available in this chunk manifest
const identities = computed(() => {
  if (activeSource.value === "chunk" && props.chunkDetail?.manifests?.length) {
    const result: Array<{ key: string; label: string; component: string; count: number }> = [];
    for (const m of props.chunkDetail.manifests) {
      const key = m.matching_field || m.language || m.component;
      result.push({
        key,
        label: manifestLabel(m),
        component: m.component,
        count: m.stats?.file_count || 0,
      });
    }
    return result;
  }
  return [{ key: "game", label: "游戏主资源", component: "game", count: 0 }];
});
const selectedIdentityItem = computed(() => identities.value.find((item) => item.key === selectedIdentity.value));

// Active Manifest Recipe for chunk downloading
const activeManifest = computed(() => {
  if (!props.chunkDetail?.manifests?.length) return null;
  return (
    props.chunkDetail.manifests.find(
      (m) => (m.matching_field || m.language || m.component) === selectedIdentity.value,
    ) || props.chunkDetail.manifests[0]
  );
});

const directoryComponents = computed(() => (props.chunkDetail?.manifests || []).map((manifest) => ({
  key: manifest.matching_field || manifest.language || manifest.component,
  label: manifestLabel(manifest),
  size: manifest.stats?.uncompressed_size || 0,
  supported: Boolean(manifest.chunk_download) && !Object.prototype.hasOwnProperty.call(manifest.chunk_download, "password") && (manifest.chunk_download?.encryption ?? 0) === 0 && [0, 1].includes(manifest.chunk_download?.compression ?? 0),
})));
const showDirectoryToggle = computed(() => activeSource.value === "chunk" && directoryComponents.value.length > 0);
const directorySize = computed(() => directoryComponents.value.filter((item) => directoryIdentities.value.includes(item.key)).reduce((sum, item) => sum + item.size, 0));

watch(() => props.chunkDetail, () => {
  if (!directoryDownloading.value) directoryIdentities.value = directoryComponents.value.filter((item) => item.supported).map((item) => item.key);
}, { immediate: true });

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

async function loadFiles(path: string, targetPage?: number): Promise<void> {
  const context = { domainId: props.domainId, version: props.version, source: activeSource.value, identity: selectedIdentity.value };
  const query = props.searchQuery;
  listController?.abort();
  const request = new AbortController();
  listController = request;
  const currentReq = ++requestId;
  const isCurrent = () => currentReq === requestId && listController === request
    && props.domainId === context.domainId && props.version === context.version
    && activeSource.value === context.source && selectedIdentity.value === context.identity && props.searchQuery === query;

  if (targetPage !== undefined) {
    loadingMore.value = true;
  } else {
    resetSelection();
    pageCursors.value = [undefined];
    pageIndex.value = 0;
    loading.value = true;
    emit("file-time-change", { ...context, fileTime: null, loading: true });
  }
  error.value = null;

  try {
    const q = query?.trim() || undefined;
    const page = targetPage ?? 0;
    const cursor = pageCursors.value[page];
    const res = await api.versionFiles(
      context.domainId,
      context.version,
      {
        source: context.source,
        identity: context.identity,
        path: path || undefined,
        q,
        limit: 100,
        cursor,
      },
      request.signal,
    );

    if (!isCurrent()) return;

    filePage.value = res;
    pageIndex.value = page;
    pageCursors.value.length = page + 1;
    if (res.next_cursor) pageCursors.value.push(res.next_cursor);
    emit("file-time-change", { ...context, fileTime: res.file_time ?? null, timeSource: res.file_time_source });
    syncRouteQuery();
  } catch (err) {
    if (isAbortError(err) || !isCurrent()) return;
    error.value = err instanceof Error ? err.message : "读取文件列表失败";
    emit("file-time-change", { ...context, fileTime: null });
  } finally {
    if (isCurrent()) {
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

function openFileDetail(item: ChunkFileItem): void {
  downloading.value = false;
  selectedFile.value = item;
  showDetailModal.value = true;
}

function closeModal(): void {
  downloading.value = false;
  showDetailModal.value = false;
  selectedFile.value = null;
}

async function downloadDirectory(): Promise<void> {
  if (anyDownloadBusy.value || !directoryIdentities.value.length) return;
  if (!canSaveDirectory.value) {
    directoryError.value = directoryUnavailableReason.value;
    return;
  }
  const controller = new AbortController();
  directoryController.value = controller;
  directoryDownloading.value = true;
  directoryMessage.value = "";
  directoryError.value = "";
  directoryProgress.value = null;
  const domainId = props.domainId;
  const version = props.version;
  const selected = [...directoryIdentities.value];
  try {
    const root = await (window as DownloadPickerWindow).showDirectoryPicker!({ mode: "readwrite" });
    if (controller.signal.aborted) return;
    const result = await downloadChunkDirectory({
      domainId, version, identities: selected, root,
      baseName: `${props.game?.id || props.domain?.game_id || domainId}-${version}`,
      signal: controller.signal,
      onProgress: (progress) => { if (directoryController.value === controller) directoryProgress.value = progress; },
    });
    if (directoryController.value === controller) directoryMessage.value = `已保存 ${result.files.toLocaleString()} 个文件（${formatBytes(result.bytes)}）到 ${result.directoryName}`;
  } catch (error) {
    if (directoryController.value === controller) {
      if (isAbortError(error)) directoryMessage.value = directoryProgress.value ? "下载已取消，已完成的文件保留在所选目录中。" : "已取消选择目录。";
      else directoryError.value = `${error instanceof Error ? error.message : "目录下载失败"}。已完成的文件会保留。`;
    }
  } finally {
    if (directoryController.value === controller) {
      directoryController.value = null;
      directoryDownloading.value = false;
    }
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
    directoryController.value?.abort();
    directoryController.value = null;
    directoryDownloading.value = false;
    directoryProgress.value = null;
    directoryMessage.value = "";
    directoryError.value = "";
    closeModal();
    directoryPanelOpen.value = false;
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
});

onBeforeUnmount(() => {
  requestId += 1;
  listController?.abort();
  directoryController.value?.abort();
  selectedController.value?.abort();
  if (toastTimer !== null) window.clearTimeout(toastTimer);
});
</script>

<template>
  <div class="cfb-wrapper">
    <!-- 顶部工具栏：来源模式切换 (当该版本同时具有 Package 和 Chunk 时显示) 与组件身份 -->
    <div class="cfb-top-toolbar" :class="{ merged: hasPackage && hasChunk && (identities.length > 1 || showDirectoryToggle) }">
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
            <span>完整包文件</span>
          </button>
          <button
            type="button"
            class="cfb-source-pill"
            :class="{ active: activeSource === 'chunk' }"
            @click="setSource('chunk')"
          >
            <span>Chunk 分块</span>
          </button>
        </div>
      </div>

      <!-- 组件/语音包分类切换栏 (Chunk 模式多分类时展示) -->
      <div v-if="identities.length > 1 || showDirectoryToggle" class="cfb-identities-row">
        <span v-if="identities.length > 1" class="cfb-toolbar-label">组件清单</span>
        <template v-if="identities.length > 8">
          <select
            class="cfb-identity-select"
            aria-label="组件清单"
            :value="selectedIdentity"
            :title="selectedIdentityItem?.label"
            @change="selectIdentity(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="item in identities" :key="item.key" :value="item.key" :title="item.label">
              {{ item.label }} · {{ item.count.toLocaleString() }} 个文件
            </option>
          </select>
          <span class="cfb-identity-summary">{{ identities.length }} 个组件 · 当前 {{ (selectedIdentityItem?.count || 0).toLocaleString() }} 个文件</span>
        </template>
        <div v-else-if="identities.length > 1" class="cfb-identity-chips">
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
        <button v-if="showDirectoryToggle" class="cfb-directory-toggle" type="button" :aria-expanded="directoryPanelOpen" @click="directoryPanelOpen = !directoryPanelOpen">下载游戏目录</button>
      </div>
    </div>

    <section v-if="directoryPanelOpen" class="cfb-directory-download" aria-label="下载游戏目录">
      <div class="cfb-directory-heading">
        <strong>选择要下载的资源</strong>
        <span>预计 {{ formatBytes(directorySize) }} · {{ directoryIdentities.length }} 个组件</span>
      </div>
      <p>重建所选清单中的全部文件，不受当前目录或搜索影响。输出为游戏文件目录，不包含安装程序。</p>
      <div class="cfb-directory-components">
        <label v-for="item in directoryComponents" :key="item.key">
          <input v-model="directoryIdentities" type="checkbox" :value="item.key" :disabled="directoryDownloading || !item.supported" />
          <span>{{ item.label }}</span><small>{{ item.supported ? formatBytes(item.size) : '暂不支持此格式' }}</small>
        </label>
      </div>
      <p v-if="!canSaveDirectory" class="cfb-download-error">{{ directoryUnavailableReason }}</p>
      <div class="cfb-directory-actions">
        <button class="tool-button dl-btn" type="button" :disabled="!canSaveDirectory || anyDownloadBusy || !directoryIdentities.length" @click="downloadDirectory">{{ directoryDownloading ? '正在下载…' : '选择目录并下载' }}</button>
        <button v-if="directoryDownloading" class="tool-button copy-btn" type="button" @click="directoryController?.abort()">取消下载</button>
      </div>
      <div v-if="directoryProgress" class="cfb-directory-progress" role="status">
        <span>{{ directoryProgress.stage === 'preparing' ? '正在读取并校验清单…' : `${directoryProgress.completedFiles.toLocaleString()}/${directoryProgress.totalFiles.toLocaleString()} 个文件 · ${formatBytes(directoryProgress.completedBytes)}/${formatBytes(directoryProgress.totalBytes)}` }}</span>
        <span v-if="directoryProgress.currentPath">{{ directoryProgress.currentPath }}</span>
        <span v-if="directoryProgress.chunkProgress">当前文件：{{ directoryProgress.chunkProgress.completed }}/{{ directoryProgress.chunkProgress.total }} 块 · {{ formatBytes(directoryProgress.chunkProgress.receivedBytes) }}/{{ formatBytes(directoryProgress.chunkProgress.totalBytes) }}</span>
      </div>
      <p v-if="directoryMessage" role="status">{{ directoryMessage }}</p>
      <p v-if="directoryError" class="cfb-download-error" role="alert">{{ directoryError }}</p>
      <p>在所选目录下新建游戏子目录，不覆盖已有文件。保持此页面打开；取消或失败时保留已完成文件。</p>
    </section>

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

    <div
      v-if="!loading && !error && (loadedFiles.length || selectedFiles.size)"
      class="cfb-selected-toolbar"
      :class="{ 'is-idle': !selectedPaths.length && !selectedProgress && !selectedMessage && !selectedError }"
    >
      <label><input type="checkbox" :checked="allLoadedSelected" :disabled="selectedBusy || !loadedFiles.length" @change="toggleLoadedFiles" />全选本页文件</label>
      <span>已选 {{ selectedPaths.length }} 个文件 · {{ formatBytes(selectedSize) }}</span>
      <button type="button" class="cfb-act-btn copy-act" :disabled="selectedBusy || !selectedPaths.length" @click="resetSelection">清空</button>
      <button type="button" class="cfb-act-btn dl-act" :disabled="anyDownloadBusy || !selectedPaths.length || !canSaveDirectory" @click="selectedAction('download')">选择目录并下载所选文件</button>
      <button type="button" class="cfb-act-btn copy-act" :disabled="anyDownloadBusy || !selectedPaths.length" @click="selectedAction('copy')">{{ activeSource === 'chunk' ? '复制合成清单' : '复制官方直链' }}</button>
      <button type="button" class="cfb-act-btn copy-act" :disabled="anyDownloadBusy || !selectedPaths.length" @click="selectedAction('export')">{{ activeSource === 'chunk' ? '导出合成清单 JSON' : '导出官方直链列表' }}</button>
      <button v-if="selectedBusy" type="button" class="cfb-act-btn copy-act" @click="selectedController?.abort()">取消</button>
      <button
        v-if="!selectedPaths.length"
        type="button"
        class="cfb-help-toggle"
        :aria-expanded="selectionHelpOpen"
        title="查看批量选择与下载说明"
        @click="selectionHelpOpen = !selectionHelpOpen"
      >
        ? 说明
      </button>
      <template v-if="selectedPaths.length || selectionHelpOpen">
        <p>可以跨页勾选；“全选”只选当前页的文件，不含文件夹。切换目录、搜索或组件后会清空已选。下载时会在你选的位置新建一个文件夹，按原目录结构保存，并核对大小和 MD5。</p>
        <p v-if="!canSaveDirectory">{{ directoryUnavailableReason }} 仍可复制或导出{{ activeSource === 'chunk' ? '合成清单。Chunk 文件要由多个分块拼成，没有可以直接下载的完整文件链接。' : '官方直链列表。' }}</p>
        <p v-else-if="activeSource === 'chunk'">Chunk 文件由多个分块拼成；导出的 JSON 是拼合用的清单，不是完整文件的下载链接。</p>
      </template>
      <div v-if="selectedProgress" class="cfb-directory-progress" role="status">
        <span>{{ selectedProgress.stage === 'preparing' ? '读取所选文件详情…' : `已完成 ${selectedProgress.completedFiles} / ${selectedProgress.totalFiles} 个文件 · ${formatBytes(selectedProgress.completedBytes)} / ${formatBytes(selectedProgress.totalBytes)}` }}</span>
        <span v-if="selectedProgress.currentPath">{{ selectedProgress.currentPath }} <template v-if="selectedProgress.chunkProgress">· {{ formatBytes(selectedProgress.chunkProgress.receivedBytes) }} / {{ formatBytes(selectedProgress.chunkProgress.totalBytes) }}</template></span>
      </div>
      <p v-if="selectedMessage" role="status">{{ selectedMessage }}</p>
      <p v-if="selectedError" class="cfb-download-error" role="alert">{{ selectedError }}</p>
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
      <button class="tool-button cfb-retry-btn" type="button" @click="loadFiles(currentPath, pageIndex)">
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
        <div class="cfb-grid-header fl-head fl-cols-chunk">
          <div class="cfb-col cfb-col-name">名称</div>
          <div class="cfb-col cfb-col-size">大小</div>
          <div class="cfb-col cfb-col-chunks">分块 / 文件数</div>
          <div class="cfb-col cfb-col-hash">MD5 校验值</div>
          <div class="cfb-col cfb-col-action">操作</div>
        </div>

        <!-- 列表 Rows -->
        <div class="cfb-grid-body">
          <div
            v-for="item in filePage.items"
            :key="item.path"
            class="cfb-grid-row fl-item fl-row fl-cols-chunk"
            :class="item.type === 'directory' ? 'row-is-dir' : 'row-is-file'"
            @click="item.type === 'directory' ? navigateToPath(item.path) : openFileDetail(item)"
          >
            <!-- 1. 名称列 -->
            <div class="cfb-col cfb-col-name">
              <div class="cfb-name-block fl-name">
                <input v-if="item.type !== 'directory'" class="cfb-file-checkbox fl-check" type="checkbox" :aria-label="`选择 ${item.path}`" :checked="selectedFiles.has(item.path)" :disabled="selectedBusy" @click.stop @change="toggleSelected(item)" />
                <span v-else class="fl-check-slot" aria-hidden="true"></span>
                <span v-if="item.type === 'directory'" class="cfb-type-icon dir-icon fl-icon is-dir">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3 6.5h6l2 2h10v9H3z" />
                  </svg>
                </span>
                <span v-else class="cfb-type-icon file-icon fl-icon is-file">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </span>

                <div class="cfb-name-texts">
                  <strong class="cfb-main-name fl-name-text" :title="item.name">{{ item.name }}</strong>
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
              <span v-if="item.type === 'directory'" class="cfb-badge-dir fl-muted">
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
                class="cfb-hash-code fl-hash"
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
                class="cfb-row-act fl-act"
                title="进入目录"
                @click="navigateToPath(item.path)"
              >
                <span class="visually-hidden">进入目录</span>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
              <template v-else>
                <div class="cfb-row-action-group fl-actions">
                  <a
                    v-if="item.download_url"
                    class="cfb-row-act fl-act fl-act-primary"
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
                    <span class="visually-hidden">下载</span>
                  </a>
                  <button
                    v-if="item.download_url"
                    type="button"
                    class="cfb-row-act cfb-row-copy fl-act"
                    title="复制文件下载直链"
                    @click="copyText(item.download_url, '直链')"
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <rect x="9" y="9" width="11" height="11" rx="2" />
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                    </svg>
                    <span class="visually-hidden">复制</span>
                  </button>
                  <button
                    v-else
                    type="button"
                    class="cfb-row-act fl-act"
                    title="查看分块"
                    @click="openFileDetail(item)"
                  >
                    <span class="visually-hidden">查看分块</span>
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

      <!-- Keep only one response page mounted, retaining selected paths across pages. -->
      <div v-if="pageIndex > 0 || filePage?.next_cursor" class="cfb-pagination-bar">
        <button type="button" class="cfb-prevpage-btn cfb-loadmore-btn" :disabled="loadingMore || pageIndex === 0" @click="loadFiles(currentPath, pageIndex - 1)">上一页</button>
        <span>第 {{ pageIndex + 1 }} 页</span>
        <button
          type="button"
          class="cfb-nextpage-btn cfb-loadmore-btn"
          :disabled="loadingMore || !filePage?.next_cursor"
          @click="loadFiles(currentPath, pageIndex + 1)"
        >
          {{ loadingMore ? '正在载入…' : '下一页文件' }}
        </button>
      </div>
    </div>

    <!-- 单文件明细弹窗 (Modal) -->
    <ChunkFileDetailModal
      :open="showDetailModal"
      :domain-id="domainId"
      :version="version"
      :source="activeSource"
      :identity="selectedIdentity"
      :selected-file="selectedFile"
      :active-manifest="activeManifest"
      :any-download-busy="anyDownloadBusy"
      :can-save-file="canSaveFile"
      @close="closeModal()"
      @copy-text="copyText"
      @update:downloading="downloading = $event"
    />

    <!-- 复制轻提示 Toast -->
    <Transition name="fade">
      <div v-if="toastMessage" class="cfb-toast">
        {{ toastMessage }}
      </div>
    </Transition>
  </div>
</template>


<style scoped src="../styles/chunk-file-browser.css"></style>
