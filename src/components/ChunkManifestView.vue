<script setup lang="ts">
import { computed, ref } from "vue";
import type { ArchiveDomain, Artifact, ChunkManifestDetail, ChunkManifestEntry, ChunkManifestSummaryItem, Game } from "../types";
import { formatBytes, formatObservedDate, hoyoLanguageLabel, preferredArtifactAction, preferredDomainArtifactAction } from "../domain-presentation";
import AvailabilityBadge from "./AvailabilityBadge.vue";

const props = defineProps<{
  domain: ArchiveDomain | null;
  game: Game | null;
  version: string;
  chunkDetail: ChunkManifestDetail | null;
  chunkCollection: ChunkManifestSummaryItem[];
  artifacts?: Artifact[];
  categoryFilter?: string;
  loading: boolean;
  error?: string | null;
}>();

const emit = defineEmits<{
  (e: "select-version", version: string): void;
  (e: "copy-url", url: string, label?: string): void;
}>();

const internalCategoryFilter = ref<string>("all");
const activeFilter = computed(() => props.categoryFilter ?? internalCategoryFilter.value);

function preferredAvailableUrl(artifact: Artifact, action: "open" | "copy" = "open"): string | undefined {
  return preferredDomainArtifactAction(props.domain, artifact, action)?.url;
}

function rawArtifactUrl(artifact: Artifact): string | undefined {
  return artifact.urls[0]?.url;
}

function manifestDownloadUrl(manifest: ChunkManifestEntry): string {
  const prefix = manifest.manifest_download?.url_prefix || "";
  const id = manifest.manifest?.id || manifest.manifest_id || "";
  if (!prefix || !id) return "";
  return `${prefix.replace(/\/+$/, "")}/${id}`;
}

function chunkDownloadRecipe(manifest: ChunkManifestEntry): string {
  const prefix = manifest.chunk_download?.url_prefix || "";
  if (!prefix) return "";
  return `${prefix.replace(/\/+$/, "")}/{chunk_checksum}`;
}

function languageLabel(lang: string | null | undefined): string {
  return hoyoLanguageLabel(lang) || lang || "通用";
}

const displayedManifests = computed(() => {
  if (!props.chunkDetail?.manifests) return [];
  const filter = activeFilter.value;
  if (filter === "all") return props.chunkDetail.manifests;
  if (filter === "game") {
    return props.chunkDetail.manifests.filter((m) => m.component === "game");
  }
  return props.chunkDetail.manifests.filter(
    (m) => (m.language?.toLowerCase() || m.component) === filter,
  );
});

const summaryStats = computed(() => {
  if (!props.chunkDetail?.manifests?.length) {
    const rows = (props.artifacts || []).filter((item) => item.kind === "chunk");
    const numeric = (item: Artifact, key: string) => Number(item.attributes?.[key] || 0);
    return {
      buildId: String(rows[0]?.attributes?.build_id || "—"),
      manifestCount: rows.length,
      fileCount: rows.reduce((sum, item) => sum + numeric(item, "file_count"), 0),
      chunkCount: rows.reduce((sum, item) => sum + numeric(item, "chunk_count"), 0),
      compressedSize: rows.reduce((sum, item) => sum + item.size, 0),
      uncompressedSize: rows.reduce((sum, item) => sum + numeric(item, "uncompressed_size"), 0),
      deduplicatedSize: rows.reduce((sum, item) => sum + item.size, 0),
    };
  }
  const detail = props.chunkDetail;
  const manifests = detail.manifests;
  const fileCount = manifests.reduce((sum, m) => sum + (m.stats?.file_count || 0), 0);
  const chunkCount = manifests.reduce((sum, m) => sum + (m.stats?.chunk_count || 0), 0);
  const compressedSize = manifests.reduce((sum, m) => sum + (m.stats?.compressed_size || 0), 0);
  const uncompressedSize = manifests.reduce((sum, m) => sum + (m.stats?.uncompressed_size || 0), 0);
  const deduplicatedSize = manifests.reduce(
    (sum, m) => sum + (m.deduplicated_stats?.compressed_size ?? m.stats?.compressed_size ?? 0),
    0,
  );
  return {
    buildId: detail.build_id || "—",
    manifestCount: manifests.length,
    fileCount,
    chunkCount,
    compressedSize,
    uncompressedSize,
    deduplicatedSize,
  };
});

