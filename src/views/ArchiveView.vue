<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, apiUrl, isAbortError } from "../api";
import {
  baseUrlFor,
  formatDate,
  formatObservedDate,
  formatRelativeTime,
  iconForGame,
  isFileManifestArtifact,
  manifestUrlFor,
  observedDate,
  preferredAvailableUrl,
  rawArtifactUrl,
} from "../archive-artifact-helpers";
import { copyTextToClipboard } from "../clipboard";
import ArchiveApkList from "../components/archive/ArchiveApkList.vue";
import ArchiveCompareView from "../components/archive/ArchiveCompareView.vue";
import ArchiveControlStrip from "../components/archive/ArchiveControlStrip.vue";
import ArchiveGameSidebar from "../components/archive/ArchiveGameSidebar.vue";
import ArchivePackageList from "../components/archive/ArchivePackageList.vue";
import ArchivePatchList from "../components/archive/ArchivePatchList.vue";
import ArchiveWuwaRawIndexMenu from "../components/archive/ArchiveWuwaRawIndexMenu.vue";
import ArtifactPagination from "../components/ArtifactPagination.vue";
import ArtifactTree from "../components/ArtifactTree.vue";
import ChunkFileBrowser from "../components/ChunkFileBrowser.vue";
import ChunkManifestView from "../components/ChunkManifestView.vue";
import FragmentFileRow, { activeFileMenuId } from "../components/FragmentFileRow.vue";
import ProbeScheduleInfo from "../components/ProbeScheduleInfo.vue";
import RemoteArtifactTree from "../components/RemoteArtifactTree.vue";
import SiteChangelogModal from "../components/SiteChangelogModal.vue";
import SourceProvenanceModal from "../components/SourceProvenanceModal.vue";
import { useArchiveArtifactsLoader, type ArchiveArtifactLoadContext, type ArchiveArtifactsLoaderState } from "../composables/useArchiveArtifactsLoader";
import { useArchiveCompare } from "../composables/useArchiveCompare";
import { useArchiveExport } from "../composables/useArchiveExport";
import { domainRouteLabel, resolveRouteDomain, useArchiveLoader } from "../composables/useArchiveLoader";
import {
  artifactKindForMode,
  availabilityStatesForMode,
  availableArchiveModes,
  domainActionSupport,
  domainFieldSupport,
  domainModeLabel,
  formatBytes,
  hoyoArtifactCardPresentation,
  hoyoLanguageLabel,
  isChunkOnlyVersion,
  latestLiveProbeTime,
  displayVersionLabel,
  routeVersionLabel,
  versionSupportsMode,
} from "../domain-presentation";
import {
  gameActivityPlatform,
  gameActivityTime,
  gameActivityTitle,
  latestReleaseActivity,
} from "../game-activity";
import type {
  ArchiveDomain,
  ArchiveLead,
  Artifact,
  FileTimeChange,
  GameActivityEvent,
} from "../types";

const route = useRoute();
const router = useRouter();
const showProvenanceModal = ref(false);
const provenanceOrigin = ref<{ x: number; y: number } | null>(null);
const showSiteChangelog = ref(false);
const siteChangelogOrigin = ref<{ x: number; y: number } | null>(null);
const siteChangelogInitialTab = ref<"system" | "data">("system");
const gameActivity = ref<GameActivityEvent[]>([]);
let gameActivityController: AbortController | null = null;

function openSiteChangelog(event: MouseEvent, tab: "system" | "data" = "system"): void {
  const button = event.currentTarget as HTMLButtonElement;
  const rect = button.getBoundingClientRect();
  button.focus();
  siteChangelogOrigin.value = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  siteChangelogInitialTab.value = tab;
  showSiteChangelog.value = true;
}

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

const remoteTreeProbeTime = ref<string | null>(null);
const remoteManifestSize = ref<{ domainId: string; version: string; kind: string; size: number | null } | null>(null);
const browserFileTime = ref<FileTimeChange | null>(null);
let manifestSizeController: AbortController | null = null;
let manifestSizeGeneration = 0;
const globalProbeTime = ref<string | null>(null);
const probeTimeClock = ref(Date.now());
const globalProbeLoaded = ref(false);
let globalProbeController: AbortController | null = null;
const leads = ref<ArchiveLead[]>([]);
const query = ref(String(route.query.q || ""));
const initialAvailability = String(route.query.availability || "all");
const availabilityFilter = ref<"all" | "available" | "unavailable" | "unknown">(
  ["available", "unavailable", "unknown"].includes(initialAvailability)
    ? (initialAvailability as "available" | "unavailable" | "unknown")
    : "all",
);
const toast = ref("");
let toastTimer: number | null = null;
const selectedCategory = ref<string>("all");
const chunkCategoryFilter = ref<string>("all");
const artifactPage = ref(1);
const artifactPageSize = ref(50);
const SEARCHABLE_MODES = new Set(["apk", "chunks", "files", "packages", "patches"]);

