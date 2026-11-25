import { type ComputedRef, type Ref, ref } from "vue";
import { adminApi } from "../api";
import { formatBytes } from "../admin-format";
import {
  type EditableArtifactDraft,
  type VersionDraft,
  applyArtifactFilenameFromUrl,
  artifactDraftFromPayload,
  buildVisualArtifactAttributes,
  normalizeArtifactUrls,
  parseArtifactsJsonPayload,
} from "../admin-version-editor";
import type { ManualArtifactPayload, ProbeUrlResult } from "../types";
import type { AdminShell } from "./admin-shell";

export interface AdminArtifactDraftsDeps {
  editableDraft: Ref<VersionDraft>;
  createDraft: Ref<VersionDraft>;
  isCreateMode: ComputedRef<boolean>;
  selectedDomainUsesPcEditor: ComputedRef<boolean>;
  buildCreateArtifactsPayload: () => ManualArtifactPayload[];
}

export function buildEditableArtifactsPayload(draft: VersionDraft): ManualArtifactPayload[] {
  if (draft.artifactsMode === "json") {
    return parseArtifactsJsonPayload(draft.artifactsJson);
  }

  return draft.artifacts.map((art, idx) => {
    return {
      artifact_id: art.artifact_id,
      kind: art.kind.trim() || "file",
      name: art.name.trim() || `part_${idx + 1}`,
      part: Number(art.part) || idx + 1,
      size: Number(art.size) || 0,
      checksum_type: art.checksum_type.trim() || null,
      checksum_value: art.checksum_value.trim().toLowerCase() || null,
      attributes: buildVisualArtifactAttributes(art),
      urls: normalizeArtifactUrls(art.urls, true),
    };
  });
}