function copyManifestUrl(manifest: ChunkManifestEntry): void {
  const url = manifestDownloadUrl(manifest);
  if (url) emit("copy-url", url, "Manifest 下载链接");
}

function copyChunkRecipe(manifest: ChunkManifestEntry): void {
  const recipe = chunkDownloadRecipe(manifest);
  if (recipe) emit("copy-url", recipe, "Chunk 下载前缀配方");
}

function copyText(text: string, label: string): void {
  if (text) emit("copy-url", text, label);
}
</script>

<template>
  <div class="chunk-manifest-view">
    <!-- 顶部加载状态 -->
    <div v-if="loading" class="chunk-loading-state">
      <div class="loading-spinner" />
      <span>正在读取 Chunk Manifest 架构信息…</span>
    </div>

    <!-- 顶部错误状态 -->
    <div v-else-if="error" class="chunk-error-state">
      <p>{{ error }}</p>
    </div>

    <!-- 当前版本缺少 Chunk Manifest 时的清爽空状态 -->
    <div v-else-if="!chunkDetail && (!artifacts || artifacts.length === 0)" class="chunk-empty-state-card">
      <svg viewBox="0 0 24 24" class="chunk-empty-icon" aria-hidden="true">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
        <line x1="12" y1="22.08" x2="12" y2="12" />
      </svg>
      <div class="chunk-empty-texts">
        <strong>当前版本暂无 Chunk 分发记录</strong>
        <p>Sophon Chunk 分发架构自 4.2.0 起收录，版本 {{ version }} 采用传统完整包或更新补丁分发</p>
      </div>
    </div>

    <!-- 当前版本有 Chunk Manifest 详情时的完整展示 -->
    <div v-else-if="chunkDetail" class="chunk-detail-content">
      <!-- Manifest 卡片列表 -->
      <div class="chunk-manifests-grid">
        <article
          v-for="(manifest, index) in displayedManifests"
          :key="manifest.manifest_id || index"
          class="chunk-manifest-card"
        >
          <!-- 卡片头部 -->
          <div class="card-head">
            <div class="card-title-group">
              <span
                class="component-pill"
                :class="manifest.component === 'game' ? 'pill-game' : 'pill-voice'"
              >
                {{ manifest.component === 'game' ? '游戏主资源' : `${languageLabel(manifest.language)}语音包` }}
              </span>
              <strong class="card-name">{{ manifest.category?.name || manifest.matching_field }}</strong>
            </div>
            <div class="card-meta-line">
              <span class="meta-field">
                <span class="meta-field-label">Manifest ID:</span>
                <code class="mono-code" @click="copyText(manifest.manifest?.id || manifest.manifest_id || '', 'Manifest ID')">{{ manifest.manifest?.id || manifest.manifest_id || '—' }}</code>
              </span>
              <span class="meta-field">
                <span class="meta-field-label">MD5:</span>
                <code class="mono-code">{{ manifest.manifest?.checksum || '—' }}</code>
              </span>
              <span v-if="manifest.last_modified_at" class="meta-field">
                <span class="meta-field-label">Manifest 更新时间:</span>
                <span class="meta-val mono">{{ formatObservedDate(manifest.last_modified_at) }}</span>
              </span>
            </div>
          </div>

          <!-- 卡片数据统计指标 -->
          <div class="card-metrics-grid">
            <div class="metric-box">
              <span class="box-label">资源文件数</span>
              <span class="box-val">{{ (manifest.stats?.file_count || 0).toLocaleString() }} 个</span>
            </div>
            <div class="metric-box">
              <span class="box-label">分块数 (Chunks)</span>
              <span class="box-val">{{ (manifest.stats?.chunk_count || 0).toLocaleString() }} 块</span>
            </div>
            <div class="metric-box">
              <span class="box-label">压缩后体积</span>
              <span class="box-val mono">{{ formatBytes(manifest.stats?.compressed_size || 0) }}</span>
            </div>
            <div class="metric-box">
              <span class="box-label">解压后体积</span>
              <span class="box-val mono">{{ formatBytes(manifest.stats?.uncompressed_size || 0) }}</span>
            </div>
            <div class="metric-box">
              <span class="box-label">Manifest 索引体积</span>
              <span class="box-val mono">{{ formatBytes(manifest.manifest?.compressed_size || 0) }}</span>
            </div>
            <div v-if="manifest.deduplicated_stats" class="metric-box">
              <span class="box-label">去重后体积</span>
              <span class="box-val mono text-cyan">{{ formatBytes(manifest.deduplicated_stats.compressed_size) }}</span>
            </div>
          </div>

          <!-- 卡片 URL Recipe & 下载入口 -->
          <div class="card-recipes-box">
            <!-- Manifest 直链下载 -->
            <div class="recipe-row">
              <div class="recipe-info">
                <span class="recipe-type-badge manifest-badge">Manifest 文件</span>
                <span class="recipe-url-text" :title="manifestDownloadUrl(manifest)">
                  {{ manifestDownloadUrl(manifest) || '无可用 Manifest URL' }}
                </span>
              </div>
              <div class="recipe-actions">
                <button
                  v-if="manifestDownloadUrl(manifest)"
                  class="icon-button"
                  @click="copyManifestUrl(manifest)"
                >
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <a
                  v-if="manifestDownloadUrl(manifest)"
                  class="icon-button download-btn"
                  :href="manifestDownloadUrl(manifest)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载 Manifest</span>
                </a>
              </div>
            </div>

            <!-- Chunk 分块请求配方 (Recipe) -->
            <div class="recipe-row">
              <div class="recipe-info">
                <span class="recipe-type-badge chunk-badge">Chunk 配方</span>
                <span class="recipe-url-text" :title="chunkDownloadRecipe(manifest)">
                  {{ chunkDownloadRecipe(manifest) || '无 Chunk 下载前缀' }}
                </span>
                <span class="recipe-param-tag">
                  压缩: {{ manifest.chunk_download?.compression === 1 ? 'LZ4 / ZSTD' : (manifest.chunk_download?.compression ?? '—') }}
                </span>
                <span class="recipe-param-tag">
                  加密: {{ manifest.chunk_download?.encryption === 0 ? '无' : (manifest.chunk_download?.encryption ?? '—') }}
                </span>
              </div>
              <div class="recipe-actions">
                <button
                  v-if="chunkDownloadRecipe(manifest)"
                  class="icon-button"
                  @click="copyChunkRecipe(manifest)"
                >
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制 Chunk 前缀</span>
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>
    </div>

    <!-- 降级：若没有 chunkDetail 但存在 artifacts 列表（如旧接口或单测 mock 数据） -->
    <div v-else-if="artifacts && artifacts.length > 0" class="chunk-fallback-list">
      <article v-for="(artifact, index) in artifacts" :key="artifact.id" class="file-card chunk-card">
        <div class="file-icon">
          <svg viewBox="0 0 24 24" aria-hidden="true" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m21 8-9-5-9 5 9 5 9-5Z" />
            <path d="M3 8v8l9 5 9-5V8" />
            <path d="M12 13v8" />
          </svg>
        </div>
        <div class="file-main">
          <div class="file-title">
            <span class="pill">Chunk Manifest</span>
            <span class="count">{{ index + 1 }}/{{ artifacts.length }}</span>
            <strong>{{ artifact.name }}</strong>
          </div>
          <div class="file-meta">
            <span>{{ formatBytes(artifact.size) }}</span>
            <span># {{ artifact.checksum_value || '—' }}</span>
            <span>ID {{ String(artifact.attributes?.manifest_id || artifact.name) }}</span>
            <span>{{ String(artifact.attributes?.matching_field || 'game') }}</span>
          </div>
        </div>
        <div class="file-actions">
          <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
          <button
            v-if="preferredAvailableUrl(artifact, 'copy')"
            class="icon-button"
            @click="emit('copy-url', preferredAvailableUrl(artifact, 'copy')!, '链接')"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            <span>复制链接</span>
          </button>
          <a
            v-if="preferredAvailableUrl(artifact)"
            class="icon-button download-btn"
            :href="preferredAvailableUrl(artifact)"
            target="_blank"
            rel="noreferrer"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 3v12" />
              <path d="m7 10 5 5 5-5" />
              <path d="M5 21h14" />
            </svg>
            <span>下载 Manifest</span>
          </a>
          <span v-else class="stale-link">无可用 Manifest URL</span>
          <button
            v-if="!preferredAvailableUrl(artifact) && rawArtifactUrl(artifact)"
            class="icon-button"
            @click="emit('copy-url', rawArtifactUrl(artifact)!, '链接')"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            <span>复制链接</span>
          </button>
        </div>
      </article>
    </div>

    <!-- 兜底状态：未查询到该版本的 Chunk Manifest 数据 -->
    <div v-else class="chunk-empty-notice">
      <div class="notice-card">
        <div class="notice-icon">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>
        <div class="notice-content">
          <h3>当前版本 ({{ version }}) 暂无 Sophon Chunk Manifest 记录</h3>
          <p>未获取到当前版本的 Manifest 分块数据。可通过上方版本选择器切换至其他版本查看。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chunk-manifest-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chunk-loading-state,