function setToast(message: string, durationMs = 1600): void {
  if (toastTimer !== null) window.clearTimeout(toastTimer);
  toast.value = message;
  toastTimer = window.setTimeout(() => {
    toast.value = "";
    toastTimer = null;
  }, durationMs);
}

let archiveArtifactsLoader: ArchiveArtifactsLoaderState | null = null;
function loadArtifacts(append: boolean): Promise<void> {
  return archiveArtifactsLoader?.loadArtifacts(append) || Promise.resolve();
}
function invalidateArtifactLoad(): void {
  archiveArtifactsLoader?.invalidate();
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
async function loadGameActivity(): Promise<void> {
  gameActivityController?.abort();
  gameActivity.value = [];
  if (!gameId.value || gameId.value === "abc") return;
  const controller = new AbortController();
  gameActivityController = controller;
  try {
    const response = await api.gameActivity(gameId.value, controller.signal);
    if (!controller.signal.aborted) gameActivity.value = response.items;
  } catch (error) {
    if (!controller.signal.aborted && !isAbortError(error)) gameActivity.value = [];
  }
}

watch(gameId, () => void loadGameActivity(), { immediate: true });
watch(showSiteChangelog, (open) => {
  if (open) void loadGameActivity();
});
const recentActivity = computed(() => latestReleaseActivity(gameActivity.value));
const domainId = computed(() => {
  const requested = String(route.params.domainId || "");
  const matched = resolveRouteDomain(gameId.value, requested, domains.value);
  return matched?.id || requested || domains.value[0]?.id || "";
});
const selectedVersion = computed(() => {
  const requested = String(route.params.version || "");
  const matched = versions.value.find(
    (item) => item.version === requested || routeVersionLabel(item.version) === requested,
  );
  return matched?.version || requested || versions.value[0]?.version || "";
});
const mode = computed(() =>
  String(route.params.mode || domains.value.find((item) => item.id === domainId.value)?.capabilities[0] || ""),
);
const game = computed(() => games.value.find((item) => item.id === gameId.value) || null);
const gameNames = computed(() => Object.fromEntries(games.value.map((item) => [
  item.id,
  /[\u3400-\u9fff]/.test(item.name) ? item.name : item.sub_name || item.name,
])));
const domain = computed(() => domains.value.find((item) => item.id === domainId.value) || null);
const uiModes = computed(() => availableArchiveModes(domains.value));
const visibleModes = computed(() => uiModes.value);
// Drives the width at which the control strip switches to its two-row layout.
const controlStripDensity = computed(() => {
  const count = visibleModes.value.length;
  return count >= 5 ? "modes-many" : count === 4 ? "modes-some" : "modes-few";
});
const selectedSummary = computed(
  () => versions.value.find((item) => item.version === selectedVersion.value) || null,
);
const selectedVersionIsChunkOnly = computed(() => isChunkOnlyVersion(selectedSummary.value));
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

const {
  compareBaseOptions,
  compareDomains,
  compareBaseVersion,
  compareBaseDisplayVersion,
  compareScope,
  switchCompareDomain,
  updateCompareBase,
} = useArchiveCompare({
  route,
  domains,
  domain,
  domainId,
  versions,
  selectedVersion,
  selectedSummary,
  navigate,
  replaceQuery,
});

const searchableMode = computed(() => SEARCHABLE_MODES.has(mode.value));
const isGenericFileManifestDomain = computed(() =>
  domain.value?.kind === "files"
  && domain.value?.adapter === "generic"
  && Number(selectedSummary.value?.artifact_kinds?.package?.count || 0) > 0,
);
const usesChunkFileBrowser = computed(() => mode.value === "files" && (domain.value?.adapter === "hoyo" || isGenericFileManifestDomain.value));
const isFileTreeMode = computed(
  () => mode.value === "files" && (
    ["patchersdk", "perfectworld_patcher", "wuwa", "hoyo"].includes(domain.value?.adapter || "")
    || isGenericFileManifestDomain.value
  ),
);
const usesArtifactTree = computed(() => isFileTreeMode.value && Boolean(query.value.trim()));
const usesRemoteTree = computed(() => mode.value === "resources" || (isFileTreeMode.value && !query.value.trim()));
watch(() => [domainId.value, selectedVersion.value, mode.value], () => { browserFileTime.value = null; }, { flush: "sync" });
const exportArtifactKind = computed(() => artifactKindForMode(mode.value));
const supportsArtifactField = (field: string) =>
  domainFieldSupport(domain.value, "artifact_fields", field) === "supported";
const supportsDomainAction = (action: string) => domainActionSupport(domain.value, action);
const isMetadataOnlyDomain = (candidate: ArchiveDomain | null): boolean =>
  Boolean(
    candidate?.game_id === "azurpromilia"
    && candidate.capability_contract?.live_probe === false
    && candidate.capability_contract?.availability_source_kinds?.includes("metadata_inference"),
  );
const canExportArtifacts = computed(() => mode.value !== "files" && mode.value !== "apk" && Boolean(exportArtifactKind.value));
const canExportUrls = computed(
  () => canExportArtifacts.value && (supportsDomainAction("download") || supportsDomainAction("open") || supportsArtifactField("urls")),
);
const canFilterAvailability = computed(() => {
  if (isMetadataOnlyDomain(domain.value)) return false;
  if (!supportsArtifactField("availability")) return false;
  if (!["apk", "packages", "patches"].includes(mode.value)) return false;
  const kind = exportArtifactKind.value;
  const kindSummary = kind ? selectedSummary.value?.artifact_kinds?.[kind] : null;
  const total = kind ? (kindSummary?.count ?? 0) : (selectedSummary.value?.artifact_count || artifacts.value.length || 0);
  return total > 1;
});
const availabilityStateForRequest = computed(() =>
  mode.value === "files" || availabilityFilter.value === "all" || isMetadataOnlyDomain(domain.value)
    ? undefined
    : availabilityFilter.value,
);

const loadedArchiveArtifacts = useArchiveArtifactsLoader({
  getContext: (): ArchiveArtifactLoadContext => ({
    domainId: domainId.value,
    gameId: gameId.value,
    selectedVersion: selectedVersion.value,
    mode: mode.value,
    artifactPage: artifactPage.value,
    artifactPageSize: artifactPageSize.value,
    domainGameId: domain.value?.game_id,
    domainKind: domain.value?.kind,
    domainHasPackageManifest: isGenericFileManifestDomain.value,
    domainAdapter: domain.value?.adapter,
    versionsDomainId: versionsDomainId.value,
    hasSelectedVersion: versions.value.some((item) => item.version === selectedVersion.value),
    query: query.value.trim(),
    availabilityState: availabilityStateForRequest.value,
    channelVersions: channelVersions.value,
    searchableMode: searchableMode.value,
    usesRemoteTree: usesRemoteTree.value,
    usesArtifactTree: usesArtifactTree.value,
  }),
  resetPresentation: () => {
    selectedCategory.value = "all";
    chunkCategoryFilter.value = "all";
    remoteTreeProbeTime.value = null;
  },
  setLeads: (loadedLeads) => {
    leads.value = loadedLeads;
  },
});
archiveArtifactsLoader = loadedArchiveArtifacts;
const {
  artifacts,
  nextCursor,
  total: artifactTotal,
  loadingMore,
  error,
  chunkCollection,
  chunkDetail,
  chunkLoading,
  chunkError,
} = loadedArchiveArtifacts;

function selectArtifactPage(page: number): void {
  artifactPage.value = page;
  void loadArtifacts(false);
}

function selectArtifactPageSize(pageSize: number): void {
  artifactPageSize.value = pageSize;
  artifactPage.value = 1;
  void loadArtifacts(false);
}

watch(
  () => [domainId.value, selectedVersion.value, mode.value, query.value, availabilityFilter.value],
  (next, previous) => {
    if (previous && next.some((value, index) => value !== previous[index])) artifactPage.value = 1;
  },
);

const usesPreferredUrlPresentation = computed(
  () =>
    supportsArtifactField("urls") &&
    supportsArtifactField("availability") &&
    Boolean(domain.value?.capability_contract?.url_source_kinds?.includes("mirror")),
);
const suppressAvailabilityPresentation = computed(() =>
  isMetadataOnlyDomain(domain.value),
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

const { exportUrlsLabel, exportArtifacts } = useArchiveExport({
  gameId,
  domainId,
  domain,
  selectedVersion,
  selectedSummary,
  mode,
  query,
  searchableMode,
  exportArtifactKind,
  canExportArtifacts,
  canExportUrls,
  artifacts,
  chunkDetail,
  setToast,
});

const isWuwaFilesMode = computed(() => domain.value?.adapter === "wuwa" && mode.value === "files");
const wuwaManifestSize = computed(() => {
  const context = remoteManifestSize.value;
  if (!isWuwaFilesMode.value || context?.domainId !== domainId.value
    || context.version !== selectedVersion.value || context.kind !== "file") return null;
  return context.size;
});
watch(
  () => [domainId.value, selectedVersion.value, mode.value, usesArtifactTree.value, usesChunkFileBrowser.value],
  () => {
    manifestSizeController?.abort();
    manifestSizeController = null;
    const generation = ++manifestSizeGeneration;
    // Search uses the local tree. Fetch metadata once when its remote browser is absent.
    if (!usesArtifactTree.value || usesChunkFileBrowser.value) return;
    const knownTime = browserFileTime.value?.domainId === domainId.value && browserFileTime.value?.version === selectedVersion.value
      && !browserFileTime.value.loading;
    if (knownTime && (!isWuwaFilesMode.value || wuwaManifestSize.value !== null)) return;
    const context = { domainId: domainId.value, version: selectedVersion.value, kind: "file" };
    const request = new AbortController();
    manifestSizeController = request;
    const isCurrent = () => manifestSizeController === request && manifestSizeGeneration === generation
      && mode.value === "files" && usesArtifactTree.value && !usesChunkFileBrowser.value
      && context.domainId === domainId.value && context.version === selectedVersion.value;
    void api.artifactTree(context.domainId, context.version, { kind: "file", limit: 1 }, request.signal)
      .then((result) => {
        if (!isCurrent()) return;
        onRemoteManifestSizeChange({ ...context, size: result.manifest_total_size ?? null });
        onFileTimeChange({ domainId: context.domainId, version: context.version, source: "package", identity: "game", fileTime: result.file_time ?? null, timeSource: result.file_time_source });
      })
      .catch(() => {
        if (isCurrent() && wuwaManifestSize.value === null) onRemoteManifestSizeChange({ ...context, size: null });
        if (isCurrent()) onFileTimeChange({ domainId: context.domainId, version: context.version, source: "package", identity: "game", fileTime: null });
      });
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  manifestSizeController?.abort();
  manifestSizeController = null;
  manifestSizeGeneration += 1;
});

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

function onWindowKeyDown(e: KeyboardEvent): void {
  if (e.key === "Escape") {
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
  if (usesRemoteTree.value || (mode.value === "files" && (domain.value?.adapter === "hoyo" || isGenericFileManifestDomain.value))) return [];
  if (usesArtifactTree.value) return artifacts.value;
  if (["packages", "patches"].includes(mode.value) && usesPreferredUrlPresentation.value && domain.value?.adapter !== "wuwa") {
    return artifacts.value;
  }
  return displayedArtifacts.value;
});

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
  if (mode.value === "compare") return `${selectedDisplayVersion.value} 版本对比`;
  if (mode.value === "manifest") return "官方清单文件";
  if (mode.value === "archive") return `${selectedDisplayVersion.value} 归档信息`;
  if (mode.value === "legacy") return "候选线索";
  return `${selectedDisplayVersion.value} ${modeLabel(domain.value, mode.value)}`;
});
const displayGameName = computed(() => {
  const current = game.value;
  if (!current) return gameId.value;
  return /[\u3400-\u9fff]/.test(current.name) ? current.name : current.sub_name || current.name;
});

