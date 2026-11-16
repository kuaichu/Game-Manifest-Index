<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api, chunkContentUrl, isAbortError } from "../../api";
import {
  chunkUrl,
  ChunkDownloadError,
  MAX_BROWSER_SYNTHESIS_SIZE,
  saveBlob,
  synthesizeChunkFile,
  writeChunkFile,
  type ChunkDownloadProgress,
} from "../../chunk-download";
import { useModalScrollLock } from "../../composables/useModalScrollLock";
import { formatBytes } from "../../domain-presentation";
import type { ChunkFileDetail, ChunkFileItem, ChunkManifestEntry } from "../../types";

type DownloadPickerWindow = Window & {
  showSaveFilePicker?: (options: { suggestedName: string }) => Promise<FileSystemFileHandle>;
};

const props = defineProps<{
  open: boolean;
  domainId: string;
  version: string;
  source: "package" | "chunk";
  identity: string;
  selectedFile: ChunkFileItem | null;
  activeManifest: ChunkManifestEntry | null;
  anyDownloadBusy: boolean;
  canSaveFile: boolean;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "copy-text", text: string, label: string): void;
  (e: "update:downloading", value: boolean): void;
}>();

useModalScrollLock(() => props.open);

const fileDetail = ref<ChunkFileDetail | null>(null);
const fileDetailLoading = ref(false);
const fileDetailError = ref<string | null>(null);
const downloadController = ref<AbortController | null>(null);
const downloadProgress = ref<ChunkDownloadProgress | null>(null);
const downloadError = ref<string | null>(null);
const downloading = ref(false);

let detailController: AbortController | null = null;
let detailGeneration = 0;

function setDownloading(value: boolean): void {
  downloading.value = value;
  emit("update:downloading", value);
}

function resetModalState(): void {
  detailGeneration += 1;
  downloadController.value?.abort();
  downloadController.value = null;
  setDownloading(false);
  fileDetail.value = null;
  fileDetailLoading.value = false;
  fileDetailError.value = null;
  downloadProgress.value = null;
  downloadError.value = null;
  detailController?.abort();
  detailController = null;
}

async function loadFileDetail(item: ChunkFileItem): Promise<void> {
  const generation = ++detailGeneration;
  downloadController.value?.abort();
  downloadController.value = null;
  downloadProgress.value = null;
  downloadError.value = null;
  setDownloading(false);
  fileDetailLoading.value = true;
  fileDetailError.value = null;
  fileDetail.value = null;

  detailController?.abort();
  const request = new AbortController();
  detailController = request;
  const recipe = props.source === "chunk" ? props.activeManifest?.chunk_download : undefined;

  try {
    const detail = await api.versionFileDetail(
      props.domainId,
      props.version,
      {
        source: props.source,
        identity: props.identity,
        path: item.path,
      },
      request.signal,
    );
    if (generation === detailGeneration) {
      fileDetail.value = recipe && !detail.chunk_download
        ? { ...detail, chunk_download: recipe }
        : detail;
    }
  } catch (err) {
    if (isAbortError(err) || generation !== detailGeneration) return;
    fileDetailError.value = err instanceof Error ? err.message : "获取文件明细失败";
  } finally {
    if (generation === detailGeneration) fileDetailLoading.value = false;
  }
}

watch(
  () => [props.open, props.selectedFile, props.domainId, props.version, props.source, props.identity] as const,
  ([open, item]) => {
    if (open && item) {
      void loadFileDetail(item);
    } else {
      resetModalState();
    }
  },
  { immediate: true },
);

function chunkDownloadUrl(chunkName: string): string {
  const recipe = props.activeManifest?.chunk_download;
  if (!recipe || !chunkName) return "";
  try {
    return chunkUrl(recipe, chunkName);
  } catch {
    return "";
  }
}

async function downloadCompleteFile(): Promise<void> {
  if (!fileDetail.value || props.anyDownloadBusy) return;
  if (fileDetail.value.size > MAX_BROWSER_SYNTHESIS_SIZE && !props.canSaveFile) {
    downloadError.value = "超过 64 MiB 的文件需要在桌面 Chrome 或 Edge 中直接保存到磁盘";
    return;
  }
  downloadController.value?.abort();
  const controller = new AbortController();
  downloadController.value = controller;
  setDownloading(true);
  downloadError.value = null;
  const chunks = fileDetail.value.chunks || [];
  downloadProgress.value = {
    completed: 0,
    total: chunks.length,
    receivedBytes: 0,
    totalBytes: chunks.reduce((sum, chunk) => sum + chunk.size, 0),
  };
  try {
    const filename = fileDetail.value.path.split("/").filter(Boolean).pop() || "download.bin";
    const detail = fileDetail.value;
    const identity = props.identity;
    const domainId = props.domainId;
    const version = props.version;
    const onProgress = (progress: ChunkDownloadProgress) => {
      if (downloadController.value === controller) downloadProgress.value = progress;
    };
    const urlForChunk = (chunk: NonNullable<ChunkFileDetail["chunks"]>[number]) =>
      chunkContentUrl(domainId, version, identity, chunk.name);
    if (props.canSaveFile) {
      const handle = await (window as DownloadPickerWindow).showSaveFilePicker!({ suggestedName: filename });
      if (controller.signal.aborted) return;
      const writable = await handle.createWritable();
      await writeChunkFile(detail, writable, controller.signal, onProgress, urlForChunk);
    } else {
      const blob = await synthesizeChunkFile(detail, controller.signal, onProgress, urlForChunk);
      if (!controller.signal.aborted) saveBlob(blob, filename);
    }
  } catch (err) {
    if (downloadController.value === controller && !isAbortError(err)) {
      downloadError.value = err instanceof ChunkDownloadError || err instanceof Error ? err.message : "完整文件合成失败";
    }
  } finally {
    if (downloadController.value === controller) {
      downloadController.value = null;
      setDownloading(false);
    }
  }
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && props.open) {
    emit("close");
  }
}

onMounted(() => {
  window.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  detailGeneration += 1;
  detailController?.abort();
  downloadController.value?.abort();
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="cfb-modal-overlay"
      @click.self="emit('close')"
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
            @click="emit('close')"
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
              @click="emit('copy-text', selectedFile?.path || '', '文件路径')"
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
              @click="emit('copy-text', selectedFile?.md5 || selectedFile?.hash || '', 'MD5')"
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
                  @click="emit('copy-text', fileDetail?.download_url || selectedFile?.download_url || '', '下载直链')"
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
              <button type="button" class="tool-button dl-btn" :disabled="anyDownloadBusy" @click="downloadCompleteFile">
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
                    @click="emit('copy-text', chunk.hash, 'Chunk Hash')"
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
                      @click="emit('copy-text', chunkDownloadUrl(chunk.name), 'Chunk 直链')"
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
            @click="emit('close')"
          >
            完成并关闭
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.mono-text {
  font-family: var(--font-mono);
  font-size: 12px;
  color: #cbd5e1;
}

.cfb-dim-text {
  color: #475569;
  font-size: 12px;
}

.cfb-hash-code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #94a3b8;
  background: rgba(0, 0, 0, 0.25);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cfb-hash-code:hover {
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.35);
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
  overscroll-behavior: contain;
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

@media (max-width: 860px) {
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
}
</style>