.chunk-error-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 160px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-soft);
  color: var(--muted);
  font-size: 14px;
}

.chunk-empty-state-card {
  width: 100%;
  padding: 56px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  border-radius: 10px;
  background: rgba(14, 22, 35, 0.5);
  border: 1px solid var(--line-soft);
  color: var(--muted);
  box-sizing: border-box;
  text-align: center;
}

.chunk-empty-icon {
  width: 36px;
  height: 36px;
  stroke: rgba(255, 255, 255, 0.25);
  fill: none;
  stroke-width: 1.6;
}

.chunk-empty-texts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.chunk-empty-texts strong {
  color: #cbd5e1;
  font-size: 14.5px;
  font-weight: 700;
}

.chunk-empty-texts p {
  margin: 0;
  color: #64748b;
  font-size: 12.5px;
  max-width: 500px;
}

.chunk-empty-actions {
  margin-top: 4px;
}

.chunk-switch-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border-radius: 6px;
  border: 1px solid rgba(56, 189, 248, 0.25);
  background: rgba(56, 189, 248, 0.06);
  color: #38bdf8;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.15s ease;
}

.chunk-switch-btn:hover {
  background: rgba(56, 189, 248, 0.16);
  border-color: #38bdf8;
  color: #fff;
}

.chunk-switch-btn svg {
  width: 12px;
  height: 12px;
  stroke: currentColor;
  stroke-width: 2.5;
  fill: none;
}