const fileTimeMetadata = computed(() => {
  if (mode.value !== "files") return null;
  const summary = selectedSummary.value;
  const attrs = (summary?.attributes || {}) as Record<string, unknown>;
  const current = browserFileTime.value;
  const context = current?.domainId === domainId.value && current.version === selectedVersion.value ? current : null;
  if (context?.loading) return null;
  if (context && context.fileTime !== null) {
    // Invalid explicit metadata must not fall back to an unrelated date.
    return typeof context.fileTime === "string" && observedDate(context.fileTime) && context.timeSource
      ? { value: context.fileTime, source: context.timeSource } : null;
  }
  // Version summaries describe the primary identity; voice components need their own response.
  const identity = context?.identity || (usesChunkFileBrowser.value ? String(route.query.identity || "game") : "game");
  if (identity !== "game") return null;
  const source = context?.source || (route.query.source === "chunk" ? "chunk" :
    usesChunkFileBrowser.value && !summary?.artifact_kinds?.package?.count && !summary?.artifact_kinds?.file?.count && summary?.artifact_kinds?.chunk?.count ? "chunk" : "package");
  const expectedTimeSource = context?.timeSource || (source === "chunk" || !usesChunkFileBrowser.value || isGenericFileManifestDomain.value ? "manifest" : "package");
  if (attrs.file_modified_at !== undefined && attrs.file_modified_at !== null) {
    return typeof attrs.file_modified_at === "string" && observedDate(attrs.file_modified_at)
      && attrs.file_time_source === expectedTimeSource
      ? { value: attrs.file_modified_at, source: expectedTimeSource } : null;
  }
  if (expectedTimeSource === "manifest" && attrs.manifest_modified_at !== undefined && attrs.manifest_modified_at !== null) {
    return typeof attrs.manifest_modified_at === "string" && observedDate(attrs.manifest_modified_at)
      ? { value: attrs.manifest_modified_at, source: "manifest" } : null;
  }
  // NTE's existing source_updated_at contract means the official manifest Last-Modified.
  if (domain.value?.game_id === "nte" && ["pc", "windows"].includes(domain.value.platform.toLowerCase())
    && observedDate(summary?.source_updated_at)) return { value: summary!.source_updated_at!, source: "manifest" };
  return null;
});

