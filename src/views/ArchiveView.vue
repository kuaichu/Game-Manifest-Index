<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, apiUrl, isAbortError } from "../api";
import ArtifactTree from "../components/ArtifactTree.vue";
import ComparePanel from "../components/ComparePanel.vue";
import FragmentFileRow, { activeFileMenuId } from "../components/FragmentFileRow.vue";
import RemoteArtifactTree from "../components/RemoteArtifactTree.vue";
import VersionPicker from "../components/VersionPicker.vue";
import AvailabilityBadge from "../components/AvailabilityBadge.vue";
import ChunkManifestView from "../components/ChunkManifestView.vue";
import ChunkFileBrowser from "../components/ChunkFileBrowser.vue";
import CustomSelect from "../components/CustomSelect.vue";
import { copyTextToClipboard } from "../clipboard";
import {
  artifactActionLabel,
  archiveSourceLabel,
  artifactKindForMode,
  availabilityStatesForMode,
  availableArchiveModes,
  buildArchiveOverview,
  buildSyncStatusPresentation,
  domainActionSupport,
  domainFieldSupport,
  domainModeLabel,
  hoyoArtifactCardPresentation,
  hoyoLanguageLabel,
  isAvailabilityActionable,
  latestLiveProbeTime,
  preferredArtifactAction,
  preferredDomainArtifactAction,
  displayVersionLabel,
  versionSupportsMode,
} from "../domain-presentation";
import { gameIcons } from "../game-icons";
import { publisherGroups } from "../game-meta";
import SourceProvenanceModal from "../components/SourceProvenanceModal.vue";
import { useArchiveLoader } from "../composables/useArchiveLoader";
import type {
  ArchiveDomain,
  ArchiveLead,
  Artifact,
  ChunkManifestDetail,
  ChunkManifestSummaryItem,
  Game,
  VersionRecord,
  VersionSummary,
} from "../types";

const route = useRoute();
const router = useRouter();
const showProvenanceModal = ref(false);
const provenanceOrigin = ref<{ x: number; y: number } | null>(null);

function openProvenanceModal(event?: MouseEvent): void {
  if (event?.currentTarget) {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    provenanceOrigin.value = {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };
  } else if (typeof window !== "undefined") {
    provenanceOrigin.value = {
      x: window.innerWidth - 60,
      y: 40,
    };
  }
  showProvenanceModal.value = true;
}

const artifacts = ref<Artifact[]>([]);
const remoteTreeProbeTime = ref<string | null>(null);
const chunkCollection = ref<ChunkManifestSummaryItem[]>([]);
const chunkDetail = ref<ChunkManifestDetail | null>(null);
const chunkLoading = ref(false);
const chunkError = ref<string | null>(null);
const leads = ref<ArchiveLead[]>([]);
const nextCursor = ref<string | null>(null);
const query = ref(String(route.query.q || ""));
const initialAvailability = String(route.query.availability || "all");
const availabilityFilter = ref<"all" | "available" | "unavailable" | "unknown">(
  ["available", "unavailable", "unknown"].includes(initialAvailability)
    ? (initialAvailability as "available" | "unavailable" | "unknown")
    : "all",
);
const loadingMore = ref(false);
const toast = ref("");
const error = ref<Error | null>(null);
let artifactController: AbortController | null = null;
let artifactRequestId = 0;
const SEARCHABLE_MODES = new Set(["apk", "chunks", "files", "packages", "patches"]);

function invalidateArtifactLoad(): void {
  artifactController?.abort();
  artifactController = null;
  artifactRequestId += 1;
  chunkLoading.value = false;
}

const {
  games,
  domains,
  versions,
  versionsDomainId,
  loading,
  registryError,
  scopedNotFound,
  registryTargetGame,
  registryTargetDomain,
  loadRegistry,
  dispose: disposeArchiveLoader,
} = useArchiveLoader({
  route,
  router,
  searchableModes: SEARCHABLE_MODES,
  loadArtifacts,
  invalidateArtifactLoad,
});

const gameId = computed(() => String(route.params.gameId || ""));
const domainId = computed(() => String(route.params.domainId || domains.value[0]?.id || ""));
const selectedVersion = computed(() => String(route.params.version || versions.value[0]?.version || ""));
const mode = computed(() =>
  String(route.params.mode || domains.value.find((item) => item.id === domainId.value)?.capabilities[0] || ""),
);
const game = computed(() => games.value.find((item) => item.id === gameId.value) || null);
const domain = computed(() => domains.value.find((item) => item.id === domainId.value) || null);
const railGroups = computed(() => publisherGroups(games.value));
const sidebarGameSearch = ref("");
const filteredRailGroups = computed(() => {
  const query = sidebarGameSearch.value.trim().toLowerCase();
  if (!query) return railGroups.value;

  return railGroups.value
    .map((group) => ({
      publisher: group.publisher,
      games: group.games.filter(
        (g) =>
          g.name.toLowerCase().includes(query) ||
          g.sub_name.toLowerCase().includes(query) ||
          g.id.toLowerCase().includes(query),
      ),
    }))
    .filter((group) => group.games.length > 0);
});
const uiModes = computed(() => availableArchiveModes(domains.value));
const visibleModes = computed(() => {
  return uiModes.value;
});
const selectedSummary = computed(
  () => versions.value.find((item) => item.version === selectedVersion.value) || null,
);
const selectedDisplayVersion = computed(() =>
  displayVersionLabel(selectedVersion.value, selectedSummary.value?.attributes),
);

const channelVersions = computed(() => {
  if (!selectedVersion.value) return [] as typeof versions.value;
  const base = displayVersionLabel(selectedVersion.value, selectedSummary.value?.attributes);
  return versions.value.filter(
    (item) => item.version !== selectedVersion.value && displayVersionLabel(item.version, item.attributes) === base,
  );
});
const gamePackageCount = computed(
  () => artifacts.value.filter((item) => item.attributes?.component !== "voice").length,
);
const compareBaseOptions = computed(() =>
  versions.value.filter((item) => item.version !== selectedVersion.value),
);
const compareDomains = computed(() =>
  domains.value.filter((item) => item.capabilities.includes("compare")),
);
function comparePlatformLabel(item: ArchiveDomain): string {
  if (item.adapter === "android" || item.platform?.toLowerCase() === "android" || item.kind === "apk") {
    return "Android 官方客户端";
  }
  if (item.adapter === "hoyo") {
    return "HOYO PC 客户端";
  }
  if (item.platform?.toLowerCase() === "windows" || item.platform?.toLowerCase() === "pc") {
    return "PC 客户端";
  }
  return item.platform || item.id;
}
async function switchCompareDomain(targetDomain: ArchiveDomain): Promise<void> {
  if (targetDomain.id === domainId.value) return;
  await navigate({
    domainId: targetDomain.id,
    version: selectedVersion.value || targetDomain.latest_version || "",
    mode: "compare",
  });
}
const compareBaseVersion = computed(() => {
  const requested = String(route.query.from || "");
  if (requested && requested !== selectedVersion.value && versions.value.some((item) => item.version === requested)) {
    return requested;
  }
  const currentIndex = versions.value.findIndex((item) => item.version === selectedVersion.value);
  return versions.value[currentIndex + 1]?.version || compareBaseOptions.value[0]?.version || "";
});
function hasHoyoPackageFiles(summary: VersionSummary | null | undefined): boolean {
  return Number(summary?.artifact_kinds?.package?.count || 0) > 0;
}
const compareBaseSummary = computed(
  () => versions.value.find((item) => item.version === compareBaseVersion.value) || null,
);
const compareScope = computed<"artifacts" | "files">(() => {
  if (domain.value?.adapter === "perfectworld_patcher" || domain.value?.adapter === "nte" || domain.value?.adapter === "wuwa") {
    return "files";
  }
  if (domain.value?.adapter === "hoyo" && hasHoyoPackageFiles(selectedSummary.value) && hasHoyoPackageFiles(compareBaseSummary.value)) {
    return "files";
  }
  return "artifacts";
});
const searchableMode = computed(() => SEARCHABLE_MODES.has(mode.value));
const isFileTreeMode = computed(
  () => mode.value === "files" && ["patchersdk", "perfectworld_patcher", "wuwa", "hoyo"].includes(domain.value?.adapter || ""),
);
const usesArtifactTree = computed(() => isFileTreeMode.value && Boolean(query.value.trim()));
const usesRemoteTree = computed(() => mode.value === "resources" || (isFileTreeMode.value && !query.value.trim()));
const exportArtifactKind = computed(() => artifactKindForMode(mode.value));
const supportsArtifactField = (field: string) =>
  domainFieldSupport(domain.value, "artifact_fields", field) === "supported";
const supportsDomainAction = (action: string) => domainActionSupport(domain.value, action);
const canExportArtifacts = computed(() => mode.value !== "files" && mode.value !== "apk" && Boolean(exportArtifactKind.value));
const canExportUrls = computed(
  () => canExportArtifacts.value && (supportsDomainAction("download") || supportsDomainAction("open") || supportsArtifactField("urls")),
);
const canFilterAvailability = computed(() => {
  if (!supportsArtifactField("availability")) return false;
  if (!["apk", "packages", "patches"].includes(mode.value)) return false;
  const kind = exportArtifactKind.value;
  const kindSummary = kind ? selectedSummary.value?.artifact_kinds?.[kind] : null;
  const total = kind ? (kindSummary?.count ?? 0) : (selectedSummary.value?.artifact_count || artifacts.value.length || 0);
  return total > 1;
});
const availabilityStateForRequest = computed(() =>
  mode.value === "files" || availabilityFilter.value === "all" ? undefined : availabilityFilter.value,
);
const usesPreferredUrlPresentation = computed(
  () =>
    supportsArtifactField("urls") &&
    supportsArtifactField("availability") &&
    Boolean(domain.value?.capability_contract?.url_source_kinds?.includes("mirror")),
);
const displayedAvailabilityFilters = computed(() => {
  const kind = exportArtifactKind.value;
  const kindSummary = kind ? selectedSummary.value?.artifact_kinds?.[kind] : null;
  const states = availabilityStatesForMode(selectedSummary.value, mode.value);
  const total = kind ? kindSummary?.count ?? 0 : selectedSummary.value?.artifact_count || 0;
  const list: Array<{ id: "all" | "available" | "unavailable" | "unknown"; label: string; count: number }> = [
    { id: "all", label: "全部状态", count: total },
    { id: "available", label: "可用", count: states.available || 0 },
    { id: "unavailable", label: "失效", count: states.unavailable || 0 },
  ];
  if ((states.unknown || 0) > 0) {
    list.push({ id: "unknown", label: "未判定", count: states.unknown || 0 });
  }
  return list;
});
const availabilityFilters = displayedAvailabilityFilters;

const exportUrlsCount = computed(() => {
  const states = availabilityStatesForMode(selectedSummary.value, mode.value);
  return states.available ?? 0;
});

const exportUrlsLabel = computed(() => {
  if (mode.value === "chunks") {
    const count = chunkDetail.value?.manifests?.length || artifacts.value.length || 0;
    return count > 0 ? `导出 Manifest 链接 · ${count}` : "导出 Manifest 链接";
  }
  const count = exportUrlsCount.value;
  return count > 0 ? `导出可用 URL · ${count}` : "导出 URL";
});

const isWuwaFilesMode = computed(() => domain.value?.adapter === "wuwa" && mode.value === "files");
const rawIndexMenuOpen = ref(false);
const copiedManifestUrl = ref(false);
const copiedBaseUrl = ref(false);