/* --- 指标概览栏 (Summary Bar) --- */
.chunk-summary-bar {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.summary-metric {
  min-height: 68px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(14, 22, 35, 0.85);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.metric-label {
  color: var(--muted);
  font-size: 11px;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.metric-val {
  margin-top: 4px;
  color: var(--cyan);
  font-size: 14.5px;
  font-weight: 850;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-val.mono {
  font-family: var(--font-mono);
}

/* --- 筛选控制栏 --- */
.chunk-filters-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  border-top: 1px solid var(--line-soft);
  padding-top: 12px;
}

.collection-toggle-btn {
  font-size: 12px;
}

.collection-toggle-btn.active {
  border-color: rgba(56, 189, 248, 0.6);
  background: rgba(56, 189, 248, 0.15);
  color: #fff;
}

/* --- 版本库表格与抽屉 --- */
.chunk-collection-section,
.chunk-collection-drawer {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(11, 18, 29, 0.9);
  padding: 16px 20px;
}

.section-head,
.drawer-header {
  margin-bottom: 12px;
}

.section-head h4,
.drawer-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 800;
  color: #f8fafc;
}

.drawer-tip {
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
  display: block;
}

.chunk-table-wrapper {
  overflow-x: auto;
  margin-top: 8px;
}

.chunk-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  text-align: left;
}

.chunk-table th {
  padding: 8px 12px;
  color: var(--muted);
  font-weight: 750;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}

.chunk-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line-soft);
  color: #e2e8f0;
  white-space: nowrap;
}