export function useAdminArtifactDrafts(shell: AdminShell, deps: AdminArtifactDraftsDeps) {
  const { token, error, success } = shell;
  const {
    editableDraft,
    createDraft,
    isCreateMode,
    selectedDomainUsesPcEditor,
    buildCreateArtifactsPayload,
  } = deps;

  function buildArtifactsPayload(): ManualArtifactPayload[] {
    return buildEditableArtifactsPayload(editableDraft.value);
  }

  function addArtifactItem(): void {
    const nextPart = editableDraft.value.artifacts.reduce((max, a) => Math.max(max, a.part), 0) + 1;
    editableDraft.value.artifacts.push({
      kind: selectedDomainUsesPcEditor.value ? "package" : "file",
      name: "",
      part: nextPart,
      size: 0,
      component: "game",
      package_type: selectedDomainUsesPcEditor.value ? "segment" : "",
      delivery_mode: selectedDomainUsesPcEditor.value ? "direct" : "",
      language: "",
      route_from: "",
      route_to: "",
      decompressed_size: null,
      manifestJson: "",
      sourceJson: "",
      checksum_type: "",
      checksum_value: "",
      attributesJson: "{}",
      urls: [{ url: "", priority: 0, source_kind: "official" }],
    });
    syncArtifactsToJson();
  }

  function removeArtifactItem(index: number): void {
    if (editableDraft.value.artifacts.length <= 1) {
      error.value = "版本必须包含至少一个资源文件 (Artifact)。";
      return;
    }
    editableDraft.value.artifacts.splice(index, 1);
    syncArtifactsToJson();
  }

  function addArtifactUrlItem(artifactIndex: number): void {
    const art = editableDraft.value.artifacts[artifactIndex];
    if (!art) return;
    const nextPriority = art.urls.length;
    art.urls.push({ url: "", priority: nextPriority, source_kind: "official" });
    syncArtifactsToJson();
  }

  function removeArtifactUrlItem(artifactIndex: number, urlIndex: number): void {
    const art = editableDraft.value.artifacts[artifactIndex];
    if (!art) return;
    art.urls.splice(urlIndex, 1);
    syncArtifactsToJson();
  }

  function handleArtifactUrlChange(art: EditableArtifactDraft, newUrl: string): void {
    applyArtifactFilenameFromUrl(art, newUrl);
    syncArtifactsToJson();
  }

  function forceExtractArtifactName(art: EditableArtifactDraft): void {
    const firstUrl = art.urls.find((u) => u.url.trim())?.url || "";
    if (applyArtifactFilenameFromUrl(art, firstUrl, true)) syncArtifactsToJson();
  }

  function switchArtifactsMode(mode: "visual" | "json"): void {
    if (mode === "json") {
      syncArtifactsToJson();
      editableDraft.value.artifactsMode = "json";
    } else {
      try {
        const parsed = JSON.parse(editableDraft.value.artifactsJson || "[]");
        if (!Array.isArray(parsed)) throw new Error("Artifacts JSON 必须是数组");
        editableDraft.value.artifacts = parsed.map(artifactDraftFromPayload);
        editableDraft.value.artifactsMode = "visual";
      } catch (err) {
        error.value = err instanceof Error ? `切换失败: ${err.message}` : "JSON 解析失败";
      }
    }
  }

  function syncArtifactsToJson(): void {
    try {
      const payload = buildArtifactsPayload();
      editableDraft.value.artifactsJson = JSON.stringify(payload, null, 2);
    } catch {
      // Keep the visual form editable while a nested JSON field is temporarily invalid.
    }
  }

  function formatArtifactsJson(): void {
    try {
      const parsed = JSON.parse(editableDraft.value.artifactsJson || "[]");
      editableDraft.value.artifactsJson = JSON.stringify(parsed, null, 2);
    } catch (err) {
      error.value = err instanceof Error ? `JSON 格式错误: ${err.message}` : "JSON 格式无效";
    }
  }

  const urlProbeMap = ref<Record<string, { loading: boolean; result?: ProbeUrlResult }>>({});

  async function probeUrlItem(target: EditableArtifactDraft["urls"][number] | string): Promise<void> {
    const urlItem = typeof target === "string" ? { url: target, priority: 0, source_kind: "official" } : target;
    const cleanUrl = urlItem.url.trim();
    if (!cleanUrl) {
      error.value = "请先输入有效的 URL 地址";
      return;
    }
    if (!cleanUrl.startsWith("http://") && !cleanUrl.startsWith("https://")) {
      error.value = "URL 必须以 http:// 或 https:// 开头";
      return;
    }
    urlProbeMap.value[cleanUrl] = { loading: true };
    try {
      const artifactUrlId = "id" in urlItem && urlItem.id && cleanUrl === urlItem.persisted_url ? urlItem.id : undefined;
      const res = await adminApi.probeUrl(cleanUrl, token.value, 10, artifactUrlId);
      urlProbeMap.value[cleanUrl] = { loading: false, result: res };
      if (res.ok) {
        const persistence = res.persisted ? "，结果已同步到下载区" : "；当前链接尚未保存，本次仅临时检测";
        success.value = `URL 验活成功：HTTP ${res.status || 200}${res.size ? ` (${formatBytes(res.size)})` : ""}${persistence}`;
      } else {
        error.value = `URL 验活异常：${res.error || res.reason || `HTTP ${res.status || "失败"}`}`;
      }
    } catch (err) {
      urlProbeMap.value[cleanUrl] = {
        loading: false,
        result: { url: cleanUrl, ok: false, error: err instanceof Error ? err.message : "请求失败" },
      };
      error.value = `URL 验活请求出错: ${err instanceof Error ? err.message : "未知错误"}`;
    }
  }

  function syncArtifactsJsonForActiveDraft(): void {
    if (isCreateMode.value) {
      createDraft.value.artifactsJson = JSON.stringify(buildCreateArtifactsPayload(), null, 2);
      return;
    }
    syncArtifactsToJson();
  }

  function handleActiveArtifactUrlChange(art: EditableArtifactDraft, newUrl: string): void {
    applyArtifactFilenameFromUrl(art, newUrl);
    syncArtifactsJsonForActiveDraft();
  }

  function forceExtractActiveArtifactName(art: EditableArtifactDraft): void {
    const firstUrl = art.urls.find((u) => u.url.trim())?.url || "";
    if (applyArtifactFilenameFromUrl(art, firstUrl, true)) syncArtifactsJsonForActiveDraft();
  }

  return {
    urlProbeMap,
    buildArtifactsPayload,
    addArtifactItem,
    removeArtifactItem,
    addArtifactUrlItem,
    removeArtifactUrlItem,
    handleArtifactUrlChange,
    forceExtractArtifactName,
    switchArtifactsMode,
    syncArtifactsToJson,
    formatArtifactsJson,
    probeUrlItem,
    syncArtifactsJsonForActiveDraft,
    handleActiveArtifactUrlChange,
    forceExtractActiveArtifactName,
  };
}

export type AdminArtifactDraftsState = ReturnType<typeof useAdminArtifactDrafts>;
