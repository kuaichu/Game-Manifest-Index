import { computed, type Ref } from "vue";
import type { RouteLocationNormalizedLoaded } from "vue-router";
import { apiUrl } from "../api";
import { formatRelativeTime, observedDate } from "../archive-artifact-helpers";
import {
  artifactKindForMode,
  domainActionSupport,
  domainModeLabel,
  formatBytes,
  formatObservedDate,
  latestLiveProbeTime,
} from "../domain-presentation";
import type {
  ArchiveDomain,
  ArchiveLead,
  Artifact,
  ChunkManifestDetail,
  FileTimeChange,
  Game,
  VersionSummary,
} from "../types";

export interface ArchivePresentationMetaOptions {
  route: RouteLocationNormalizedLoaded;
  gameId: Ref<string>;
  game: Ref<Game | null>;
  domainId: Ref<string>;
  domain: Ref<ArchiveDomain | null>;
  selectedVersion: Ref<string>;
  selectedDisplayVersion: Ref<string>;
  selectedSummary: Ref<VersionSummary | null>;
  mode: Ref<string>;
  usesChunkFileBrowser: Ref<boolean>;
  isGenericFileManifestDomain: Ref<boolean>;
  wuwaManifestSize: Ref<number | null>;
  chunkDetail: Ref<ChunkManifestDetail | null>;
  browserFileTime: Ref<FileTimeChange | null>;
  globalProbeLoaded: Ref<boolean>;
  globalProbeTime: Ref<string | null>;
  remoteTreeProbeTime: Ref<string | null>;
  probeTimeClock: Ref<number>;
  footerProbeArtifacts: Ref<Artifact[]>;
  leads: Ref<ArchiveLead[]>;
}