.chunk-table tr.is-active-row {
  background: rgba(56, 189, 248, 0.08);
}

.version-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(148, 163, 184, 0.15);
  color: #f1f5f9;
  font-family: var(--font-mono);
  font-weight: 800;
  font-size: 12px;
}

.version-tag.current-tag {
  background: rgba(56, 189, 248, 0.25);
  border: 1px solid rgba(56, 189, 248, 0.6);
  color: #38bdf8;
}

.build-id-code {
  font-family: var(--font-mono);
  color: #93c5fd;
  font-size: 11.5px;
}

.tags-row {
  display: flex;
  gap: 5px;
}

.mini-chip {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(148, 163, 184, 0.12);
  color: #94a3b8;
  font-size: 11px;
}

.mini-chip.lang-chip {
  background: rgba(167, 139, 250, 0.15);
  color: #c4b5fd;
}

.mini-btn {
  min-width: 68px;
  min-height: 28px;
  padding: 0 10px;
  font-size: 11.5px;
}

/* --- Manifest 卡片列表 --- */
.chunk-manifests-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chunk-manifest-card {
  display: flex !important;
  flex-direction: column !important;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.75);
  padding: 16px 20px;
  gap: 14px;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  overflow: hidden;
  transition: all 0.2s ease;
}

.chunk-manifest-card:hover {
  border-color: rgba(56, 189, 248, 0.4);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
}

.card-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.card-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}

.component-pill {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
}

.pill-game {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.4);
  color: #38bdf8;
}

.pill-voice {
  background: rgba(167, 139, 250, 0.15);
  border: 1px solid rgba(167, 139, 250, 0.4);
  color: #c4b5fd;
}

.card-name {
  font-size: 15px;
  font-weight: 800;
  color: #f8fafc;
}

.card-meta-line {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
  min-width: 0;
}

.meta-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  min-width: 0;
  max-width: 100%;
}

.meta-field-label {
  font-weight: 700;
  white-space: nowrap;
}

.mono-code {
  font-family: var(--font-mono);
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.6);
  padding: 1px 6px;
  border-radius: 4px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 380px;
}

.mono-code:hover {
  color: #38bdf8;
  text-decoration: underline;
}

.meta-val {
  color: #cbd5e1;
  font-weight: 600;
}

.meta-val.mono {
  font-family: var(--font-mono);
  color: #93c5fd;
}

/* --- 卡片指标网格 --- */
.card-metrics-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
}

.metric-box {
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  background: rgba(10, 16, 26, 0.6);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.box-label {
  color: var(--muted);
  font-size: 10.5px;
  font-weight: 750;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.box-val {
  margin-top: 3px;
  color: #f1f5f9;
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.box-val.mono {
  font-family: var(--font-mono);
}

.text-cyan {
  color: var(--cyan);
}

/* --- Recipes Box --- */
.card-recipes-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid var(--line-soft);
  padding-top: 10px;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.recipe-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: rgba(11, 18, 30, 0.7);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  padding: 8px 14px;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  overflow: hidden;
}

.recipe-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

.recipe-type-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 800;
  white-space: nowrap;
  flex-shrink: 0;
}

.manifest-badge {
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
}

.chunk-badge {
  background: rgba(52, 211, 153, 0.15);
  color: #6ee7b7;
}

.recipe-url-text {
  font-family: var(--font-mono);
  font-size: 12px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.recipe-param-tag {
  font-size: 11px;
  color: #64748b;
  background: rgba(15, 23, 42, 0.8);
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.recipe-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.download-btn {
  border-color: rgba(56, 189, 248, 0.4);
  color: #38bdf8;
}

.download-btn:hover {
  border-color: rgba(56, 189, 248, 0.8);
  background: rgba(56, 189, 248, 0.15);
}

.chunk-fallback-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

@media (max-width: 1100px) {
  .chunk-summary-bar {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .card-metrics-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .recipe-row {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .recipe-actions {
    width: 100%;
    justify-content: flex-end;
  }
}

@media (max-width: 640px) {
  .chunk-summary-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .card-metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