const wuwaManifestUrl = computed(() => {
  const meta = selectedSummary.value?.attributes?.manifest_urls;
  if (Array.isArray(meta) && typeof meta[0] === "string") return meta[0];
  const pkgArtifact = artifacts.value.find((a) => a.kind === "package");
  if (pkgArtifact) return manifestUrlFor(pkgArtifact) || "";
  return "";
});

const wuwaBaseUrl = computed(() => {
  const meta = selectedSummary.value?.attributes?.base_urls;
  if (Array.isArray(meta) && typeof meta[0] === "string") return meta[0];
  const pkgArtifact = artifacts.value.find((a) => a.kind === "package");
  if (pkgArtifact) return baseUrlFor(pkgArtifact) || "";
  return "";
});

const wuwaManifestShort = computed(() => {
  if (!wuwaManifestUrl.value) return "indexFile.json";
  try {
    const parsed = new URL(wuwaManifestUrl.value);
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    return pathParts.at(-1) || "indexFile.json";
  } catch {
    return "indexFile.json";
  }
});

const wuwaBaseUrlShort = computed(() => {
  if (!wuwaBaseUrl.value) return "pcdownload-aliyun.../zip/";
  try {
    const parsed = new URL(wuwaBaseUrl.value);
    const hostPrefix = parsed.hostname.split(".")[0] || "";
    return `${hostPrefix}.../zip/`;
  } catch {
    return ".../zip/";
  }
});

async function copyWuwaManifestUrl(): Promise<void> {
  if (wuwaManifestUrl.value) {
    await copyUrl(wuwaManifestUrl.value);
    copiedManifestUrl.value = true;
    setTimeout(() => {
      copiedManifestUrl.value = false;
    }, 1800);
  }
}

async function copyWuwaBaseUrl(): Promise<void> {
  if (wuwaBaseUrl.value) {
    await copyUrl(wuwaBaseUrl.value);
    copiedBaseUrl.value = true;
    setTimeout(() => {
      copiedBaseUrl.value = false;
    }, 1800);
  }
}

function toggleRawIndexMenu(): void {
  rawIndexMenuOpen.value = !rawIndexMenuOpen.value;
  if (rawIndexMenuOpen.value) {
    activeFileMenuId.value = null;
    window.dispatchEvent(new CustomEvent("gmi-close-file-menus"));
  }
}

function onWindowRawIndexClick(e: MouseEvent): void {
  const target = e.target as HTMLElement | null;
  if (!target?.closest(".raw-manifest-dropdown")) {
    rawIndexMenuOpen.value = false;
  }
}

function onCloseRawIndex(): void {
  rawIndexMenuOpen.value = false;
}

function onWindowKeyDown(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    rawIndexMenuOpen.value = false;
    activeFileMenuId.value = null;
  }
}

function formatCategoryLabel(cat: string): string {
  if (cat === "游戏包分卷") return "游戏分卷";
  if (cat === "全部") return "全部文件";
  if (cat.endsWith("语音更新")) return cat.replace("更新", "");
  return cat;
}

function artifactCategory(artifact: Artifact): string {
  if (domain.value?.adapter === "hoyo") {
    const pres = hoyoArtifactCardPresentation(artifact, selectedVersion.value);
    return pres.label;
  }
  if (artifact.attributes?.component === "voice" || artifact.attributes?.component === "audio") {
    const lang = artifact.attributes.language ? hoyoLanguageLabel(artifact.attributes.language) : "";
    return lang ? `${lang}语音` : "语音包";
  }
  if (artifact.kind === "patch") {
    return "更新补丁";
  }
  if (artifact.kind === "package") {
    if (domain.value?.adapter === "wuwa" || isFileManifestArtifact(artifact)) return "资源清单";
    if (artifact.part || artifact.attributes?.route_part) return "游戏分卷";
    return "游戏完整包";
  }
  if (artifact.kind === "file") {
    return "散文件";
  }
  if (artifact.kind === "manifest") {
    return "清单文件";
  }
  if (artifact.kind === "apk") {
    return "官方安装包";
  }
  return "全部文件";
}

const selectedCategory = ref<string>("all");

const categoryFilters = computed(() => {
  if (!artifacts.value.length) return [];
  const counts: Record<string, number> = {};
  for (const artifact of artifacts.value) {
    const cat = artifactCategory(artifact);
    counts[cat] = (counts[cat] || 0) + 1;
  }
  const keys = Object.keys(counts);
  if (keys.length <= 1) return [];
  const list = [{ id: "all", label: "全部文件", count: artifacts.value.length }];
  for (const key of keys) {
    list.push({ id: key, label: formatCategoryLabel(key), count: counts[key] });
  }
  return list;
});

const chunkCategoryFilter = ref<string>("all");

const chunkFilterOptions = computed(() => {
  if (!chunkDetail.value?.manifests?.length) return [];
  const manifests = chunkDetail.value.manifests;
  const list: Array<{ key: string; label: string; count: number }> = [
    { key: "all", label: "全部清单", count: manifests.length },
  ];
  const gameManifests = manifests.filter((m) => m.component === "game");
  if (gameManifests.length > 0) {
    list.push({ key: "game", label: "游戏主资源", count: gameManifests.length });
  }
  const voiceManifests = manifests.filter((m) => m.component === "voice");
  const langSeen = new Set<string>();
  for (const vm of voiceManifests) {
    const lang = vm.language?.toLowerCase() || "voice";
    if (!langSeen.has(lang)) {
      langSeen.add(lang);
      const count = voiceManifests.filter((m) => (m.language?.toLowerCase() || "voice") === lang).length;
      list.push({ key: lang, label: `${hoyoLanguageLabel(vm.language) || vm.language || "语音"}语音`, count });
    }
  }
  return list;
});

const displayedArtifacts = computed(() => {
  if (selectedCategory.value === "all") return artifacts.value;
  return artifacts.value.filter((artifact) => artifactCategory(artifact) === selectedCategory.value);
});

function chunkArtifactMatchesFilter(artifact: Artifact): boolean {
  const filter = chunkCategoryFilter.value;
  if (filter === "all") return true;
  const component = String(artifact.attributes?.component || "game").toLowerCase();
  if (filter === "game") return component === "game";
  const language = String(artifact.attributes?.language || "voice").toLowerCase();
  return component === "voice" && language === filter;
}

const footerProbeArtifacts = computed(() => {
  if (mode.value === "chunks") return artifacts.value.filter(chunkArtifactMatchesFilter);
  if (usesRemoteTree.value || (mode.value === "files" && domain.value?.adapter === "hoyo")) return [];
  if (usesArtifactTree.value) return artifacts.value;
  if (["packages", "patches"].includes(mode.value) && usesPreferredUrlPresentation.value && domain.value?.adapter !== "wuwa") {
    return artifacts.value;
  }
  return displayedArtifacts.value;
});

function versionRecordState(record: VersionRecord): "available" | "unavailable" | "unknown" {
  return record.status.available === true
    ? "available"
    : record.status.available === false
      ? "unavailable"
      : "unknown";
}

function formatChecksum(artifact: Artifact): string {
  if (!artifact.checksum_value) return "—";
  const type = (artifact.checksum_type || (artifact.checksum_value.length === 32 ? "MD5" : "CRC64")).toUpperCase();
  return `${type}: ${artifact.checksum_value}`;
}

function versionRecordArtifact(record: VersionRecord, id: number): Artifact {
  const state = versionRecordState(record);
  const verified = record.status.http_code !== null && record.status.last_checked_at !== null;
  const checksumType = record.checksum.md5 ? "md5" : record.checksum.crc64 ? "crc64" : null;
  const checksumValue = record.checksum.md5 || record.checksum.crc64;
  const current = {
    state,
    reason: record.status.http_code === null ? "无有效探测结果" : `HTTP ${record.status.http_code}`,
    confidence: state === "unknown" ? "low" as const : "high" as const,
    retained: false,
    checked_at: record.status.last_checked_at,
    source_kind: "live_probe",
    source_confidence: verified ? "high" : "low",
    observed_at: record.status.last_checked_at,
    expires_at: null,
    evidence_status: verified ? "verified" as const : "unverified" as const,
  };
  return {
    id,
    kind: "apk",
    name: record.filename,
    part: 1,
    size: record.size,
    checksum_type: checksumType,
    checksum_value: checksumValue,
    attributes: {
      vendor: record.vendor,
      game_id: record.game_id,
      channel: record.channel,
      version_code: record.version_code,
      etag: record.checksum.etag,
      crc64: record.checksum.crc64,
      http_code: record.status.http_code,
    },
    urls: [{
      id,
      url: record.url,
      priority: 0,
      source_kind: "official",
      provider: record.vendor,
      evidence_status: current.evidence_status,
      current,
    }],
  };
}
const availabilityEvidenceNote = computed(
  () => "“可用”只表示受限 Range 请求收到有效内容，不保证完整文件传输或所有下载器兼容。",
);
const fileWorkspaceSubtitle = "列表 / 对比 / Chunk";
const panelEyebrow = computed(() => {
  if (mode.value === "resources") {
    return gameId.value === "endfield" ? "Endfield Windows resources" : "Aether Gazer resources";
  }
  if (["patchersdk", "perfectworld_patcher"].includes(domain.value?.adapter || "") && mode.value === "files") return `${gameId.value.toUpperCase()} files`;
  if (domain.value?.adapter === "arknights" && mode.value === "packages") return "Arknights packages";
  if (mode.value === "legacy") return "Historical candidates";
  if (domain.value?.adapter === "hoyo") return "HOYO PC 客户端";
  if (domain.value?.adapter === "android" || domain.value?.kind === "apk") return "Android 官方客户端";
  if (domain.value?.adapter === "wuwa") return "Wuwa files";
  return modeLabel(domain.value, mode.value);
});
const panelTitle = computed(() => {
  if (mode.value === "compare") return `${selectedVersion.value} 版本对比`;
  if (mode.value === "manifest") return "官方清单文件";
  if (mode.value === "archive") return `${selectedVersion.value} 归档信息`;
  if (mode.value === "legacy") return "候选线索";
  return `${selectedDisplayVersion.value} ${modeLabel(domain.value, mode.value)}`;
});
const displayGameName = computed(() => {
  const current = game.value;
  if (!current) return gameId.value;
  return /[\u3400-\u9fff]/.test(current.name) ? current.name : current.sub_name || current.name;
});
const displayGameSubtitle = computed(() => {
  const current = game.value;
  if (!current) return "";
  return displayGameName.value === current.name ? current.sub_name : current.name;
});
const chunkSummary = computed(() => {
  const rows = artifacts.value.filter((item) => item.kind === "chunk");
  const numeric = (item: Artifact, key: string) => Number(item.attributes?.[key] || 0);
  return {
    buildId: String(rows[0]?.attributes?.build_id || "—"),
    manifests: selectedSummary.value?.artifact_kinds?.chunk?.count || rows.length,
    files: rows.reduce((sum, item) => sum + numeric(item, "file_count"), 0),
    chunks: rows.reduce((sum, item) => sum + numeric(item, "chunk_count"), 0),
    compressed: rows.reduce((sum, item) => sum + item.size, 0),
    uncompressed: rows.reduce((sum, item) => sum + numeric(item, "uncompressed_size"), 0),
  };
});
const kindSummary = (kind: string) => selectedSummary.value?.artifact_kinds?.[kind] || { count: 0, size: 0 };
const archiveOverview = computed(() =>
  buildArchiveOverview({
    domain: domain.value,
    summary: selectedSummary.value,
    mode: mode.value,
    version: selectedVersion.value,
    displayVersion: selectedDisplayVersion.value,
    channelSummaries: channelVersions.value,
    formatBytes,
    formatDate: formatObservedDate,
  }),
);

const adapterSourceLabel = (adapter: string | undefined, sourceKind?: unknown): string => {
  return archiveSourceLabel(adapter, sourceKind);
};

