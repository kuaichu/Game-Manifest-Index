import { computed, type Ref } from "vue";
import { api } from "../api";
import { artifactDownloadUrl, rawArtifactUrl } from "../archive-artifact-helpers";
import { availabilityStatesForMode, preferredDomainArtifactAction } from "../domain-presentation";
import type { ArchiveDomain, Artifact, ChunkManifestDetail, VersionSummary } from "../types";

export interface ArchiveExportOptions {
  gameId: Ref<string>;
  domainId: Ref<string>;
  domain: Ref<ArchiveDomain | null>;
  selectedVersion: Ref<string>;
  selectedSummary: Ref<VersionSummary | null>;
  mode: Ref<string>;
  query: Ref<string>;
  searchableMode: Ref<boolean>;
  exportArtifactKind: Ref<string>;
  canExportArtifacts: Ref<boolean>;
  canExportUrls: Ref<boolean>;
  artifacts: Ref<Artifact[]>;
  chunkDetail: Ref<ChunkManifestDetail | null>;
  setToast: (message: string, durationMs?: number) => void;
}

function saveTextFile(filename: string, content: string, type: string): void {
  const href = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(href), 0);
}

export function useArchiveExport(options: ArchiveExportOptions) {
  const exportUrlsCount = computed(() => {
    const states = availabilityStatesForMode(options.selectedSummary.value, options.mode.value);
    return states.available ?? 0;
  });

  const exportUrlsLabel = computed(() => {
    if (options.mode.value === "chunks") {
      const count = options.chunkDetail.value?.manifests?.length || options.artifacts.value.length || 0;
      return count > 0 ? `导出 Manifest 链接 · ${count}` : "导出 Manifest 链接";
    }
    const count = exportUrlsCount.value;
    return count > 0 ? `导出可用 URL · ${count}` : "导出 URL";
  });

  async function exportArtifacts(format: "urls" | "json"): Promise<void> {
    if (!options.canExportArtifacts.value || (format === "urls" && !options.canExportUrls.value)) return;
    const exportController = new AbortController();
    const dom = options.domain.value;
    const gId = options.gameId.value;
    const dId = options.domainId.value;
    const ver = options.selectedVersion.value;
    const currentMode = options.mode.value;

    try {
      if (currentMode === "chunks") {
        const stem = `${gId}-${ver}-chunk-manifests`;
        if (format === "json") {
          const payload = options.chunkDetail.value || {
            domain_id: dId,
            version: ver,
            manifests: options.artifacts.value,
          };
          saveTextFile(`${stem}.json`, `${JSON.stringify(payload, null, 2)}\n`, "application/json;charset=utf-8");
          options.setToast("已生成 1 项 Chunk Manifest JSON", 2400);
        } else {
          const urls: string[] = [];
          if (options.chunkDetail.value?.manifests?.length) {
            for (const m of options.chunkDetail.value.manifests) {
              const prefix = m.manifest_download?.url_prefix || "";
              const id = m.manifest?.id || m.manifest_id || "";
              if (prefix && id) urls.push(`${prefix.replace(/\/+$/, "")}/${id}`);
            }
          } else {
            for (const art of options.artifacts.value) {
              const url = artifactDownloadUrl(dom, art)
                || preferredDomainArtifactAction(dom, art, "download")?.url
                || rawArtifactUrl(art);
              if (url) urls.push(url);
            }
          }
          saveTextFile(`${stem}.urls.txt`, `${urls.join("\n")}\n`, "text/plain;charset=utf-8");
          options.setToast(`已生成 ${urls.length} 项 Manifest URL 列表`, 2400);
        }
        return;
      }

      if (currentMode === "apk") {
        const record = await api.versionRecord(dId, ver, exportController.signal);
        const stem = `${gId}-${ver}-${currentMode}`;
        if (format === "json") {
          saveTextFile(`${stem}.json`, `${JSON.stringify(record, null, 2)}\n`, "application/json;charset=utf-8");
        } else {
          saveTextFile(`${stem}.urls.txt`, `${record.url}\n`, "text/plain;charset=utf-8");
        }
        options.setToast(`已生成 1 项${format === "json" ? " JSON" : " URL 列表"}`, 2400);
        return;
      }

      const rows = await api.allArtifacts(
        dId,
        ver,
        {
          kind: options.exportArtifactKind.value,
          query: options.searchableMode.value ? options.query.value.trim() : "",
        },
        exportController.signal,
      );
      const stem = `${gId}-${ver}-${currentMode}`;
      if (format === "json") {
        saveTextFile(`${stem}.json`, `${JSON.stringify(rows, null, 2)}\n`, "application/json;charset=utf-8");
      } else {
        const content = rows
          .map((item) => artifactDownloadUrl(dom, item) || preferredDomainArtifactAction(dom, item, "download")?.url || rawArtifactUrl(item))
          .filter((url): url is string => Boolean(url))
          .join("\n");
        saveTextFile(`${stem}.urls.txt`, `${content}\n`, "text/plain;charset=utf-8");
      }
      options.setToast(`已生成 ${rows.length} 项${format === "json" ? " JSON" : " 批量 URL 文件"}`, 2400);
    } catch (reason) {
      options.setToast(reason instanceof Error ? reason.message : "生成导出文件失败", 2400);
    }
  }

  return {
    exportUrlsCount,
    exportUrlsLabel,
    exportArtifacts,
  };
}