const versionMetaSummary = computed(() => {
  const summary = selectedSummary.value;
  const dom = domain.value;
  if (!summary || !dom) return [];

  const items: Array<{ label: string; value: string; isMono?: boolean; title?: string }> = [];

  // WuWa's package and patch buckets include alternative update paths, not a file-list total.
  const kind = ["apk", "packages", "patches", "files"].includes(mode.value) ? artifactKindForMode(mode.value) : "";
  const count = kind ? (summary.artifact_kinds?.[kind]?.count || 0) : (summary.artifact_count || 0);
  const size = kind ? (summary.artifact_kinds?.[kind]?.size || 0) : (summary.packed_size || 0);
  if (wuwaManifestSize.value !== null) {
    items.push({ label: "总大小", value: formatBytes(wuwaManifestSize.value), isMono: true });
  } else if (size > 0 && count > 1) {
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

  if (mode.value === "files") {
    const fileTime = fileTimeMetadata.value;
    if (fileTime) {
      items.push({
        label: "文件时间", value: formatObservedDate(fileTime.value), isMono: true,
        title: fileTime.source === "manifest"
          ? "官方清单文件的最后修改时间（北京时间），不代表清单内每个文件的修改时间"
          : "官方资源包的最后修改时间（北京时间）；分卷包取各分卷中最晚的修改时间，不代表资源包内每个文件的修改时间",
      });
    }
  } else if (mode.value === "chunks" && manifestTime) {
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
  const time = globalProbeLoaded.value
    ? globalProbeTime.value
    : latestLiveProbeTime(footerProbeArtifacts.value) || remoteTreeProbeTime.value;
  if (!time) return "";
  const formatted = formatObservedDate(time);
  const rel = formatRelativeTime(time, probeTimeClock.value);
  return rel ? `${formatted} (${rel})` : formatted;
});
const currentVersionApiUrl = computed(() => {
  if (!domainId.value || !selectedVersion.value) return "";
  if (mode.value === "chunks") {
    return apiUrl(`/domains/${encodeURIComponent(domainId.value)}/versions/${encodeURIComponent(selectedVersion.value)}/chunk-manifests`);
  }
  if (mode.value === "files" && (["hoyo", "perfectworld_patcher"].includes(domain.value?.adapter || "") || isGenericFileManifestDomain.value)) {
    return apiUrl(`/domains/${encodeURIComponent(domainId.value)}/versions/${encodeURIComponent(selectedVersion.value)}/files`);
  }
  return apiUrl(`/domains/${encodeURIComponent(domainId.value)}/versions/${encodeURIComponent(selectedVersion.value)}`);
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
  const targetVersion = String(params.version || selectedVersion.value);
  const targetDomain = params.domainId
    ? domains.value.find((item) => item.id === params.domainId)
    : undefined;
  const routeDomain = targetDomain ? domainRouteLabel(gameId.value, targetDomain) : params.domainId;
  const nextParams = {
    ...route.params,
    ...params,
    ...(routeDomain ? { domainId: routeDomain } : {}),
    ...(params.version ? { version: routeVersionLabel(params.version) } : {}),
  } as Record<string, string>;
  const targetMode = String(nextParams.mode || mode.value);
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

function switchToFiles(): void {
  if (domain.value) void navigateMode(domain.value, "files");
}

async function replaceQuery(name: "q" | "availability" | "from", value: string): Promise<void> {
  const next = { ...route.query };
  if (value && value !== "all") next[name] = value;
  else delete next[name];
  await router.replace({ name: "archive", params: route.params, query: next });
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
      registryTargetDomain.value === domainId.value
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
      const icon = gId ? iconForGame(games.value, gId) : undefined;
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
  void loadGlobalProbeTime();
}

async function loadGlobalProbeTime(): Promise<void> {
  probeTimeClock.value = Date.now();
  globalProbeController?.abort();
  const controller = new AbortController();
  globalProbeController = controller;
  try {
    const result = await api.latestProbeTime(controller.signal);
    if (!controller.signal.aborted) {
      globalProbeTime.value = result.last_checked_at;
      globalProbeLoaded.value = true;
    }
  } catch (error) {
    // Keep the page-local timestamp as a compatibility fallback when an older
    // API has not deployed the global probe endpoint yet.
    if (!controller.signal.aborted && !isAbortError(error)) globalProbeLoaded.value = false;
  }
}
function onAvailabilityStorageInvalidated(event: StorageEvent): void {
  if (event.key === "gmi-availability-invalidated-at" && event.newValue) onAvailabilityInvalidated();
}
onMounted(() => {
  loadRegistry();
  void loadGlobalProbeTime();
  window.addEventListener("keydown", onWindowKeyDown);
  window.addEventListener("gmi-availability-invalidated", onAvailabilityInvalidated);
  window.addEventListener("storage", onAvailabilityStorageInvalidated);
});
onBeforeUnmount(() => {
  gameActivityController?.abort();
  globalProbeController?.abort();
  disposeArchiveLoader();
  if (searchTimer !== null) window.clearTimeout(searchTimer);
  if (toastTimer !== null) window.clearTimeout(toastTimer);
  window.removeEventListener("keydown", onWindowKeyDown);
  window.removeEventListener("gmi-availability-invalidated", onAvailabilityInvalidated);
  window.removeEventListener("storage", onAvailabilityStorageInvalidated);
});

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
async function copyArtifactUrl(artifact: Artifact): Promise<void> {
  const url = preferredAvailableUrl(domain.value, artifact, "copy") || rawArtifactUrl(artifact) || artifact.urls[0]?.url;
  await copyUrl(url);
}
async function copyUrl(url?: string): Promise<void> {
  if (!url) return;
  setToast((await copyTextToClipboard(url)) ? "链接已复制" : "复制失败，请手动复制");
}
async function onCopyChunkUrl(url: string, label = "链接"): Promise<void> {
  if (!url) return;
  setToast((await copyTextToClipboard(url)) ? `${label}已复制` : "复制失败，请手动复制");
}
function onRemoteTreeProbeTimeChange(value: string | null): void {
  remoteTreeProbeTime.value = value;
}
function onFileTimeChange(context: FileTimeChange): void {
  if (mode.value !== "files" || context.domainId !== domainId.value || context.version !== selectedVersion.value) return;
  browserFileTime.value = context;
}
function onRemoteManifestSizeChange(context: { domainId: string; version: string; kind: string; size: number | null }): void {
  if (!isWuwaFilesMode.value || context.domainId !== domainId.value
    || context.version !== selectedVersion.value || context.kind !== "file") return;
  const size = context.size;
  remoteManifestSize.value = {
    ...context, size: typeof size === "number" && Number.isSafeInteger(size) && size >= 0 ? size : null,
  };
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
    <ArchiveGameSidebar
      :games="games"
      :game-id="gameId"
      @select-game="navigate({ gameId: $event, domainId: '', version: '', mode: '' })"
    />
    <main class="main-content">
      <header id="home" class="topbar">
        <div>
          <p class="kicker">Unofficial URL Archive</p>
          <h1>{{ displayGameName || '游戏' }}官方文件索引</h1>
        </div>
        <button class="topbar-changelog" type="button" @click="openSiteChangelog($event)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
            <rect x="3" y="5" width="18" height="16" rx="2" />
            <path d="M7 3v4M17 3v4M3 10h18M7 14h5" />
          </svg>
          <span>更新日志</span>
          <span class="topbar-changelog-arrow" aria-hidden="true">↗</span>
        </button>
      </header>
      <section v-if="recentActivity.length" class="recent-activity" aria-label="最近资源变动">
        <div class="recent-activity-heading">
          <strong>最近资源变动</strong>
          <button type="button" @click="openSiteChangelog($event, 'data')">查看全部</button>
        </div>
        <ol>
          <li v-for="event in recentActivity" :key="event.id">
            <time :datetime="event.occurred_at">{{ gameActivityTime(event.occurred_at) }}</time>
            <span class="recent-activity-text">
              {{ gameActivityTitle(event, displayGameName) }}
              <span v-if="recentActivity.length > 1" class="recent-activity-platform">{{ gameActivityPlatform(event) }}</span>
            </span>
          </li>
        </ol>
      </section>
      <ArchiveControlStrip
        :versions="versions"
        :selected-version="selectedVersion"
        :domain="domain"
        :domain-id="domainId"
        :mode="mode"
        :visible-modes="visibleModes"
        :control-strip-density="controlStripDensity"
        :searchable-mode="searchableMode"
        :query="query"
        :suppress-availability-presentation="suppressAvailabilityPresentation"
        @select-version="navigate({ version: $event })"
        @select-mode="navigateMode"
        @update:query="query = $event"
      />
      <section id="files" class="file-panel">
        <div class="panel-head">
          <div class="panel-header-top">
            <div class="panel-heading-block">
              <p class="kicker">{{ panelEyebrow }}</p>
              <div class="panel-title-row">
                <h2>{{ panelTitle }}</h2>
                <div v-if="versionMetaSummary.length" class="panel-meta-inline">
                  <span v-for="(item, idx) in versionMetaSummary" :key="item.label" class="meta-inline-item" :title="item.title">
                    <span v-if="idx > 0" class="meta-dot">·</span>
                    <span class="meta-label">{{ item.label }}</span>
                    <span class="meta-value" :class="{ 'text-mono': item.isMono }">{{ item.value }}</span>
                  </span>
                </div>
              </div>
            </div>
            <div v-if="canExportArtifacts || currentVersionApiUrl || mode === 'compare' || mode === 'legacy' || isWuwaFilesMode" class="panel-tools">
              <ArchiveWuwaRawIndexMenu
                v-if="isWuwaFilesMode"
                :manifest-url="wuwaManifestUrl"
                :base-url="wuwaBaseUrl"
                @copy-url="copyUrl"
              />
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
        <ArchiveCompareView
          v-else-if="mode === 'compare'"
          :domain-id="domainId"
          :selected-version="selectedVersion"
          :selected-display-version="selectedDisplayVersion"
          :compare-domains="compareDomains"
          :compare-base-version="compareBaseVersion"
          :compare-base-display-version="compareBaseDisplayVersion"
          :compare-base-options="compareBaseOptions"
          :compare-scope="compareScope"
          @switch-domain="switchCompareDomain"
          @update-base="updateCompareBase"
        />
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
          <ArtifactPagination :page="artifactPage" :total="artifactTotal || 0" :page-size="artifactPageSize" :loading="loadingMore" @update:page="selectArtifactPage" @update:page-size="selectArtifactPageSize" />
        </div>
        <div v-else-if="mode === 'manifest'" class="empty">当前版本没有官方清单记录。</div>
        <div v-else-if="mode === 'chunks'" class="chunk-manifest-wrapper">
          <ChunkManifestView
            :domain="domain"
            :version="selectedDisplayVersion"
            :chunk-detail="chunkDetail"
            :artifacts="artifacts"
            :category-filter="chunkCategoryFilter"
            :loading="loading || chunkLoading"
            :error="chunkError"
            @copy-url="onCopyChunkUrl"
          />
        </div>
        <div v-else-if="mode === 'files' && (domain?.adapter === 'hoyo' || isGenericFileManifestDomain)" class="chunk-file-browser-wrapper">
          <ChunkFileBrowser
            :domain="domain"
            :game="game"
            :version="selectedVersion"
            :domain-id="domainId"
            :chunk-detail="chunkDetail"
            :version-summary="selectedSummary"
            :chunk-collection="chunkCollection"
            :search-query="query"
            @file-time-change="onFileTimeChange"
          />
        </div>
        <template v-if="!loading && !error && !['legacy', 'archive', 'compare', 'manifest', 'chunks'].includes(mode) && !(mode === 'files' && (domain?.adapter === 'hoyo' || isGenericFileManifestDomain))">
          <div v-if="usesRemoteTree && domain" class="remote-workspace">
            <template v-if="mode === 'resources' && selectedSummary">
              <div class="chunk-summary resource-summary">
                <div>
                  <span>资源版本</span>
                  <strong>{{ displayVersionLabel(String(selectedSummary.attributes.resource_version || selectedVersion)) }}</strong>
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
              @manifest-size-change="onRemoteManifestSizeChange"
              @file-time-change="onFileTimeChange"
            />
          </div>
          <div v-else-if="!displayedArtifacts.length" class="empty">
            <template v-if="selectedVersionIsChunkOnly && (mode === 'packages' || mode === 'patches')">
              <span>该版本仅提供 Chunk 分发，当前视图没有对应资源。</span>
              <button class="tool-button" type="button" @click="switchToFiles">切换到文件视图</button>
            </template>
            <template v-else>
              {{ domain?.adapter === 'hoyo' && mode === 'packages' ? '该分类下没有压缩包直链' : '没有符合当前条件的归档记录。' }}
            </template>
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
          <ArchiveApkList
            v-else-if="mode === 'apk'"
            :artifacts="displayedArtifacts"
            :domain="domain"
            :suppress-availability-presentation="suppressAvailabilityPresentation"
            @copy-url="copyUrl"
            @copy-artifact-url="copyArtifactUrl"
          />
          <ArchivePackageList
            v-else-if="mode === 'packages'"
            :artifacts="artifacts"
            :displayed-artifacts="displayedArtifacts"
            :domain="domain"
            :selected-summary="selectedSummary"
            :selected-version="selectedVersion"
            :uses-preferred-url-presentation="usesPreferredUrlPresentation"
            :suppress-availability-presentation="suppressAvailabilityPresentation"
            :artifact-page="artifactPage"
            :artifact-total="artifactTotal || 0"
            :artifact-page-size="artifactPageSize"
            :loading-more="loadingMore"
            @copy-url="copyUrl"
            @copy-artifact-url="copyArtifactUrl"
            @copy-manifest-url="copyManifestUrl"
            @copy-base-url="copyBaseUrl"
            @open-files="openArtifactFiles"
            @update:page="selectArtifactPage"
            @update:page-size="selectArtifactPageSize"
          />
          <ArchivePatchList
            v-else-if="mode === 'patches' && (usesPreferredUrlPresentation || domain?.adapter === 'wuwa' || domain?.adapter === 'hoyo')"
            :displayed-artifacts="displayedArtifacts"
            :domain="domain"
            :selected-version="selectedVersion"
            :uses-preferred-url-presentation="usesPreferredUrlPresentation"
            :artifact-page="artifactPage"
            :artifact-total="artifactTotal || 0"
            :artifact-page-size="artifactPageSize"
            :loading-more="loadingMore"
            @copy-url="copyUrl"
            @copy-artifact-url="copyArtifactUrl"
            @copy-manifest-url="copyManifestUrl"
            @copy-base-url="copyBaseUrl"
            @open-files="openArtifactFiles"
            @update:page="selectArtifactPage"
            @update:page-size="selectArtifactPageSize"
          />
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
                  v-if="preferredAvailableUrl(domain, artifact, 'copy')"
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
                  v-if="preferredAvailableUrl(domain, artifact)"
                  class="icon-button"
                  :href="preferredAvailableUrl(domain, artifact)"
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
            <ArtifactPagination :page="artifactPage" :total="artifactTotal || 0" :page-size="artifactPageSize" :loading="loadingMore" @update:page="selectArtifactPage" @update:page-size="selectArtifactPageSize" />
          </div>
        </template>
      </section>
      <footer class="archive-footer">
        <ProbeScheduleInfo :checked-time="syncTimeText" :global-time="globalProbeLoaded" @refresh="loadGlobalProbeTime" />
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
    <SiteChangelogModal
      :open="showSiteChangelog"
      :origin-pos="siteChangelogOrigin"
      :initial-tab="siteChangelogInitialTab"
      :game-names="gameNames"
      @close="showSiteChangelog = false"
    />
  </div>
</template>