const syncStatus = computed(() => {
  const latest = versions.value[0] || null;
  const presentation = buildSyncStatusPresentation({
    domains: domains.value,
    currentDomain: domain.value,
    currentLatest: latest,
  });
  const currentDomainSummary = latest || selectedSummary.value || null;
  const primarySummary = presentation.primaryDomain?.id === domain.value?.id ? latest : currentDomainSummary;
  const observed = primarySummary?.observed_at
    || primarySummary?.source_updated_at
    || primarySummary?.source_released_at
    || primarySummary?.archived_at
    || null;
  const packages = Number(primarySummary?.artifact_kinds?.package?.count ?? 0);
  const patches = Number(primarySummary?.artifact_kinds?.patch?.count ?? 0);
  return {
    title: `${displayGameName.value} 最新归档`,
    primaryLabel: presentation.primaryLabel,
    primaryLatest: presentation.primaryLatest,
    syncedAt: observed,
    source: adapterSourceLabel(presentation.primaryDomain?.adapter || domain.value?.adapter, selectedSummary.value?.provenance?.source_kind),
    detail: `${packages.toLocaleString()} 个压缩包 / ${patches.toLocaleString()} 个更新包`,
    androidSecondary: presentation.androidSecondary,
  };
});

const versionMetaSummary = computed(() => {
  const summary = selectedSummary.value;
  const dom = domain.value;
  if (!summary || !dom) return [];

  const items: Array<{ label: string; value: string; isMono?: boolean }> = [];

  // 1. 总大小 (仅多分卷/多文件时在顶部汇总展示，单文件不重复)
  const kind = mode.value === "apk" ? "apk" : mode.value === "packages" ? "package" : mode.value === "patches" ? "patch" : "";
  const count = kind ? (summary.artifact_kinds?.[kind]?.count || 0) : (summary.artifact_count || 0);
  const size = kind ? (summary.artifact_kinds?.[kind]?.size || 0) : (summary.packed_size || 0);
  if (size > 0 && count > 1) {
    items.push({ label: "总大小", value: formatBytes(size), isMono: true });
  }

  // 2. 日期语义区分（优先展示 Manifest 更新时间或官方发布时间）
  const attrs = (summary.attributes || {}) as Record<string, unknown>;
  const manifestTime = (typeof attrs.manifest_modified_at === "string" ? attrs.manifest_modified_at : "") ||
    (chunkDetail.value?.manifests?.[0]?.last_modified_at || "");
  const releaseTime = summary.source_released_at;
  const updateTime = summary.source_updated_at;
  const apkFileTime = mode.value === "apk" ? summary.observed_at : null;
  const importedTime = summary.archived_at || summary.imported_at;

  if (mode.value === "chunks" && manifestTime) {
    const formatted = formatObservedDate(manifestTime);
    if (formatted && formatted !== "不支持" && formatted !== "-") {
      items.push({ label: "Manifest 更新时间", value: formatted, isMono: true });
    }
  } else if (releaseTime) {
    const formatted = formatObservedDate(releaseTime);
    if (formatted && formatted !== "不支持" && formatted !== "-") {
      items.push({ label: "发布时间", value: formatted, isMono: true });
    }
  } else if (manifestTime) {
    const formatted = formatObservedDate(manifestTime);
    if (formatted && formatted !== "不支持" && formatted !== "-") {
      items.push({ label: "Manifest 更新时间", value: formatted, isMono: true });
    }
  } else if (updateTime) {
    const formatted = formatObservedDate(updateTime);
    if (formatted && formatted !== "不支持" && formatted !== "-") {
      items.push({ label: "更新时间", value: formatted, isMono: true });
    }
  } else if (apkFileTime) {
    const formatted = formatObservedDate(apkFileTime);
    if (formatted && formatted !== "不支持" && formatted !== "-") {
      items.push({ label: "文件时间", value: formatted, isMono: true });
    }
  } else if (importedTime) {
    const formatted = formatObservedDate(importedTime);
    if (formatted && formatted !== "不支持" && formatted !== "-") {
      items.push({ label: "数据导入时间", value: formatted, isMono: true });
    }
  }

  // 3. 渠道 (仅特殊渠道时展示)
  const channel = typeof attrs.channel === "string" ? attrs.channel : "";
  if (channel && channel !== "official" && channel !== "-" && channel !== "官方") {
    items.push({ label: "渠道", value: channel });
  }

  return items;
});

const syncTimeText = computed(() => {
  const time = latestLiveProbeTime(footerProbeArtifacts.value) || remoteTreeProbeTime.value;
  if (!time) return "";
  const formatted = formatObservedDate(time);
  const rel = formatRelativeTime(time);
  return rel ? `${formatted} (${rel})` : formatted;
});
const currentVersionApiUrl = computed(() => {
  if (!domainId.value || !selectedVersion.value) return "";
  if (mode.value === "chunks") {
    return apiUrl(`/domains/${encodeURIComponent(domainId.value)}/versions/${encodeURIComponent(selectedVersion.value)}/chunk-manifests`);
  }
  if (mode.value === "files" && ["hoyo", "perfectworld_patcher"].includes(domain.value?.adapter || "")) {
    return apiUrl(`/domains/${encodeURIComponent(domainId.value)}/versions/${encodeURIComponent(selectedVersion.value)}/files`);
  }
  return apiUrl(`/domains/${encodeURIComponent(domainId.value)}/versions/${encodeURIComponent(selectedVersion.value)}`);
});

const provenanceSource = computed(() => {
  if (domain.value?.adapter === "hoyo") {
    return { label: "hoyo-files.amarea.cn", href: "https://hoyo-files.amarea.cn/" };
  }
  if (domain.value?.adapter === "wuwa") {
    if (selectedSummary.value?.provenance?.source_kind === "legacy_migration") {
      return { label: "Game-Manifest-Index（历史迁移）", href: "https://github.com/yuhkix/wuwa-downloader" };
    }
    return { label: "yuhkix/wuwa-downloader", href: "https://github.com/yuhkix/wuwa-downloader" };
  }
  if (domain.value?.adapter === "perfectworld_patcher") {
    return { label: "完美世界官方 PatcherSDK", href: "https://wmupd.com/" };
  }
  if (gameId.value === "endfield") {
    return { label: "上游资源归档", href: "https://ak-endfield-api-archive.daydreamer-json.cc/" };
  }
  if (domain.value?.adapter === "arknights") {
    return { label: "明日方舟 PC 官网", href: "https://ak.hypergryph.com/pcs" };
  }
  return { label: "GitHub 仓库", href: "https://github.com/kuaichu/Game-Manifest-Index" };
});
const legacyLeads = computed(() =>
  [...leads.value].sort((left, right) =>
    String(left.generated_at || "").localeCompare(String(right.generated_at || "")),
  ),
);
function legacyArchiveUrl(lead: ArchiveLead): string | undefined {
  const url = lead.urls[0];
  const timestamp = String(url?.archive_facts.timestamp || "");
  return timestamp && url?.url ? `https://web.archive.org/web/${timestamp}/${url.url}` : undefined;
}

async function navigate(params: Record<string, string>): Promise<void> {
  const nextParams = { ...route.params, ...params };
  const targetMode = String(nextParams.mode || mode.value);
  const targetVersion = String(nextParams.version || selectedVersion.value);
  const nextQuery: Record<string, string> = {};
  if (SEARCHABLE_MODES.has(targetMode) && String(route.query.q || "").trim()) {
    nextQuery.q = String(route.query.q).trim();
  }
  if (
    !["files", "legacy", "archive", "compare", "manifest"].includes(targetMode) &&
    String(route.query.availability || "")
  ) {
    nextQuery.availability = String(route.query.availability);
  }
  if (targetMode === "files") {
    if (route.query.source) nextQuery.source = String(route.query.source);
    if (route.query.identity) nextQuery.identity = String(route.query.identity);
    if (route.query.path) nextQuery.path = String(route.query.path);
  }
  const requestedFrom = String(route.query.from || "");
  // Keep a user-selected compare base across platform switches; loadRegistry()
  // validates it against the destination domain and falls back if absent.
  if (targetMode === "compare" && requestedFrom && requestedFrom !== targetVersion) {
    nextQuery.from = requestedFrom;
  }
  await router.push({ name: "archive", params: nextParams, query: nextQuery });
}

async function navigateMode(targetDomain: ArchiveDomain, targetMode: string): Promise<void> {
  const destDomain = (targetMode === "compare" && domain.value?.capabilities.includes("compare"))
    ? domain.value
    : targetDomain;
  const sameDomain = destDomain.id === domainId.value;
  const scopesHoYoVersions = destDomain.adapter === "hoyo"
    && ["packages", "patches", "chunks"].includes(targetMode);
  const currentSupportsMode = !scopesHoYoVersions || (sameDomain && selectedSummary.value
    ? versionSupportsMode(selectedSummary.value, targetMode, destDomain.adapter)
    : false);
  const targetVersion = currentSupportsMode
    ? selectedVersion.value
    : sameDomain
      ? versions.value.find((item) => versionSupportsMode(item, targetMode, destDomain.adapter))?.version || selectedVersion.value
      : destDomain.latest_version || "";
  await navigate({
    domainId: destDomain.id,
    version: targetVersion,
    mode: targetMode,
  });
}

function saveTextFile(filename: string, content: string, type: string): void {
  const href = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(href), 0);
}

async function exportArtifacts(format: "urls" | "json"): Promise<void> {
  if (!canExportArtifacts.value || (format === "urls" && !canExportUrls.value)) return;
  const exportController = new AbortController();
  try {
    if (mode.value === "chunks") {
      const stem = `${gameId.value}-${selectedVersion.value}-chunk-manifests`;
      if (format === "json") {
        const payload = chunkDetail.value || {
          domain_id: domainId.value,
          version: selectedVersion.value,
          manifests: artifacts.value,
        };
        saveTextFile(`${stem}.json`, `${JSON.stringify(payload, null, 2)}\n`, "application/json;charset=utf-8");
        toast.value = "已生成 1 项 Chunk Manifest JSON";
      } else {
        const urls: string[] = [];
        if (chunkDetail.value?.manifests?.length) {
          for (const m of chunkDetail.value.manifests) {
            const prefix = m.manifest_download?.url_prefix || "";
            const id = m.manifest?.id || m.manifest_id || "";
            if (prefix && id) urls.push(`${prefix.replace(/\/+$/, "")}/${id}`);
          }
        } else {
          for (const art of artifacts.value) {
            const url = artifactDownloadUrl(art) || preferredDomainArtifactAction(domain.value, art, "download")?.url || rawArtifactUrl(art);
            if (url) urls.push(url);
          }
        }
        saveTextFile(`${stem}.urls.txt`, `${urls.join("\n")}\n`, "text/plain;charset=utf-8");
        toast.value = `已生成 ${urls.length} 项 Manifest URL 列表`;
      }
      return;
    }
    if (mode.value === "apk") {
      const record = await api.versionRecord(domainId.value, selectedVersion.value, exportController.signal);
      const stem = `${gameId.value}-${selectedVersion.value}-${mode.value}`;
      if (format === "json") {
        saveTextFile(`${stem}.json`, `${JSON.stringify(record, null, 2)}\n`, "application/json;charset=utf-8");
      } else {
        saveTextFile(`${stem}.urls.txt`, `${record.url}\n`, "text/plain;charset=utf-8");
      }
      toast.value = `已生成 1 项${format === "json" ? " JSON" : " URL 列表"}`;
      return;
    }
    const rows = await api.allArtifacts(
      domainId.value,
      selectedVersion.value,
      {
        kind: exportArtifactKind.value,
        query: searchableMode.value ? query.value.trim() : "",
      },
      exportController.signal,
    );
    const stem = `${gameId.value}-${selectedVersion.value}-${mode.value}`;
    if (format === "json") {
      saveTextFile(`${stem}.json`, `${JSON.stringify(rows, null, 2)}\n`, "application/json;charset=utf-8");
    } else {
      const content = rows
        .map((item) => artifactDownloadUrl(item) || preferredDomainArtifactAction(domain.value, item, "download")?.url || rawArtifactUrl(item))
        .filter((url): url is string => Boolean(url))
        .join("\n");
      saveTextFile(`${stem}.urls.txt`, `${content}\n`, "text/plain;charset=utf-8");
    }
    toast.value = `已生成 ${rows.length} 项${format === "json" ? " JSON" : " 批量 URL 文件"}`;
  } catch (reason) {
    toast.value = reason instanceof Error ? reason.message : "生成导出文件失败";
  } finally {
    window.setTimeout(() => {
      toast.value = "";
    }, 2400);
  }
}

