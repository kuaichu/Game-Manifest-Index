import { type ComputedRef, type Ref, computed, ref, watch } from "vue";
import { ApiError, adminApi } from "../api";
import { manualVersionSavedMessage } from "../admin-ui-capabilities";
import {
  type EditableArtifactDraft,
  type VersionDraft,
  buildVisualArtifactAttributes,
  defaultCreateDraft,
  normalizeArtifactUrls,
} from "../admin-version-editor";
import type { ManualArtifactPayload, VersionSummary } from "../types";
import type { AdminShell } from "./admin-shell";

export interface AdminVersionCreateDeps {
  versions: Ref<VersionSummary[]>;
  selectedVersion: Ref<string>;
  contentSubTab: Ref<"edit" | "create">;
  editableLoaded: Ref<boolean>;
  editableDraft: Ref<VersionDraft>;
  selectedDomainGameName: ComputedRef<string>;
  selectedDomainSupportsCreateVersion: ComputedRef<boolean>;
  selectedDomainSupportsManualVersion: ComputedRef<boolean>;
  loadEditableVersion: (domainId?: string, version?: string) => Promise<void>;
}

export function useAdminVersionCreate(shell: AdminShell, deps: AdminVersionCreateDeps) {
  const { token, error, success, selectedDomainId, askConfirm, withLoading } = shell;
  const {
    versions,
    selectedVersion,
    contentSubTab,
    editableLoaded,
    editableDraft,
    selectedDomainGameName,
    selectedDomainSupportsCreateVersion,
    selectedDomainSupportsManualVersion,
    loadEditableVersion,
  } = deps;

  watch(
    () => selectedDomainSupportsCreateVersion.value,
    (supportsCreate) => {
      if (!supportsCreate && contentSubTab.value === "create") {
        contentSubTab.value = "edit";
      }
    },
  );

  const createDraft = ref<VersionDraft>(defaultCreateDraft());

  const isCreateMode = computed(() => contentSubTab.value === "create");

  const versionDraft = computed(() => (isCreateMode.value ? createDraft.value : editableDraft.value));

  function copyCurrentVersionToCreateDraft(): void {
    if (!editableLoaded.value) {
      error.value = "当前没有加载有效的版本数据供复制。";
      return;
    }
    const clonedArtifacts: EditableArtifactDraft[] = editableDraft.value.artifacts.map((art) => ({
      kind: "apk",
      name: art.name,
      part: 1,
      size: art.size,
      component: art.component,
      package_type: "",
      delivery_mode: "",
      language: art.language,
      route_from: "",
      route_to: "",
      decompressed_size: art.decompressed_size,
      manifestJson: "",
      sourceJson: "",
      checksum_type: art.checksum_type,
      checksum_value: art.checksum_value,
      attributesJson: art.attributesJson,
      urls: art.urls.map((u) => ({
        url: u.url,
        priority: u.priority,
        source_kind: u.source_kind,
      })),
    }));

    createDraft.value = {
      version: "",
      channel: editableDraft.value.channel,
      version_code: editableDraft.value.version_code,
      file_created_at_override: editableDraft.value.file_created_at_override || "",
      is_visible: editableDraft.value.is_visible,
      checksum_etag: editableDraft.value.checksum_etag,
      checksum_crc64: editableDraft.value.checksum_crc64,
      checksum_md5: editableDraft.value.checksum_md5,
      artifacts: clonedArtifacts,
      artifactsJson: editableDraft.value.artifactsJson,
      artifactsMode: "visual",
    };
    contentSubTab.value = "create";
    success.value = `已成功复制版本 ${selectedVersion.value} 的配置模板！请输入新版本号。`;
  }

  function resetCreateDraft(): void {
    createDraft.value = defaultCreateDraft();
    success.value = "新版本录入表单已重置为空白模板。";
  }

  function buildCreateArtifactsPayload(): ManualArtifactPayload[] {
    if (createDraft.value.artifactsMode === "json") {
      try {
        const parsed = JSON.parse(createDraft.value.artifactsJson || "[]");
        if (!Array.isArray(parsed)) throw new Error("Artifacts JSON 必须是数组");
        return parsed;
      } catch (err) {
        throw new Error(err instanceof Error ? `Artifacts JSON 格式错误: ${err.message}` : "Artifacts JSON 无效");
      }
    }
    return createDraft.value.artifacts.map((art) => {
      return {
        kind: art.kind,
        name: art.name.trim(),
        part: art.part,
        size: Number(art.size) || 0,
        checksum_type: art.checksum_type.trim() || undefined,
        checksum_value: art.checksum_value.trim().toLowerCase() || undefined,
        attributes: buildVisualArtifactAttributes(art),
        urls: normalizeArtifactUrls(art.urls, true, false, (value) => Number(value) || 0),
      };
    });
  }

  async function addVersion(): Promise<void> {
    if (!selectedDomainSupportsManualVersion.value) {
      error.value = "当前手工录入只支持单 APK 的 Android 版本；PC 版本请通过官方采集流程维护。";
      return;
    }
    const ver = createDraft.value.version.trim();
    if (!selectedDomainId.value || !ver) {
      error.value = "请输入新版本的版本号";
      return;
    }

    let artifactsPayload: ManualArtifactPayload[];
    try {
      artifactsPayload = buildCreateArtifactsPayload();
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Artifacts 配置无效";
      return;
    }

    if (artifactsPayload.length !== 1) {
      error.value = "Android 架构只允许包含一个 APK 资源文件 (Artifact)";
      return;
    }
    const mainArt = artifactsPayload[0];
    if (mainArt.kind !== "apk") {
      error.value = "资源文件类型 (kind) 必须为 apk";
      return;
    }
    if (!mainArt.name.trim()) {
      error.value = "APK 文件名不能为空";
      return;
    }
    if (!mainArt.name.trim().toLowerCase().endsWith(".apk")) {
      error.value = "文件名必须以 .apk 结尾";
      return;
    }
    if (mainArt.urls.length !== 1) {
      error.value = "每个版本必须且仅允许包含一条下载链接 (URL)";
      return;
    }
    const firstUrl = mainArt.urls[0].url.trim();
    if (!firstUrl.startsWith("http://") && !firstUrl.startsWith("https://")) {
      error.value = "下载链接 URL 必须使用 http:// 或 https:// 协议";
      return;
    }

    // 注入校验值
    const artAttrs = (mainArt.attributes || {}) as Record<string, unknown>;
    if (createDraft.value.checksum_etag?.trim()) {
      artAttrs.etag = createDraft.value.checksum_etag.trim();
    }
    if (createDraft.value.checksum_crc64?.trim()) {
      artAttrs.crc64 = createDraft.value.checksum_crc64.trim();
    }
    if (createDraft.value.checksum_md5?.trim()) {
      artAttrs.md5 = createDraft.value.checksum_md5.trim();
    }
    mainArt.attributes = artAttrs;

    const attributes: Record<string, unknown> = {
      channel: createDraft.value.channel.trim() || "official",
      version_code:
        createDraft.value.version_code !== null &&
        createDraft.value.version_code !== undefined &&
        String(createDraft.value.version_code).trim() !== ""
          ? Number(createDraft.value.version_code)
          : null,
    };
    if (createDraft.value.file_created_at_override?.trim()) {
      attributes.file_created_at = createDraft.value.file_created_at_override.trim();
    }

    const confirmed = await askConfirm(
      `确定要为【${selectedDomainGameName.value || selectedDomainId.value}】录入新版本【${ver}】吗？`,
      { title: "录入新版本", confirmLabel: "录入" },
    );
    if (!confirmed) return;

    await withLoading(async (signal) => {
      try {
        const result = await adminApi.addVersion(
          selectedDomainId.value,
          {
            version: ver,
            client_version: ver,
            file_path: mainArt.name.trim(),
            attributes,
            artifacts: [mainArt],
          },
          token.value,
          signal,
        );

        if (!createDraft.value.is_visible) {
          await adminApi.setVersionVisibility(
            selectedDomainId.value,
            ver,
            false,
            token.value,
            signal,
          );
        }

        const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
        versions.value = verRes.items;
        selectedVersion.value = ver;
        await loadEditableVersion(selectedDomainId.value, ver);
        contentSubTab.value = "edit";
        createDraft.value = defaultCreateDraft();

        success.value = manualVersionSavedMessage(ver, result.probe_error);
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          error.value = `版本【${ver}】已存在，请勿重复新增 (HTTP 409)。`;
          return;
        }
        throw err;
      }
    });
  }

  return {
    createDraft,
    isCreateMode,
    versionDraft,
    buildCreateArtifactsPayload,
    addVersion,
    copyCurrentVersionToCreateDraft,
    resetCreateDraft,
  };
}

export type AdminVersionCreateState = ReturnType<typeof useAdminVersionCreate>;
