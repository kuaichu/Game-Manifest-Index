import { computed, ref, watch, type Ref } from "vue";
import { baseUrlFor, isFileManifestArtifact, manifestUrlFor } from "../archive-artifact-helpers";
import { hoyoArtifactCardPresentation, hoyoLanguageLabel } from "../domain-presentation";
import type {
  ArchiveDomain,
  Artifact,
  ChunkManifestDetail,
  ResourcePacksChange,
  VersionSummary,
} from "../types";

export interface ArchiveFiltersAndPacksOptions {
  domainId: Ref<string>;
  domain: Ref<ArchiveDomain | null>;
  selectedVersion: Ref<string>;
  selectedSummary: Ref<VersionSummary | null>;
  mode: Ref<string>;
  artifacts: Ref<Artifact[]>;
  chunkDetail: Ref<ChunkManifestDetail | null>;
  usesRemoteTree: Ref<boolean>;
  isGenericFileManifestDomain: Ref<boolean>;
  usesPreferredUrlPresentation: Ref<boolean>;
}

export function useArchiveFiltersAndPacks(options: ArchiveFiltersAndPacksOptions) {
  const remoteManifestSize = ref<{ domainId: string; version: string; kind: string; size: number | null } | null>(null);
  // Kuro resource-pack versions: info reported by the file tree; "" selects the backend default (common pack).
  const resourcePacksByContext = ref<ResourcePacksChange | null>(null);
  const selectedPack = ref("");
  const selectedCategory = ref<string>("all");
  const selectedChunkFilter = ref<string>("all");

  watch(
    () => [options.domainId.value, options.selectedVersion.value],
    () => {
      selectedPack.value = "";
    },
    { flush: "sync" },
  );

  const isWuwaFilesMode = computed(() => options.domain.value?.adapter === "wuwa" && options.mode.value === "files");

  const wuwaManifestSize = computed(() => {
    const context = remoteManifestSize.value;
    if (!isWuwaFilesMode.value || context?.domainId !== options.domainId.value
      || context.version !== options.selectedVersion.value || context.kind !== "file") return null;
    return context.size;
  });

  const activeResourcePacks = computed(() => {
    const state = resourcePacksByContext.value;
    return isWuwaFilesMode.value && state?.domainId === options.domainId.value && state.version === options.selectedVersion.value
      ? state : null;
  });

  const activePackIdentity = computed(() => selectedPack.value || activeResourcePacks.value?.resourcePacks?.selected || "");

  function selectResourcePack(identity: string): void {
    if (identity !== activePackIdentity.value) selectedPack.value = identity;
  }

  function onResourcePacksChange(change: ResourcePacksChange): void {
    if (!isWuwaFilesMode.value || change.domainId !== options.domainId.value || change.version !== options.selectedVersion.value) return;
    resourcePacksByContext.value = change;
  }

  function onRemoteManifestSizeChange(context: { domainId: string; version: string; kind: string; size: number | null }): void {
    if (!isWuwaFilesMode.value || context.domainId !== options.domainId.value
      || context.version !== options.selectedVersion.value || context.kind !== "file") return;
    const size = context.size;
    remoteManifestSize.value = {
      ...context,
      size: typeof size === "number" && Number.isSafeInteger(size) && size >= 0 ? size : null,
    };
  }

  const wuwaManifestUrl = computed(() => {
    const packs = activeResourcePacks.value?.resourcePacks;
    if (packs) return packs.packs.find((item) => item.identity === activePackIdentity.value)?.manifest_url || "";
    const meta = options.selectedSummary.value?.attributes?.manifest_urls;
    if (Array.isArray(meta) && typeof meta[0] === "string") return meta[0];
    const pkgArtifact = options.artifacts.value.find((a) => a.kind === "package");
    if (pkgArtifact) return manifestUrlFor(pkgArtifact) || "";
    return "";
  });

  const wuwaBaseUrl = computed(() => {
    if (activeResourcePacks.value?.resourcePacks) return activeResourcePacks.value.baseUrl;
    const meta = options.selectedSummary.value?.attributes?.base_urls;
    if (Array.isArray(meta) && typeof meta[0] === "string") return meta[0];
    const pkgArtifact = options.artifacts.value.find((a) => a.kind === "package");
    if (pkgArtifact) return baseUrlFor(pkgArtifact) || "";
    return "";
  });

  function formatCategoryLabel(cat: string): string {
    if (cat === "游戏包分卷") return "游戏分卷";
    if (cat === "全部") return "全部文件";
    if (cat.endsWith("语音更新")) return cat.replace("更新", "");
    return cat;
  }

  function artifactCategory(artifact: Artifact): string {
    if (options.domain.value?.adapter === "hoyo") {
      const pres = hoyoArtifactCardPresentation(artifact, options.selectedVersion.value);
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
      if (options.domain.value?.adapter === "wuwa" || isFileManifestArtifact(artifact)) return "资源清单";
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
    if (!options.artifacts.value.length) return [];
    const counts: Record<string, number> = {};
    for (const artifact of options.artifacts.value) {
      const cat = artifactCategory(artifact);
      counts[cat] = (counts[cat] || 0) + 1;
    }
    const keys = Object.keys(counts);
    if (keys.length <= 1) return [];
    const list = [{ id: "all", label: "全部文件", count: options.artifacts.value.length }];
    for (const key of keys) {
      list.push({ id: key, label: formatCategoryLabel(key), count: counts[key] });
    }
    return list;
  });

  const chunkFilterOptions = computed(() => {
    if (!options.chunkDetail.value?.manifests?.length) return [];
    const manifests = options.chunkDetail.value.manifests;
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
    if (selectedCategory.value === "all") return options.artifacts.value;
    return options.artifacts.value.filter((artifact) => artifactCategory(artifact) === selectedCategory.value);
  });

  function chunkArtifactMatchesFilter(artifact: Artifact): boolean {
    const filter = selectedChunkFilter.value;
    if (filter === "all") return true;
    const component = String(artifact.attributes?.component || "game").toLowerCase();
    if (filter === "game") return component === "game";
    const language = String(artifact.attributes?.language || "voice").toLowerCase();
    return component === "voice" && language === filter;
  }

  const footerProbeArtifacts = computed(() => {
    if (options.mode.value === "chunks") return options.artifacts.value.filter(chunkArtifactMatchesFilter);
    if (options.usesRemoteTree.value || (options.mode.value === "files" && (options.domain.value?.adapter === "hoyo" || options.isGenericFileManifestDomain.value))) return [];
    if (["packages", "patches"].includes(options.mode.value) && options.usesPreferredUrlPresentation.value && options.domain.value?.adapter !== "wuwa") {
      return options.artifacts.value;
    }
    return displayedArtifacts.value;
  });

  function resetFilters(): void {
    selectedCategory.value = "all";
    selectedChunkFilter.value = "all";
  }

  return {
    selectedPack,
    resourcePacksByContext,
    remoteManifestSize,
    isWuwaFilesMode,
    wuwaManifestSize,
    activeResourcePacks,
    activePackIdentity,
    selectResourcePack,
    onResourcePacksChange,
    onRemoteManifestSizeChange,
    wuwaManifestUrl,
    wuwaBaseUrl,
    selectedCategory,
    selectedChunkFilter,
    formatCategoryLabel,
    artifactCategory,
    categoryFilters,
    chunkFilterOptions,
    displayedArtifacts,
    chunkArtifactMatchesFilter,
    footerProbeArtifacts,
    resetFilters,
  };
}