async function loadArtifacts(append: boolean): Promise<void> {
  if (!domainId.value || !selectedVersion.value) return;
  const resolvedDomain = domains.value.find((item) => item.id === domainId.value);
  if (
    resolvedDomain?.game_id !== gameId.value ||
    versionsDomainId.value !== domainId.value ||
    !versions.value.some((item) => item.version === selectedVersion.value)
  ) {
    return;
  }
  const requestId = ++artifactRequestId;
  artifactController?.abort();
  const request = new AbortController();
  artifactController = request;
  const isCurrent = () => artifactRequestId === requestId && artifactController === request && !request.signal.aborted;
  if (!append) {
    selectedCategory.value = "all";
    chunkCategoryFilter.value = "all";
    remoteTreeProbeTime.value = null;
  }
  error.value = null;
  try {
    if (mode.value === "chunks") {
      artifacts.value = [];
      nextCursor.value = null;
      chunkLoading.value = true;
      chunkError.value = null;
      try {
        const [collRes, detailRes, artRes] = await Promise.allSettled([
          api.chunkManifestCollection(domainId.value, request.signal),
          api.chunkManifests(domainId.value, selectedVersion.value, request.signal),
          api.artifacts(
            domainId.value,
            selectedVersion.value,
            {
              query: query.value.trim(),
              kind: "chunk",
              limit: 100,
            },
            request.signal,
          ),
        ]);
        if (!isCurrent()) return;
        if (collRes.status === "fulfilled") {
          chunkCollection.value = collRes.value?.items || [];
        } else {
          chunkCollection.value = [];
        }
        if (detailRes.status === "fulfilled") {
          chunkDetail.value = detailRes.value;
        } else {
          chunkDetail.value = null;
        }
        if (artRes.status === "fulfilled" && artRes.value?.items?.length) {
          artifacts.value = artRes.value.items;
        }
      } catch (err) {
        if (!isAbortError(err)) {
          chunkError.value = err instanceof Error ? err.message : "读取 Chunk Manifest 失败";
        }
      } finally {
        if (isCurrent()) chunkLoading.value = false;
      }
      return;
    }
    if (mode.value === "files" && domain.value?.adapter === "hoyo") {
      artifacts.value = [];
      nextCursor.value = null;
      chunkLoading.value = true;
      chunkError.value = null;
      try {
        const [collRes, detailRes] = await Promise.allSettled([
          api.chunkManifestCollection(domainId.value, request.signal),
          api.chunkManifests(domainId.value, selectedVersion.value, request.signal),
        ]);
        if (!isCurrent()) return;
        if (collRes.status === "fulfilled") {
          chunkCollection.value = collRes.value?.items || [];
        }
        if (detailRes.status === "fulfilled") {
          chunkDetail.value = detailRes.value;
        } else {
          chunkDetail.value = null;
        }
      } catch (err) {
        if (!isAbortError(err)) {
          chunkDetail.value = null;
          chunkError.value = err instanceof Error ? err.message : "读取 Chunk Manifest 失败";
        }
      } finally {
        if (isCurrent()) chunkLoading.value = false;
      }
      return;
    }
    if (mode.value === "legacy") {
      artifacts.value = [];
      nextCursor.value = null;
      const loadedLeads = await api.leads(domainId.value, request.signal);
      if (!isCurrent()) return;
      leads.value = loadedLeads;
      return;
    }
    leads.value = [];
    if (mode.value === "compare") {
      artifacts.value = [];
      nextCursor.value = null;
      return;
    }
    if (usesRemoteTree.value) {
      artifacts.value = [];
      nextCursor.value = null;
      return;
    }
    if (usesArtifactTree.value) {
      const loadedArtifacts = await api.allArtifacts(
        domainId.value,
        selectedVersion.value,
        {
          kind: "file",
          query: query.value.trim(),
          state: availabilityStateForRequest.value,
        },
        request.signal,
      );
      if (!isCurrent()) return;
      artifacts.value = loadedArtifacts;
      nextCursor.value = null;
      return;
    }
    const baseVersion = selectedVersion.value;
    const channelTargets = channelVersions.value.length
      ? [baseVersion, ...channelVersions.value.map((item) => item.version)]
      : [baseVersion];
    if (mode.value === "apk") {
      const loaded: Artifact[] = [];
      const queryText = query.value.trim().toLocaleLowerCase();
      for (const [index, version] of channelTargets.entries()) {
        if (!isCurrent()) return;
        const record = await api.versionRecord(domainId.value, version, request.signal);
        if (!isCurrent()) return;
        if (queryText && !JSON.stringify(record).toLocaleLowerCase().includes(queryText)) continue;
        if (availabilityStateForRequest.value && versionRecordState(record) !== availabilityStateForRequest.value) continue;
        loaded.push(versionRecordArtifact(record, index + 1));
      }
      if (!isCurrent()) return;
      artifacts.value = loaded;
      nextCursor.value = null;
      return;
    }
    if (channelTargets.length > 1) {
      const loaded: Artifact[] = [];
      for (const version of channelTargets) {
        if (!isCurrent()) return;
        const page = await api.artifacts(
          domainId.value,
          version,
          {
            query: searchableMode.value ? query.value.trim() : "",
            state: availabilityStateForRequest.value,
            kind: artifactKindForMode(mode.value),
            limit: 500,
          },
          request.signal,
        );
        if (!isCurrent()) return;
        loaded.push(...page.items);
      }
      const seenArtifacts = new Set<string>();
      if (!isCurrent()) return;
      artifacts.value = loaded.filter((item) => {
        const key = String(item.name);
        if (seenArtifacts.has(key)) return false;
        seenArtifacts.add(key);
        return true;
      });
      nextCursor.value = null;
      return;
    }
    const page = await api.artifacts(
      domainId.value,
      selectedVersion.value,
      {
        cursor: append ? nextCursor.value : null,
        query: searchableMode.value ? query.value.trim() : "",
        state: availabilityStateForRequest.value,
        kind: artifactKindForMode(mode.value),
        limit: 50,
      },
      request.signal,
    );
    if (!isCurrent()) return;
    artifacts.value = append ? [...artifacts.value, ...page.items] : page.items;
    nextCursor.value = page.next_cursor;
  } catch (reason) {
    if (!isCurrent() || isAbortError(reason)) return;
    error.value = reason instanceof Error ? reason : new Error(String(reason));
  } finally {
    if (requestId === artifactRequestId) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

async function replaceQuery(name: "q" | "availability" | "from", value: string): Promise<void> {
  const next = { ...route.query };
  if (value && value !== "all") next[name] = value;
  else delete next[name];
  await router.replace({ name: "archive", params: route.params, query: next });
}

function updateCompareBase(value: string): void {
  void replaceQuery("from", value);
}
function onCompareBaseChange(event: Event): void {
  updateCompareBase((event.target as HTMLSelectElement).value);
}

let searchTimer: number | null = null;
watch(
  [
    () => String(route.params.gameId || ""),
    () => String(route.params.domainId || ""),
  ],
  () => {
    // While a load is in flight, its own normalize/alias replace lands on the
    // exact params it is already loading; any other change supersedes it.
    if (
      loading.value &&
      registryTargetGame.value === String(route.params.gameId || "") &&
      registryTargetDomain.value === String(route.params.domainId || "")
    ) return;
    void loadRegistry();
  },
);
watch(
  [() => String(route.params.version || ""), () => String(route.params.mode || "")],
  () => {
    if (
      loading.value ||
      versionsDomainId.value !== domainId.value ||
      !versions.value.some((item) => item.version === selectedVersion.value)
    ) return;
    void loadArtifacts(false);
  },
);
watch(query, () => {
  if (searchTimer !== null) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(async () => {
    await replaceQuery("q", query.value.trim());
    void loadArtifacts(false);
  }, 180);
});
watch(availabilityFilter, async () => {
  await replaceQuery("availability", availabilityFilter.value);
  void loadArtifacts(false);
});
watch(
  () => route.query.q,
  (value) => {
    const next = String(value || "");
    if (query.value !== next) query.value = next;
  },
);
watch(
  () => route.query.availability,
  (value) => {
    const next = String(value || "all");
    const valid = ["available", "unavailable", "unknown"].includes(next) ? next : "all";
    if (availabilityFilter.value !== valid) availabilityFilter.value = valid as typeof availabilityFilter.value;
  },
);
function updateFavicon(iconUrl?: string): void {
  let link: HTMLLinkElement | null = document.querySelector("link[rel*='icon']");
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  if (iconUrl) {
    link.href = iconUrl;
  }
}

watch(
  () => [displayGameName.value, gameId.value] as const,
  ([name, gId]) => {
    if (name) {
      document.title = `${name} · 官方文件索引 | GMI`;
      const icon = gId ? iconFor(gId) : undefined;
      if (icon) updateFavicon(icon);
    } else {
      document.title = "GMI - 游戏资源索引";
    }
  },
  { immediate: true },
);
watch(
  () => route.fullPath,
  (value) => {
    if (!value.startsWith("/games/")) return;
    try {
      localStorage.setItem("game-manifest-index-web-view-v1", value);
    } catch {
      // Storage unavailable
    }
  },
);
function onAvailabilityInvalidated(): void {
  void loadRegistry();
}
function onAvailabilityStorageInvalidated(event: StorageEvent): void {
  if (event.key === "gmi-availability-invalidated-at" && event.newValue) onAvailabilityInvalidated();
}
onMounted(() => {
  loadRegistry();
  window.addEventListener("click", onWindowRawIndexClick);
  window.addEventListener("keydown", onWindowKeyDown);
  window.addEventListener("gmi-close-raw-index", onCloseRawIndex);
  window.addEventListener("gmi-availability-invalidated", onAvailabilityInvalidated);
  window.addEventListener("storage", onAvailabilityStorageInvalidated);
});
onBeforeUnmount(() => {
  disposeArchiveLoader();
  artifactRequestId += 1;
  artifactController?.abort();
  if (searchTimer !== null) window.clearTimeout(searchTimer);
  window.removeEventListener("click", onWindowRawIndexClick);
  window.removeEventListener("keydown", onWindowKeyDown);
  window.removeEventListener("gmi-close-raw-index", onCloseRawIndex);
  window.removeEventListener("gmi-availability-invalidated", onAvailabilityInvalidated);
  window.removeEventListener("storage", onAvailabilityStorageInvalidated);
});

function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value,
    unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 2 : 0)} ${units[unit]}`;
}

function shortName(item: Game): string {
  return item.id.slice(0, 3).toUpperCase();
}
function iconFor(id: string): string | undefined {
  const source = games.value.find((item) => item.id === id)?.icon_source?.trim();
  if (source?.startsWith("builtin:")) return gameIcons[source.slice("builtin:".length)] || gameIcons[id];
  return source || gameIcons[id];
}
function useFallbackIcon(event: Event, id: string): void {
  const image = event.currentTarget as HTMLImageElement;
  const fallback = gameIcons[id];
  if (fallback && image.src !== fallback) image.src = fallback;
  else image.hidden = true;
}
function modeLabel(item: ArchiveDomain | null | undefined, capability: string): string {
  return domainModeLabel(item, capability);
}
function leadClassificationLabel(lead: ArchiveLead): string {
  const value = String(lead.urls[0]?.current_facts.classification || lead.inferred_context || "");
  return (
    ({
      complete_archived: "完整归档",
      partial_archived: "部分归档",
      missing_list: "清单缺失",
      malformed_list: "清单异常",
      historical_404: "历史 404",
      unresolved: "待确认",
    } as Record<string, string>)[value] || `${lead.platform || "未知平台"} 候选`
  );
}
function leadActionAllowed(lead: ArchiveLead, action: "open" | "copy"): boolean {
  return domainActionSupport(domain.value, action) && lead.urls[0]?.current_facts.action_allowed === true;
}
function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((result, part) => {
      if (part.type !== "literal") result[part.type] = part.value;
      return result;
    }, {});
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
}
function formatRelativeTime(value?: string | null): string {
  const date = observedDate(value);
  if (!date) return "-";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "刚刚";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} 天前`;
  return formatDate(value);
}
function observedDate(value?: string | null): Date | null {
  if (!value) return null;
  const normalized = /(?:z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}
function formatObservedDate(value?: string | null): string {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value.replaceAll("-", ".");
  const date = observedDate(value);
  if (!date) return "—";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((result, part) => {
      if (part.type !== "literal") result[part.type] = part.value;
      return result;
    }, {});
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
}
async function copyArtifactUrl(artifact: Artifact): Promise<void> {
  const url = preferredAvailableUrl(artifact, "copy") || rawArtifactUrl(artifact) || artifact.urls[0]?.url;
  await copyUrl(url);
}
async function copyUrl(url?: string): Promise<void> {
  if (!url) return;
  toast.value = (await copyTextToClipboard(url)) ? "链接已复制" : "复制失败，请手动复制";
  window.setTimeout(() => {
    toast.value = "";
  }, 1600);
}
async function onSelectChunkVersion(targetVersion: string): Promise<void> {
  await navigate({ version: targetVersion, mode: "chunks" });
}
async function onCopyChunkUrl(url: string, label = "链接"): Promise<void> {
  if (!url) return;
  toast.value = (await copyTextToClipboard(url)) ? `${label}已复制` : "复制失败，请手动复制";
  window.setTimeout(() => {
    toast.value = "";
  }, 1600);
}
function onRemoteTreeProbeTimeChange(value: string | null): void {
  remoteTreeProbeTime.value = value;
}
function candidateUrl(artifact: Artifact, sourceKind: string) {
  return artifact.urls.find((item) => item.source_kind === sourceKind);
}
function rawArtifactUrl(artifact: Artifact): string | undefined {
  return artifact.urls[0]?.url;
}
function isFileManifestArtifact(artifact: Artifact): boolean {
  return artifact.attributes?.delivery_mode === "file_manifest";
}
function manifestUrlFor(artifact: Artifact): string | undefined {
  const urls = artifact.attributes?.manifest_urls;
  return Array.isArray(urls) && typeof urls[0] === "string" ? urls[0] : (typeof artifact.attributes?.manifest_url === "string" ? artifact.attributes.manifest_url : undefined);
}
function baseUrlFor(artifact: Artifact): string | undefined {
  const urls = artifact.attributes?.base_urls;
  return Array.isArray(urls) && typeof urls[0] === "string" ? urls[0] : undefined;
}
async function copyManifestUrl(artifact: Artifact): Promise<void> {
  await copyUrl(manifestUrlFor(artifact));
}
async function copyBaseUrl(artifact: Artifact): Promise<void> {
  await copyUrl(baseUrlFor(artifact));
}
async function openArtifactFiles(): Promise<void> {
  await navigate({ mode: "files" });
}
function artifactIsAvailable(artifact: Artifact): boolean {
  const current = preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current;
  if (current?.state === "available") return true;
  if (preferredAvailableUrl(artifact) || actionableCandidate(artifact, "official")) return true;
  return false;
}
function artifactDownloadUrl(artifact: Artifact): string | undefined {
  if (!artifactIsAvailable(artifact)) return undefined;
  return preferredAvailableUrl(artifact)
    || actionableCandidate(artifact, "official")?.url
    || artifact.urls.find((u) => u.current?.state === "available")?.url
    || rawArtifactUrl(artifact);
}
function archiveAvailabilityLabel(artifact: Artifact): string {
  return artifactActionLabel(artifact);
}
function preferredAvailableUrl(artifact: Artifact, action: "open" | "copy" | "download" = "download"): string | undefined {
  return preferredDomainArtifactAction(domain.value, artifact, action)?.url;
}
function actionableCandidate(artifact: Artifact, sourceKind: string) {
  const candidate = candidateUrl(artifact, sourceKind);
  return domainActionSupport(domain.value, "open") &&
    candidate &&
    isAvailabilityActionable(candidate.current, candidate.url)
    ? candidate
    : undefined;
}
function patchRouteText(artifact: Artifact): string {
  const from = String(artifact.attributes.route_from || "");
  const to = String(artifact.attributes.route_to || "");
  return from && to ? `${from} -> ${to}` : String(artifact.attributes.route || "更新路线未知");
}
function packageLabel(artifact?: Artifact): string {
  if (selectedSummary.value?.provenance?.source_kind === "legacy_migration") return "历史归档资源清单";
  if (domain.value?.adapter === "arknights") return "官方完整分卷";
  if (domain.value?.adapter === "hoyo" && artifact) return hoyoArtifactCardPresentation(artifact, selectedVersion.value).label;
  if (domain.value?.adapter === "wuwa" || (artifact && isFileManifestArtifact(artifact))) return "官方资源清单";
  return "官方完整包";
}
function packageSource(): string {
  if (selectedSummary.value?.provenance?.source_kind === "legacy_migration") return "历史迁移/社区归档资源";
  if (selectedSummary.value?.provenance?.source_kind === "official_launcher") return "官方启动器索引";
  if (domain.value?.adapter === "arknights") return "Hypergryph launcher API";
  if (domain.value?.adapter === "hoyo") return "HoYo launcher API";
  return "official launcher API";
}
function availabilityText(artifact: Artifact): string {
  return artifactActionLabel(artifact);
}

function apkSourceSize(artifact: Artifact): number | null {
  const value = artifact.attributes.source_size;
  return typeof value === "number" && value > 0 ? value : null;
}
function apkSourceSizeText(artifact: Artifact): string {
  const value = apkSourceSize(artifact);
  return value === null ? "" : formatBytes(value);
}

function packageSubtitle(artifact: Artifact, index: number): string {
  if (domain.value?.adapter === "hoyo") {
    return hoyoArtifactCardPresentation(
      artifact,
      selectedVersion.value,
      index,
      gamePackageCount.value || artifacts.value.length,
    ).subtitle;
  }
  return `分卷 ${artifact.part || index + 1} / ${packageSource()} / ${availabilityText(artifact)}`;
}

function hoyoPatchLabel(artifact: Artifact): string {
  return hoyoArtifactCardPresentation(artifact, selectedVersion.value).label;
}
function hoyoPatchSubtitle(artifact: Artifact): string {
  return hoyoArtifactCardPresentation(artifact, selectedVersion.value).subtitle;
}
function patchRouteLabel(name: string): string {
  return name.replace("→", "->");
}
function patchBasePath(artifact: Artifact): string {
  const raw = artifact.urls[0]?.url;
  if (!raw) return "—";
  try {
    const path = decodeURIComponent(new URL(raw, window.location.origin).pathname).replace(/^\/+/, "");
    return path.replace(/indexFile\.json$/i, "resources/");
  } catch {
    return raw;
  }
}
function chunkManifestId(artifact: Artifact): string {
  const stored = artifact.attributes?.manifest_id;
  if (stored) return String(stored);
  const raw = artifact.urls[0]?.url;
  if (!raw) return "—";
  try {
    return decodeURIComponent(new URL(raw).pathname.split("/").filter(Boolean).at(-1) || "—");
  } catch {
    return artifact.name;
  }
}
function chunkMatchField(name: string): string {
  const value = name.toLowerCase();
  if (value.includes("中文") || value.includes("chinese")) return "zh-cn";
  if (value.includes("英文") || value.includes("english")) return "en-us";
  if (value.includes("日文") || value.includes("japanese")) return "ja-jp";
  if (value.includes("韩文") || value.includes("korean")) return "ko-kr";
  return "game";
}
function chunkMatchingField(artifact: Artifact): string {
  return String(artifact.attributes?.matching_field || chunkMatchField(artifact.name));
}
</script>

<template>
  <main v-if="registryError" class="not-found-view error-state">
    <p class="kicker">Registry Error</p>
    <h1>归档目录加载失败</h1>
    <p>{{ registryError.message }}</p>
    <button class="tool-button" type="button" @click="loadRegistry">重试</button>
  </main>
  <main v-else-if="scopedNotFound" class="not-found-view">
    <p class="kicker">Scoped Not Found</p>
    <h1>请求的归档范围不存在</h1>
    <p>{{ scopedNotFound }}</p>
    <button class="tool-button" type="button" @click="navigate({ gameId: games[0]?.id || '', domainId: '', version: '', mode: '' })">
      返回可用归档
    </button>
  </main>
  <main v-else-if="!loading && !games.length" class="not-found-view">
    <p class="kicker">Empty Registry</p>
    <h1>还没有游戏归档</h1>
    <p>registry 当前没有公开游戏。</p>
  </main>
  <main v-else-if="!loading && games.length && !domains.length" class="not-found-view">
    <p class="kicker">Empty Domains</p>
    <h1>这个游戏还没有归档域</h1>
    <p>稍后同步数据后再试。</p>
  </main>
  <main v-else-if="!loading && domains.length && !versions.length" class="not-found-view">
    <p class="kicker">Empty Versions</p>
    <h1>这个归档域还没有版本</h1>
    <p>当前没有可公开查询的版本。</p>
  </main>
  <div v-else class="archive-app">
    <aside class="game-sidebar" aria-label="游戏导航">
      <div class="sidebar-header">
        <div class="sidebar-brand">
          <div class="brand-badge">GMI</div>
          <div class="brand-info">
            <strong>游戏资源索引</strong>
            <span>Game Manifest Index</span>
          </div>
        </div>
        <div class="sidebar-search-box">
          <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            v-model="sidebarGameSearch"
            class="sidebar-search-input"
            placeholder="搜索游戏名称 / 代号…"
          />
          <span v-if="sidebarGameSearch" class="clear-search-btn" @click="sidebarGameSearch = ''">✕</span>
        </div>
      </div>

      <div class="sidebar-games-scroll">
        <div v-if="filteredRailGroups.length === 0" class="sidebar-empty">
          未找到匹配的游戏
        </div>
        <div v-for="group in filteredRailGroups" :key="group.publisher" class="publisher-group">
          <div class="publisher-header">
            <span>{{ group.publisher }}</span>
            <small class="publisher-count">{{ group.games.length }}</small>
          </div>
          <div class="publisher-game-list">
            <button
              v-for="item in group.games"
              :key="item.id"
              class="game-nav-item"
              :class="{ active: item.id === gameId }"
              type="button"
              @click="navigate({ gameId: item.id, domainId: '', version: '', mode: '' })"
            >
              <div class="game-item-icon-box">
                <img
                  v-if="iconFor(item.id)"
                  :class="{ 'endfield-icon': item.id === 'endfield' }"
                  :src="iconFor(item.id)"
                  :alt="item.name"
                  @error="useFallbackIcon($event, item.id)"
                />
                <span v-else>{{ shortName(item) }}</span>
              </div>
              <div class="game-item-text">
                <strong class="game-item-name">{{ item.name }}</strong>
                <span class="game-item-sub">{{ item.sub_name || item.id }}</span>
              </div>
            </button>
          </div>
        </div>
      </div>

      <div class="sidebar-footer">
        <a href="/admin" class="sidebar-admin-link">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          <span>管理后台</span>
        </a>
      </div>
    </aside>
    <main class="main-content">
      <header id="home" class="topbar">
        <div>
          <p class="kicker">Unofficial URL Archive</p>
          <h1>{{ displayGameName || '游戏' }}官方 CDN 文件索引</h1>
        </div>
        <button
          class="topbar-source-card"
          type="button"
          @click="openProvenanceModal($event)"
          title="查看全量游戏数据来源与官方直链申明"
        >
          <span class="source-card-dot"></span>
          <span class="source-card-val">数据与资源来源</span>
          <svg class="source-card-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
        </button>
      </header>
      <section class="control-strip">
        <VersionPicker
          :versions="versions"
          :model-value="selectedVersion"
          :domain="domain"
          :mode="mode"
          :label-override="mode === 'legacy' ? '候选线索' : undefined"
          :show-availability="mode !== 'files'"
          @select="navigate({ version: $event })"
        />
        <div class="mode-field">
          <div class="mode-tabs" role="tablist" aria-label="数据视图">
            <button
              v-for="item in visibleModes"
              :key="`${item.domain.id}:${item.capability}`"
              class="mode-tab"
              :class="{
                active: item.capability === 'compare'
                  ? mode === 'compare'
                  : (item.domain.id === domainId && item.capability === mode)
              }"
              @click="navigateMode(item.domain, item.capability)"
            >
              {{ modeLabel(item.domain, item.capability) }}
            </button>
          </div>
        </div>
        <label v-if="searchableMode" class="search-box">
          <span>搜索</span>
          <input v-model="query" placeholder="文件名 / MD5 / URL" />
        </label>
      </section>
      <section id="files" class="file-panel">
        <div class="panel-head">
          <div class="panel-header-top">
            <div class="panel-heading-block">
              <p class="kicker">{{ panelEyebrow }}</p>
              <div class="panel-title-row">
                <h2>{{ panelTitle }}</h2>
                <div v-if="versionMetaSummary.length" class="panel-meta-inline">
                  <span v-for="(item, idx) in versionMetaSummary" :key="item.label" class="meta-inline-item">
                    <span v-if="idx > 0" class="meta-dot">·</span>
                    <span class="meta-label">{{ item.label }}</span>
                    <span class="meta-value" :class="{ 'text-mono': item.isMono }">{{ item.value }}</span>
                  </span>
                </div>
              </div>
            </div>
            <div v-if="canExportArtifacts || currentVersionApiUrl || mode === 'compare' || mode === 'legacy' || isWuwaFilesMode" class="panel-tools">
              <!-- 鸣潮文件列表模式：统一收拢为 [ 原始索引 ▾ ] -->
              <div v-if="isWuwaFilesMode" class="raw-manifest-dropdown">
                <button
                  type="button"
                  class="tool-button raw-index-btn"
                  :class="{ active: rawIndexMenuOpen }"
                  @click.stop="toggleRawIndexMenu"
                >
                  <span>索引信息</span>
                  <svg class="raw-chevron-icon" :class="{ open: rawIndexMenuOpen }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>

                <div v-if="rawIndexMenuOpen" class="raw-index-card" @click.stop>
                  <div class="raw-index-card-header">
                    <strong>索引信息</strong>
                    <span class="raw-index-card-sub">官方 Manifest 索引源</span>
                  </div>

                  <!-- 清单 URL -->
                  <div class="raw-index-item">
                    <span class="raw-index-item-label">清单 URL</span>
                    <div class="raw-index-item-row">
                      <span class="raw-index-item-url" :title="wuwaManifestUrl || '暂无'">{{ wuwaManifestShort }}</span>
                      <button
                        type="button"
                        class="raw-index-item-btn"
                        :disabled="!wuwaManifestUrl"
                        @click="copyWuwaManifestUrl"
                      >
                        {{ copiedManifestUrl ? '已复制' : '复制' }}
                      </button>
                    </div>
                  </div>

                  <!-- 资源根目录 -->
                  <div class="raw-index-item">
                    <span class="raw-index-item-label">资源根目录</span>
                    <div class="raw-index-item-row">
                      <span class="raw-index-item-url" :title="wuwaBaseUrl || '暂无'">{{ wuwaBaseUrlShort }}</span>
                      <button
                        type="button"
                        class="raw-index-item-btn"
                        :disabled="!wuwaBaseUrl"
                        @click="copyWuwaBaseUrl"
                      >
                        {{ copiedBaseUrl ? '已复制' : '复制' }}
                      </button>
                    </div>
                  </div>

                  <div class="raw-index-divider"></div>

                  <!-- 查看原始 JSON -->
                  <a
                    v-if="wuwaManifestUrl"
                    class="raw-index-json-link"
                    :href="wuwaManifestUrl"
                    target="_blank"
                    rel="noreferrer"
                    @click="rawIndexMenuOpen = false"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                      <polyline points="15 3 21 3 21 9" />
                      <line x1="10" y1="14" x2="21" y2="3" />
                    </svg>
                    <span>查看原始 JSON</span>
                  </a>
                </div>
              </div>

              <!-- 其他常规模式下的 [查看 JSON] / [导出 URL] -->
              <template v-else>
                <a
                  v-if="currentVersionApiUrl && mode !== 'compare' && mode !== 'legacy'"
                  class="tool-button"
                  :href="currentVersionApiUrl"
                  target="_blank"
                  rel="noreferrer"
                >
                  查看 JSON
                </a>
                <a
                  v-else-if="mode === 'legacy'"
                  class="tool-button"
                  :href="apiUrl(`/domains/${encodeURIComponent(domainId)}/leads`)"
                  target="_blank"
                  rel="noreferrer"
                >
                  查看 JSON
                </a>
                <button
                  v-else-if="mode !== 'compare'"
                  class="tool-button"
                  @click="exportArtifacts('json')"
                >
                  查看 JSON
                </button>
                <button
                  v-if="canExportArtifacts"
                  class="tool-button"
                  :disabled="!canExportUrls"
                  @click="exportArtifacts('urls')"
                >
                  {{ exportUrlsLabel }}
                </button>
              </template>
            </div>
          </div>

          <!-- 第二层：两组明确的筛选器 (文件类型 & 可用状态 / 组件清单) -->
          <div v-if="(mode === 'chunks' && chunkFilterOptions.length > 1) || categoryFilters.length > 1 || canFilterAvailability" class="panel-filters-row">
            <!-- 模式为 chunks 时的组件清单筛选 -->
            <div v-if="mode === 'chunks' && chunkFilterOptions.length > 1" class="filter-group category-toolbar" aria-label="组件清单筛选">
              <span class="filter-group-label">组件清单</span>
              <div class="filter-group-chips">
                <button
                  v-for="opt in chunkFilterOptions"
                  :key="opt.key"
                  type="button"
                  class="filter-chip"
                  :class="{ active: chunkCategoryFilter === opt.key }"
                  @click="chunkCategoryFilter = opt.key"
                >
                  {{ opt.label }} <b>{{ opt.count.toLocaleString() }}</b>
                </button>
              </div>
            </div>

            <!-- 模式为普通文件时的文件类型筛选 -->
            <div v-else-if="categoryFilters.length > 1" class="filter-group category-toolbar" aria-label="文件类型筛选">
              <span class="filter-group-label">文件类型</span>
              <div class="filter-group-chips">
                <button
                  v-for="item in categoryFilters"
                  :key="item.id"
                  type="button"
                  class="filter-chip"
                  :class="{ active: selectedCategory === item.id }"
                  @click="selectedCategory = item.id"
                >
                  {{ item.label }} <b>{{ item.count.toLocaleString() }}</b>
                </button>
              </div>
            </div>

            <!-- 细分割线 -->
            <div v-if="categoryFilters.length > 1 && canFilterAvailability" class="filter-group-divider" aria-hidden="true"></div>

            <!-- 组 2: 可用状态 -->
            <div v-if="canFilterAvailability" class="filter-group availability-toolbar" aria-label="可用状态筛选">
              <span class="filter-group-label">可用状态</span>
              <div class="filter-group-chips">
                <button
                  v-for="item in displayedAvailabilityFilters"
                  :key="item.id"
                  type="button"
                  class="filter-chip"
                  :class="{ active: availabilityFilter === item.id }"
                  @click="availabilityFilter = item.id"
                >
                  {{ item.label }} <b>{{ item.count.toLocaleString() }}</b>
                </button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="loading" class="empty">
          正在读取归档 API…
        </div>
        <div v-else-if="error" class="empty error-state">
          <strong>内容加载失败</strong>
          <span>{{ error.message }}</span>
          <button class="tool-button" type="button" @click="loadArtifacts(false)">重试</button>
        </div>
        <div v-else-if="mode === 'legacy' && legacyLeads.length" class="file-list legacy-candidate-list">
          <article v-for="lead in legacyLeads" :key="lead.id" class="file-card legacy-candidate-card">
            <div class="file-icon">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="m4 7 8-4 8 4-8 4-8-4Z" />
                <path d="m4 7 8 4 8-4v10l-8 4-8-4V7Z" />
                <path d="M12 11v10" />
              </svg>
            </div>
            <div class="file-main">
              <div class="file-title">
                <span class="pill">{{ leadClassificationLabel(lead) }}</span>
                <span class="count">{{ formatDate(lead.generated_at || undefined) }}</span>
                <strong>{{ lead.filename }}</strong>
              </div>
              <div class="file-meta">
                <span>归档证据 HTTP {{ lead.urls[0]?.current_facts.status_code ?? '未知' }} / {{ lead.urls[0]?.current_facts.reason ?? '无判定' }}</span>
                <span v-if="lead.urls[0]?.archive_facts.classification_reason">{{ lead.urls[0].archive_facts.classification_reason }}</span>
                <span v-if="lead.urls[0]?.archive_facts.digest"># {{ lead.urls[0].archive_facts.digest }}</span>
              </div>
              <div class="file-path">{{ lead.urls[0]?.url }}</div>
            </div>
            <div v-if="leadActionAllowed(lead, 'copy') || leadActionAllowed(lead, 'open')" class="file-actions">
              <button v-if="leadActionAllowed(lead, 'copy')" class="icon-button" @click="copyUrl(lead.urls[0]?.url)">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="9" y="9" width="11" height="11" rx="2" />
                  <path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" />
                </svg>
                复制链接
              </button>
              <a
                v-if="leadActionAllowed(lead, 'open') && lead.urls[0]?.url"
                class="icon-button"
                :href="lead.urls[0].url"
                target="_blank"
                rel="noreferrer"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 3v12" />
                  <path d="m7 10 5 5 5-5" />
                  <path d="M5 21h14" />
                </svg>
                下载
              </a>
              <a
                v-if="leadActionAllowed(lead, 'open') && legacyArchiveUrl(lead)"
                class="icon-button mirror-link"
                :href="legacyArchiveUrl(lead)"
                target="_blank"
                rel="noreferrer"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M14 5h5v5" />
                  <path d="m10 14 9-9" />
                  <path d="M19 13v6H5V5h6" />
                </svg>
                CDX 快照
              </a>
            </div>
          </article>
        </div>
        <div v-else-if="mode === 'legacy'" class="empty">没有候选线索记录。</div>
        <div v-else-if="mode === 'compare'" class="compare-shell">
          <div class="compare-toolbar">
            <div v-if="compareDomains.length > 1" class="compare-platform-field">
              <span>对比平台</span>
              <div class="compare-platform-tabs" role="tablist" aria-label="对比平台选择">
                <button
                  v-for="item in compareDomains"
                  :key="item.id"
                  type="button"
                  class="compare-platform-tab"
                  :class="{ active: item.id === domainId }"
                  @click="switchCompareDomain(item)"
                >
                  {{ comparePlatformLabel(item) }}
                </button>
              </div>
            </div>
            <div v-if="compareBaseVersion" class="compare-range-field">
              <span>对比范围</span>
              <strong>{{ compareBaseVersion }} → {{ selectedVersion }}</strong>
            </div>
            <div v-if="compareBaseVersion" class="compare-base-field">
              <span>基准版本</span>
              <CustomSelect
                :model-value="compareBaseVersion"
                :options="compareBaseOptions.map((item) => ({ label: item.version, value: item.version }))"
                size="small"
                @change="updateCompareBase(String($event))"
              />
            </div>
            <p>{{ compareScope === 'files' ? '差异由服务端按文件路径、大小和 MD5 计算并分页返回。' : '差异由服务端按稳定 artifact identity 计算并分页返回；对比响应不包含 URL 或 availability。' }}</p>
          </div>
          <ComparePanel
            v-if="compareBaseVersion"
            :domain-id="domainId"
            :from-version="compareBaseVersion"
            :to-version="selectedVersion"
            :compare-scope="compareScope"
          />
          <div v-else class="empty">当前版本没有可用的对比基准。</div>
        </div>
        <div v-else-if="mode === 'manifest' && artifacts.length" class="manifest-table">
          <div class="manifest-head">
            <span>路径</span>
            <span>大小</span>
            <span>校验值</span>
          </div>
          <div v-for="artifact in artifacts" :key="artifact.id" class="manifest-row">
            <strong>{{ artifact.name }}</strong>
            <span>{{ formatBytes(artifact.size) }}</span>
            <code>{{ artifact.checksum_value || '—' }}</code>
          </div>
          <button v-if="nextCursor" class="load-more" :disabled="loadingMore" @click="loadArtifacts(true)">
            {{ loadingMore ? '读取中…' : '加载下一页' }}
          </button>
        </div>
        <div v-else-if="mode === 'manifest'" class="empty">当前版本没有官方清单记录。</div>
        <div v-else-if="mode === 'chunks'" class="chunk-manifest-wrapper">
          <ChunkManifestView
            :domain="domain"
            :game="game"
            :version="selectedVersion"
            :chunk-detail="chunkDetail"
            :chunk-collection="chunkCollection"
            :artifacts="artifacts"
            :category-filter="chunkCategoryFilter"
            :loading="loading || chunkLoading"
            :error="chunkError"
            @select-version="onSelectChunkVersion"
            @copy-url="onCopyChunkUrl"
          />
        </div>
        <div v-else-if="mode === 'files' && domain?.adapter === 'hoyo'" class="chunk-file-browser-wrapper">
          <ChunkFileBrowser
            :domain="domain"
            :game="game"
            :version="selectedVersion"
            :domain-id="domainId"
            :chunk-detail="chunkDetail"
            :version-summary="selectedSummary"
            :chunk-collection="chunkCollection"
            :search-query="query"
          />
        </div>
        <template v-if="!loading && !error && !['legacy', 'archive', 'compare', 'manifest', 'chunks'].includes(mode) && !(mode === 'files' && domain?.adapter === 'hoyo')">
          <div v-if="usesRemoteTree && domain" class="remote-workspace">
            <template v-if="mode === 'resources' && selectedSummary">
              <div class="chunk-summary resource-summary">
                <div>
                  <span>资源版本</span>
                  <strong>{{ selectedSummary.attributes.resource_version || selectedVersion }}</strong>
                </div>
                <div>
                  <span>文件数</span>
                  <strong>{{ selectedSummary.artifact_kinds.resource?.count.toLocaleString() || '0' }}</strong>
                </div>
                <div>
                  <span>总大小</span>
                  <strong>{{ formatBytes(selectedSummary.artifact_kinds.resource?.size || 0) }}</strong>
                </div>
                <div>
                  <span>{{ gameId === 'endfield' ? '平台' : 'Unity' }}</span>
                  <strong>{{ gameId === 'endfield' ? 'Windows' : selectedSummary.attributes.unity_version || '2022.3.62f3' }}</strong>
                </div>
              </div>
            </template>
            <RemoteArtifactTree
              :domain-id="domain.id"
              :version="selectedVersion"
              :kind="mode === 'resources' ? 'resource' : 'file'"
              :availability-state="availabilityStateForRequest"
              :allow-actions="supportsDomainAction('open')"
              @probe-time-change="onRemoteTreeProbeTimeChange"
            />
          </div>
          <div v-else-if="!displayedArtifacts.length" class="empty">
            {{ domain?.adapter === 'hoyo' && mode === 'packages' ? '该分类下没有压缩包直链' : '没有符合当前条件的归档记录。' }}
          </div>
          <ArtifactTree v-else-if="usesArtifactTree" :artifacts="artifacts" />
          <div v-else-if="mode === 'files'" class="remote-workspace fragment-file-list">
            <div class="tree-table-wrapper">
              <div class="tree-grid-header">
                <div class="col-name">名称</div>
                <div class="col-hash">校验值</div>
                <div class="col-size">大小</div>
                <div class="col-action">操作</div>
              </div>
              <div class="tree-grid-body">
                <FragmentFileRow v-for="artifact in artifacts" :key="artifact.id" :artifact="artifact" />
              </div>
            </div>
            <div v-if="nextCursor" class="tree-load-more">
              <button class="tree-load-btn" :disabled="loadingMore" type="button" @click="loadArtifacts(true)">
                <span v-if="loadingMore" class="tree-btn-spinner"></span>
                <span>{{ loadingMore ? '读取中…' : '加载下一页' }}</span>
              </button>
            </div>
          </div>
          <div v-else-if="mode === 'apk'" class="file-list">
            <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card">
              <div class="file-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21 8-9-5-9 5 9 5 9-5Z" />
                  <path d="M3 8v8l9 5 9-5V8" />
                  <path d="M12 13v8" />
                </svg>
              </div>
              <div class="file-main">
                <div class="file-title">
                  <span class="pill">官方安装包</span>
                  <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
                  <strong>{{ artifact.name }}</strong>
                </div>
                <div class="file-meta">
                  <span>{{ formatBytes(artifact.size || apkSourceSize(artifact) || 0) }}</span>
                  <span v-if="artifact.checksum_value">{{ (artifact.checksum_type || 'CRC64').toUpperCase() }}: {{ artifact.checksum_value }}</span>
                  <span v-if="artifact.attributes.artifact_variant">渠道 {{ artifact.attributes.artifact_variant }}</span>
                </div>
              </div>
               <div class="file-actions">
                  <button v-if="false" class="icon-button" type="button" @click="openArtifactFiles">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v14H4z" /><path d="M8 9h8M8 13h5" /></svg>
                    <span>查看清单</span>
                  </button>
                  <button v-if="false" class="icon-button" type="button" @click="copyManifestUrl(artifact)">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                    <span>复制清单链接</span>
                  </button>
                  <button v-if="false" class="icon-button" type="button" @click="copyBaseUrl(artifact)">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                    <span>复制资源文件根目录</span>
                  </button>
                  <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
                  <button
                  v-if="preferredAvailableUrl(artifact, 'copy')"
                  class="icon-button"
                  @click="copyArtifactUrl(artifact)"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <button
                  v-else-if="rawArtifactUrl(artifact)"
                  class="icon-button"
                  @click="copyUrl(rawArtifactUrl(artifact))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <a
                  v-if="preferredAvailableUrl(artifact)"
                  class="icon-button"
                  :href="preferredAvailableUrl(artifact)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <a
                  v-else-if="artifactDownloadUrl(artifact)"
                  class="icon-button"
                  :href="artifactDownloadUrl(artifact)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <button
                  v-else
                  class="icon-button is-disabled is-locked"
                  disabled
                  type="button"
                  title="链接已失效，不可直接下载"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>下载</span>
                </button>
                <a
                  v-if="actionableCandidate(artifact, 'archive')"
                  class="icon-button mirror-link"
                  :href="actionableCandidate(artifact, 'archive')?.url"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>归档路径</span>
                </a>
              </div>
            </article>
          </div>
          <div v-else-if="mode === 'packages' && usesPreferredUrlPresentation && domain?.adapter !== 'wuwa'" class="file-list package-list endfield-list">
            <article v-for="(artifact, index) in artifacts" :key="artifact.id" class="file-card package-card">
              <div class="file-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21 8-9-5-9 5 9 5 9-5Z" />
                  <path d="M3 8v8l9 5 9-5V8" />
                  <path d="M12 13v8" />
                </svg>
              </div>
              <div class="file-main">
                <div class="file-title">
                  <span class="pill">{{ candidateUrl(artifact, 'mirror') ? '完整分卷' : '官方完整分卷' }}</span>
                  <span class="count">{{ artifact.part || index + 1 }}/{{ selectedSummary?.artifact_kinds?.package?.count || artifacts.length }}</span>
                  <strong>{{ artifact.name }}</strong>
                </div>
                <div class="file-meta">
                  <span v-if="supportsArtifactField('size')">{{ formatBytes(artifact.size) }}</span>
                  <span v-if="supportsArtifactField('checksum') && artifact.checksum_value"># {{ artifact.checksum_value }}</span>
                </div>
              </div>
              <div class="file-actions endfield-actions">
                <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
                <button
                  v-if="preferredAvailableUrl(artifact, 'copy')"
                  class="icon-button"
                  @click="copyUrl(preferredAvailableUrl(artifact, 'copy'))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <a
                  v-if="actionableCandidate(artifact, 'official')"
                  class="icon-button"
                  :href="actionableCandidate(artifact, 'official')?.url"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <a
                  v-if="actionableCandidate(artifact, 'mirror')"
                  class="icon-button mirror-link"
                  :href="actionableCandidate(artifact, 'mirror')?.url"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>镜像</span>
                </a>
                <button
                  v-if="!preferredAvailableUrl(artifact) && !actionableCandidate(artifact, 'official') && !actionableCandidate(artifact, 'mirror')"
                  class="icon-button is-disabled is-locked"
                  disabled
                  type="button"
                  title="链接已失效，不可直接下载"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>下载</span>
                </button>
                <button
                  v-if="!preferredAvailableUrl(artifact) && rawArtifactUrl(artifact)"
                  class="icon-button"
                  @click="copyUrl(rawArtifactUrl(artifact))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
              </div>
            </article>
            <button v-if="nextCursor" class="load-more" :disabled="loadingMore" @click="loadArtifacts(true)">
              {{ loadingMore ? '读取中…' : '加载下一页' }}
            </button>
          </div>
          <div v-else-if="mode === 'packages'" class="file-list package-list">
            <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card package-card">
              <div class="file-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21 8-9-5-9 5 9 5 9-5Z" />
                  <path d="M3 8v8l9 5 9-5V8" />
                  <path d="M12 13v8" />
                </svg>
              </div>
              <div class="file-main">
                <div class="file-title">
                  <span class="pill">{{ packageLabel(artifact) }}</span>
                  <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
                  <strong>{{ artifact.name }}</strong>
                </div>
                <div class="file-meta">
                  <span>{{ formatBytes(artifact.size) }}</span>
                  <span v-if="artifact.checksum_value">{{ formatChecksum(artifact) }}</span>
                  <span v-if="artifact.attributes?.language">{{ hoyoLanguageLabel(artifact.attributes.language) }}</span>
                </div>
              </div>
              <div class="file-actions">
                <template v-if="domain?.adapter === 'wuwa' && isFileManifestArtifact(artifact)">
                  <button class="icon-button" type="button" @click="openArtifactFiles"><span>查看清单</span></button>
                  <button v-if="manifestUrlFor(artifact)" class="icon-button" type="button" @click="copyManifestUrl(artifact)"><span>复制清单链接</span></button>
                  <button v-if="baseUrlFor(artifact)" class="icon-button" type="button" @click="copyBaseUrl(artifact)"><span>复制资源文件根目录</span></button>
                </template>
                <template v-else>
                <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
                <button
                  v-if="preferredAvailableUrl(artifact, 'copy')"
                  class="icon-button"
                  @click="copyArtifactUrl(artifact)"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <button
                  v-else-if="rawArtifactUrl(artifact)"
                  class="icon-button"
                  @click="copyUrl(rawArtifactUrl(artifact))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <a
                  v-if="preferredAvailableUrl(artifact)"
                  class="icon-button"
                  :href="preferredAvailableUrl(artifact)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <button
                  v-else
                  class="icon-button is-disabled is-locked"
                  disabled
                  type="button"
                  title="链接已失效，不可直接下载"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>下载</span>
                </button>
                </template>
              </div>
            </article>
            <button v-if="nextCursor" class="load-more" :disabled="loadingMore" @click="loadArtifacts(true)">
              {{ loadingMore ? '读取中…' : '加载下一页' }}
            </button>
          </div>
          <div v-else-if="mode === 'patches' && usesPreferredUrlPresentation && domain?.adapter !== 'wuwa'" class="file-list patch-route-list endfield-list">
            <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card patch-route-card">
              <div class="file-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21 8-9-5-9 5 9 5 9-5Z" />
                  <path d="M3 8v8l9 5 9-5V8" />
                  <path d="M12 13v8" />
                </svg>
              </div>
              <div class="file-main">
                <div class="file-title">
                  <span class="pill">更新分卷</span>
                  <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
                  <strong>{{ artifact.name }}</strong>
                </div>
                <div class="file-meta">
                  <span v-if="supportsArtifactField('size')">{{ formatBytes(artifact.size) }}</span>
                  <span v-if="supportsArtifactField('checksum') && artifact.checksum_value"># {{ artifact.checksum_value }}</span>
                  <span v-if="patchRouteText(artifact)">{{ patchRouteText(artifact) }}</span>
                </div>
              </div>
              <div class="file-actions endfield-actions">
                <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
                <button
                  v-if="preferredAvailableUrl(artifact, 'copy')"
                  class="icon-button"
                  @click="copyUrl(preferredAvailableUrl(artifact, 'copy'))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <button
                  v-else-if="rawArtifactUrl(artifact)"
                  class="icon-button"
                  @click="copyUrl(rawArtifactUrl(artifact))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <a
                  v-if="actionableCandidate(artifact, 'official')"
                  class="icon-button"
                  :href="actionableCandidate(artifact, 'official')?.url"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <a
                  v-if="actionableCandidate(artifact, 'mirror')"
                  class="icon-button mirror-link"
                  :href="actionableCandidate(artifact, 'mirror')?.url"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>镜像</span>
                </a>
                <button
                  v-if="!preferredAvailableUrl(artifact) && !actionableCandidate(artifact, 'official') && !actionableCandidate(artifact, 'mirror')"
                  class="icon-button is-disabled is-locked"
                  disabled
                  type="button"
                  title="链接已失效，不可直接下载"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>下载</span>
                </button>
              </div>
            </article>
            <button v-if="nextCursor" class="load-more" :disabled="loadingMore" @click="loadArtifacts(true)">
              {{ loadingMore ? '读取中…' : '加载下一页' }}
            </button>
          </div>
          <div v-else-if="mode === 'patches' && domain?.adapter === 'wuwa'" class="file-list patch-route-list">
            <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card patch-route-card">
              <div class="file-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21 8-9-5-9 5 9 5 9-5Z" />
                  <path d="M3 8v8l9 5 9-5V8" />
                  <path d="M12 13v8" />
                </svg>
              </div>
              <div class="file-main">
                <div class="file-title">
                  <span class="pill">更新路线</span>
                  <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
                  <strong>{{ patchRouteLabel(artifact.name) }}</strong>
                </div>
                <div class="file-meta">
                  <span>{{ formatBytes(artifact.size) }}</span>
                  <span># {{ artifact.checksum_value || '—' }}</span>
                  <span v-if="patchBasePath(artifact)">{{ patchBasePath(artifact) }}</span>
                </div>
              </div>
              <div class="file-actions">
                <template v-if="isFileManifestArtifact(artifact)">
                  <button class="icon-button" type="button" @click="openArtifactFiles"><span>查看清单</span></button>
                  <button v-if="manifestUrlFor(artifact)" class="icon-button" type="button" @click="copyManifestUrl(artifact)"><span>复制清单链接</span></button>
                  <button v-if="baseUrlFor(artifact)" class="icon-button" type="button" @click="copyBaseUrl(artifact)"><span>复制资源文件根目录</span></button>
                </template>
                <template v-else>
                <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
                <button
                  v-if="preferredAvailableUrl(artifact, 'copy')"
                  class="icon-button"
                  @click="copyArtifactUrl(artifact)"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <button
                  v-else-if="rawArtifactUrl(artifact)"
                  class="icon-button"
                  @click="copyUrl(rawArtifactUrl(artifact))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <a
                  v-if="preferredAvailableUrl(artifact)"
                  class="icon-button"
                  :href="preferredAvailableUrl(artifact)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <button
                  v-else
                  class="icon-button is-disabled is-locked"
                  disabled
                  type="button"
                  title="链接已失效，不可直接下载"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>下载</span>
                </button>
                </template>
              </div>
            </article>
            <button v-if="nextCursor" class="load-more" :disabled="loadingMore" @click="loadArtifacts(true)">
              {{ loadingMore ? '读取中…' : '加载下一页' }}
            </button>
          </div>
          <div v-else-if="mode === 'patches' && domain?.adapter === 'hoyo'" class="file-list patch-route-list">
            <article v-for="(artifact, index) in displayedArtifacts" :key="artifact.id" class="file-card package-card">
              <div class="file-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21 8-9-5-9 5 9 5 9-5Z" />
                  <path d="M3 8v8l9 5 9-5V8" />
                  <path d="M12 13v8" />
                </svg>
              </div>
              <div class="file-main">
                <div class="file-title">
                  <span class="pill">{{ hoyoPatchLabel(artifact) }}</span>
                  <span class="count">{{ index + 1 }}/{{ displayedArtifacts.length }}</span>
                  <strong>{{ artifact.name }}</strong>
                </div>
                <div class="file-meta">
                  <span>{{ formatBytes(artifact.size) }}</span>
                  <span v-if="artifact.checksum_value">{{ formatChecksum(artifact) }}</span>
                  <span v-if="artifact.attributes.route_from && (artifact.attributes.route_to || selectedVersion)">{{ artifact.attributes.route_from }} -> {{ artifact.attributes.route_to || selectedVersion }}</span>
                  <span v-if="artifact.attributes.language">{{ hoyoLanguageLabel(artifact.attributes.language) }}</span>
                </div>
              </div>
              <div class="file-actions">
                <AvailabilityBadge :value="preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current || null" />
                <button
                  v-if="preferredAvailableUrl(artifact, 'copy')"
                  class="icon-button"
                  @click="copyArtifactUrl(artifact)"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <button
                  v-else-if="rawArtifactUrl(artifact)"
                  class="icon-button"
                  @click="copyUrl(rawArtifactUrl(artifact))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>复制链接</span>
                </button>
                <a
                  v-if="preferredAvailableUrl(artifact)"
                  class="icon-button"
                  :href="preferredAvailableUrl(artifact)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <button
                  v-else
                  class="icon-button is-disabled is-locked"
                  disabled
                  type="button"
                  title="链接已失效，不可直接下载"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>下载</span>
                </button>
              </div>
            </article>
            <button v-if="nextCursor" class="load-more" :disabled="loadingMore" @click="loadArtifacts(true)">
              {{ loadingMore ? '读取中…' : '加载下一页' }}
            </button>
          </div>
          <div v-else class="file-list">
            <article v-for="artifact in displayedArtifacts" :key="artifact.id" class="file-card">
              <span class="file-icon">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m21 8-9-5-9 5 9 5 9-5Z" />
                  <path d="M3 8v8l9 5 9-5V8" />
                  <path d="M12 13v8" />
                </svg>
              </span>
              <div class="file-body">
                <div class="file-title">
                  <strong>{{ artifact.name }}</strong>
                  <span class="pill">{{ artifact.attributes?.delivery_mode === 'file_manifest' ? (artifact.kind === 'patch' ? '更新资源清单' : '官方资源清单') : artifact.kind }}</span>
                </div>
                <div class="file-meta">
                  <span>{{ formatBytes(artifact.size) }}</span>
                  <span v-if="artifact.checksum_value">{{ artifact.checksum_type }} {{ artifact.checksum_value }}</span>
                  <span>{{ artifact.urls.length }} 个 URL</span>
                </div>
                <div class="file-path">{{ artifact.urls[0]?.url }}</div>
              </div>
              <div class="file-actions">
                <button
                  v-if="preferredAvailableUrl(artifact, 'copy')"
                  class="icon-button"
                  @click="copyArtifactUrl(artifact)"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>{{ artifact.attributes?.delivery_mode === 'file_manifest' ? '复制清单链接' : '复制链接' }}</span>
                </button>
                <button
                  v-else-if="rawArtifactUrl(artifact)"
                  class="icon-button"
                  @click="copyUrl(rawArtifactUrl(artifact))"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  <span>{{ artifact.attributes?.delivery_mode === 'file_manifest' ? '复制清单链接' : '复制链接' }}</span>
                </button>
                <a
                  v-if="preferredAvailableUrl(artifact)"
                  class="icon-button"
                  :href="preferredAvailableUrl(artifact)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <a
                  v-else-if="rawArtifactUrl(artifact)"
                  class="icon-button"
                  :href="rawArtifactUrl(artifact)"
                  target="_blank"
                  rel="noreferrer"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                  </svg>
                  <span>下载</span>
                </a>
                <button
                  v-else
                  class="icon-button is-disabled is-locked"
                  disabled
                  type="button"
                  title="链接已失效，不可直接下载"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>下载</span>
                </button>
              </div>
            </article>
            <button v-if="nextCursor" class="load-more" :disabled="loadingMore" @click="loadArtifacts(true)">
              {{ loadingMore ? '读取中…' : '加载下一页' }}
            </button>
          </div>
        </template>
      </section>
      <footer class="archive-footer">
        <div v-if="syncTimeText" class="footer-sync-info">
          <span>当前资源最近探活于 <b>{{ syncTimeText }}</b></span>
        </div>
        <div class="footer-notice">
          <button type="button" class="footer-provenance-link" @click="openProvenanceModal($event)">
            官方下载索引与数据溯源
          </button>
          <span class="dot">·</span>
          <span>不托管任何游戏文件</span>
          <span class="dot">·</span>
          <span>Game Manifest Index</span>
        </div>
      </footer>
      <div v-if="toast" class="toast" role="status">{{ toast }}</div>
    </main>

    <!-- 全量游戏数据与资源溯源说明弹窗 -->
    <SourceProvenanceModal
      :open="showProvenanceModal"
      :origin-pos="provenanceOrigin"
      :active-game-id="gameId"
      @close="showProvenanceModal = false"
    />
  </div>
</template>