export function useArchivePresentationMeta(options: ArchivePresentationMetaOptions) {
  function modeLabel(item: ArchiveDomain | null | undefined, capability: string): string {
    return domainModeLabel(item, capability);
  }

  const displayGameName = computed(() => {
    const current = options.game.value;
    if (!current) return options.gameId.value;
    return /[\u3400-\u9fff]/.test(current.name) ? current.name : current.sub_name || current.name;
  });

  const panelEyebrow = computed(() => {
    if (options.mode.value === "resources") {
      return options.gameId.value === "endfield"
        ? "Endfield Windows resources"
        : `${displayGameName.value || options.gameId.value} Windows resources`;
    }
    if (["patchersdk", "perfectworld_patcher"].includes(options.domain.value?.adapter || "") && options.mode.value === "files") {
      return `${options.gameId.value.toUpperCase()} files`;
    }
    if (options.domain.value?.adapter === "arknights" && options.mode.value === "packages") return "Arknights packages";
    if (options.mode.value === "legacy") return "Historical candidates";
    if (options.domain.value?.adapter === "hoyo") return "HOYO PC 客户端";
    if (options.domain.value?.adapter === "android" || options.domain.value?.kind === "apk") return "Android 官方客户端";
    if (options.domain.value?.adapter === "wuwa") return "Wuwa files";
    return modeLabel(options.domain.value, options.mode.value);
  });

  const panelTitle = computed(() => {
    if (options.mode.value === "compare") return `${options.selectedDisplayVersion.value} 版本对比`;
    if (options.mode.value === "manifest") return "官方清单文件";
    if (options.mode.value === "archive") return `${options.selectedDisplayVersion.value} 归档信息`;
    if (options.mode.value === "legacy") return "候选线索";
    return `${options.selectedDisplayVersion.value} ${modeLabel(options.domain.value, options.mode.value)}`;
  });

  const fileTimeMetadata = computed(() => {
    if (options.mode.value !== "files") return null;
    const summary = options.selectedSummary.value;
    const attrs = (summary?.attributes || {}) as Record<string, unknown>;
    const current = options.browserFileTime.value;
    const context = current?.domainId === options.domainId.value && current.version === options.selectedVersion.value ? current : null;
    if (context?.loading) return null;
    if (context && context.fileTime !== null) {
      // Invalid explicit metadata must not fall back to an unrelated date.
      return typeof context.fileTime === "string" && observedDate(context.fileTime) && context.timeSource
        ? { value: context.fileTime, source: context.timeSource } : null;
    }
    // Version summaries describe the primary identity; voice components need their own response.
    const identity = context?.identity || (options.usesChunkFileBrowser.value ? String(options.route.query.identity || "game") : "game");
    if (identity !== "game") return null;
    const source = context?.source || (options.route.query.source === "chunk" ? "chunk" :
      options.usesChunkFileBrowser.value && !summary?.artifact_kinds?.package?.count && !summary?.artifact_kinds?.file?.count && summary?.artifact_kinds?.chunk?.count ? "chunk" : "package");
    const expectedTimeSource = context?.timeSource || (source === "chunk" || !options.usesChunkFileBrowser.value || options.isGenericFileManifestDomain.value ? "manifest" : "package");
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
    if (options.domain.value?.game_id === "nte" && ["pc", "windows"].includes(options.domain.value.platform.toLowerCase())
      && observedDate(summary?.source_updated_at)) return { value: summary!.source_updated_at!, source: "manifest" };
    return null;
  });

  const versionMetaSummary = computed(() => {
    const summary = options.selectedSummary.value;
    const dom = options.domain.value;
    if (!summary || !dom) return [];

    const items: Array<{ label: string; value: string; isMono?: boolean; title?: string }> = [];

    // WuWa's package and patch buckets include alternative update paths, not a file-list total.
    const kind = ["apk", "packages", "patches", "files"].includes(options.mode.value) ? artifactKindForMode(options.mode.value) : "";
    const count = kind ? (summary.artifact_kinds?.[kind]?.count || 0) : (summary.artifact_count || 0);
    const size = kind ? (summary.artifact_kinds?.[kind]?.size || 0) : (summary.packed_size || 0);
    if (options.wuwaManifestSize.value !== null) {
      items.push({ label: "总大小", value: formatBytes(options.wuwaManifestSize.value), isMono: true });
    } else if (size > 0 && count > 1) {
      items.push({ label: "总大小", value: formatBytes(size), isMono: true });
    }

    // 2. 日期语义区分（优先展示 Manifest 更新时间或官方发布时间）
    const attrs = (summary.attributes || {}) as Record<string, unknown>;
    const manifestTime = (typeof attrs.manifest_modified_at === "string" ? attrs.manifest_modified_at : "") ||
      (options.chunkDetail.value?.manifests?.[0]?.last_modified_at || "");
    const releaseTime = summary.source_released_at;
    const updateTime = summary.source_updated_at;
    const apkFileTime = options.mode.value === "apk" ? summary.observed_at : null;
    const importedTime = summary.archived_at || summary.imported_at;

    if (options.mode.value === "files") {
      const fileTime = fileTimeMetadata.value;
      if (fileTime) {
        items.push({
          label: "文件时间", value: formatObservedDate(fileTime.value), isMono: true,
          title: fileTime.source === "manifest"
            ? "官方清单文件的最后修改时间（北京时间），不代表清单内每个文件的修改时间"
            : "官方资源包的最后修改时间（北京时间）；分卷包取各分卷中最晚的修改时间，不代表资源包内每个文件的修改时间",
        });
      }
    } else if (options.mode.value === "chunks" && manifestTime) {
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
    const time = options.globalProbeLoaded.value
      ? options.globalProbeTime.value
      : latestLiveProbeTime(options.footerProbeArtifacts.value) || options.remoteTreeProbeTime.value;
    if (!time) return "";
    const formatted = formatObservedDate(time);
    const rel = formatRelativeTime(time, options.probeTimeClock.value);
    return rel ? `${formatted} (${rel})` : formatted;
  });

  const currentVersionApiUrl = computed(() => {
    if (!options.domainId.value || !options.selectedVersion.value) return "";
    if (options.mode.value === "chunks") {
      return apiUrl(`/domains/${encodeURIComponent(options.domainId.value)}/versions/${encodeURIComponent(options.selectedVersion.value)}/chunk-manifests`);
    }
    if (options.mode.value === "files" && (["hoyo", "perfectworld_patcher"].includes(options.domain.value?.adapter || "") || options.isGenericFileManifestDomain.value)) {
      return apiUrl(`/domains/${encodeURIComponent(options.domainId.value)}/versions/${encodeURIComponent(options.selectedVersion.value)}/files`);
    }
    return apiUrl(`/domains/${encodeURIComponent(options.domainId.value)}/versions/${encodeURIComponent(options.selectedVersion.value)}`);
  });

  const legacyLeads = computed(() =>
    [...options.leads.value].sort((left, right) =>
      String(left.generated_at || "").localeCompare(String(right.generated_at || "")),
    ),
  );

  function legacyArchiveUrl(lead: ArchiveLead): string | undefined {
    const url = lead.urls[0];
    const timestamp = String(url?.archive_facts.timestamp || "");
    return timestamp && url?.url ? `https://web.archive.org/web/${timestamp}/${url.url}` : undefined;
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
    return domainActionSupport(options.domain.value, action) && lead.urls[0]?.current_facts.action_allowed === true;
  }

  return {
    displayGameName,
    panelEyebrow,
    panelTitle,
    fileTimeMetadata,
    versionMetaSummary,
    syncTimeText,
    currentVersionApiUrl,
    legacyLeads,
    legacyArchiveUrl,
    leadClassificationLabel,
    leadActionAllowed,
    modeLabel,
  };
}
