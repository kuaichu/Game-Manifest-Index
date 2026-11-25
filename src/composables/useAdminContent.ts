import { computed, ref } from "vue";
import { ApiError, adminApi } from "../api";
import { supportsApkVersionEditor } from "../admin-ui-capabilities";
import { formatFileTimeLabel, isoToLocalInput, localInputToIso } from "../admin-date-time";
import { copyTextToClipboard } from "../clipboard";
import {
  type EditableArtifactDraft,
  type VersionDraft,
  artifactDraftFromPayload,
  isVersionUnavailable,
  isVersionUnknown,
  normalizeArtifactsForComparison,
  supportsPcVersionEditor,
  validatePcArtifacts,
} from "../admin-version-editor";
import type {
  AdminEditableVersionPayload,
  ManualArtifactPayload,
  VersionSummary,
} from "../types";
import type { AdminShell } from "./admin-shell";
import { buildEditableArtifactsPayload, useAdminArtifactDrafts } from "./useAdminArtifactDrafts";
import { useAdminVersionCreate } from "./useAdminVersionCreate";
import { useAdminVersionList } from "./useAdminVersionList";
import type { AvailabilityInvalidation } from "./useAvailabilityInvalidation";

export interface AdminContentDeps {
  stopProbePolling: () => void;
  availability: AvailabilityInvalidation;
}

export function useAdminContent(shell: AdminShell, deps: AdminContentDeps) {
  const {
    token,
    catalog,
    tab,
    error,
    success,
    selectedDomainId,
    askConfirm,
    withLoading,
    showError,
    selectDomain,
  } = shell;
  const { stopProbePolling } = deps;
  const { notifyAvailabilityInvalidated, nextVersionProbeInvalidationId } = deps.availability;

  const versions = ref<VersionSummary[]>([]);
  const selectedVersion = ref("");

  const contentSubTab = ref<"edit" | "create">("edit");
  const editableLoaded = ref(false);
  const editableLoading = ref(false);
  const originalEditableJson = ref("");
  const checksumsOpen = ref(false);
  const moreActionsOpen = ref(false);

  const editableDraft = ref<VersionDraft>({
    version: "",
    channel: "official",
    version_code: null as number | null,
    is_visible: true,
    file_created_at_override: "",
    checksum_etag: "",
    checksum_crc64: "",
    checksum_md5: "",
    artifacts: [] as EditableArtifactDraft[],
    artifactsJson: "[]",
    artifactsMode: "visual" as "visual" | "json",
  });

  const isEditableDirty = computed(() => {
    if (!editableLoaded.value) return false;
    let currentArtifactsStr = "";
    try {
      currentArtifactsStr = normalizeArtifactsForComparison(buildEditableArtifactsPayload(editableDraft.value));
    } catch {
      return true;
    }
    const current = JSON.stringify({
      channel: editableDraft.value.channel.trim(),
      version_code: editableDraft.value.version_code,
      is_visible: editableDraft.value.is_visible,
      file_created_at_override: editableDraft.value.file_created_at_override.trim(),
      checksum_etag: editableDraft.value.checksum_etag.trim(),
      checksum_crc64: editableDraft.value.checksum_crc64.trim(),
      checksum_md5: editableDraft.value.checksum_md5.trim(),
      artifacts: currentArtifactsStr,
    });
    return current !== originalEditableJson.value;
  });

  const versionList = useAdminVersionList(shell, {
    versions,
    selectedVersion,
    isEditableDirty,
    openContent,
    loadEditableVersion,
  });

  const {
    selectedDomain,
    selectedDomainGameName,
    ensureVersionExpanded,
    scrollToActiveVersion,
  } = versionList;

  const selectedDomainSupportsCreateVersion = computed(() =>
    supportsApkVersionEditor(selectedDomain.value?.platform),
  );

  const selectedDomainUsesPcEditor = computed(() =>
    supportsPcVersionEditor(selectedDomain.value),
  );

  const selectedDomainSupportsManualVersion = computed(() =>
    selectedDomainSupportsCreateVersion.value || selectedDomainUsesPcEditor.value,
  );

  const {
    createDraft,
    isCreateMode,
    versionDraft,
    buildCreateArtifactsPayload,
    addVersion,
    copyCurrentVersionToCreateDraft,
    resetCreateDraft,
  } = useAdminVersionCreate(shell, {
    versions,
    selectedVersion,
    contentSubTab,
    editableLoaded,
    editableDraft,
    selectedDomainGameName,
    selectedDomainSupportsCreateVersion,
    selectedDomainSupportsManualVersion,
    loadEditableVersion,
  });

  const {
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
  } = useAdminArtifactDrafts(shell, {
    editableDraft,
    createDraft,
    isCreateMode,
    selectedDomainUsesPcEditor,
    buildCreateArtifactsPayload,
  });

  const currentVersionItem = computed(() =>
    versions.value.find((v) => v.version === selectedVersion.value) || null,
  );

  const currentVersionHealth = computed(() => {
    const summary = currentVersionItem.value;
    if (summary) {
      if (isVersionUnavailable(summary)) {
        return {
          isChecked: true,
          isOk: false,
          httpCode: null as number | null,
          available: false,
          lastCheckedAt: null as string | null,
          size: summary.packed_size || 0,
        };
      }
      if (!isVersionUnknown(summary)) {
        return {
          isChecked: true,
          isOk: true,
          httpCode: null as number | null,
          available: true,
          lastCheckedAt: null as string | null,
          size: summary.packed_size || 0,
        };
      }
    }

    const art = editableDraft.value.artifacts[0];
    let attr: Record<string, any> = {};
    if (art?.attributesJson) {
      try {
        attr = JSON.parse(art.attributesJson || "{}");
      } catch {
        // ignore
      }
    }
    const httpCode = attr.http_code !== undefined && attr.http_code !== null ? Number(attr.http_code) : null;
    const available = attr.available === true;
    const lastCheckedAt = attr.last_checked_at || null;
    const size = art?.size || 0;

    const isChecked = httpCode !== null || lastCheckedAt !== null;
    const isOk = available || (httpCode !== null && httpCode >= 200 && httpCode < 400);

    return {
      isChecked,
      isOk,
      httpCode,
      available,
      lastCheckedAt,
      size,
    };
  });

  const pcArtifactsOverview = computed(() => {
    const artifacts = editableDraft.value.artifacts || [];
    const packageCount = artifacts.filter((item) => item.kind === "package").length;
    const patchCount = artifacts.filter((item) => item.kind === "patch").length;
    const urlCount = artifacts.reduce((total, item) =>
      total + (item.urls || []).filter((urlItem) => urlItem.url.trim()).length, 0);
    const totalSize = artifacts.reduce((total, item) => total + (Number(item.size) || 0), 0);
    return {
      total: artifacts.length,
      packageCount,
      patchCount,
      urlCount,
      totalSize,
    };
  });

  const isUrlChanged = computed(() => {
    if (!editableLoaded.value || !editableDraft.value.artifacts.length) return false;
    const currentUrl = editableDraft.value.artifacts[0]?.urls[0]?.url?.trim() || "";
    const initialUrl = editableDraft.value.artifacts[0]?.urls[0]?.persisted_url?.trim() || "";
    return initialUrl !== "" && currentUrl !== initialUrl;
  });

  const dirtyChangesCount = computed(() => {
    if (!editableLoaded.value) return 0;
    let count = 0;
    let original: any = {};
    try {
      original = JSON.parse(originalEditableJson.value || "{}");
    } catch {
      return 0;
    }

    if (editableDraft.value.channel.trim() !== (original.channel || "").trim()) count++;
    if (Number(editableDraft.value.version_code || 0) !== Number(original.version_code || 0)) count++;
    if (editableDraft.value.is_visible !== original.is_visible) count++;
    if (editableDraft.value.file_created_at_override.trim() !== (original.file_created_at_override || "").trim()) count++;
    if (editableDraft.value.checksum_etag.trim() !== (original.checksum_etag || "").trim()) count++;
    if (editableDraft.value.checksum_crc64.trim() !== (original.checksum_crc64 || "").trim()) count++;
    if (editableDraft.value.checksum_md5.trim() !== (original.checksum_md5 || "").trim()) count++;

    let currentArtifacts = "";
    try {
      currentArtifacts = normalizeArtifactsForComparison(buildArtifactsPayload());
    } catch {
      count++;
      return count;
    }
    if (currentArtifacts !== (original.artifacts || "")) count++;

    return count;
  });

  function clearActiveFileTime(): void {
    versionDraft.value.file_created_at_override = "";
  }

  async function copyUrl(url: string): Promise<void> {
    if (!url) return;
    if (await copyTextToClipboard(url)) {
      success.value = "下载链接已成功复制到剪贴板！";
    } else {
      error.value = "复制链接失败，请手动选择复制。";
    }
  }

  function openUrl(url: string): void {
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  const showApkFileCard = computed(
    () => Boolean(versionDraft.value.artifacts[0]) && (isCreateMode.value || selectedDomainSupportsCreateVersion.value),
  );

  const fileTimeRaw = computed(() => versionDraft.value.file_created_at_override.trim());

  const fileTimeInputValue = computed(() => isoToLocalInput(fileTimeRaw.value));

  const fileTimeLabel = computed(() => formatFileTimeLabel(fileTimeRaw.value));

  const fileTimeUnparsable = computed(() => Boolean(fileTimeRaw.value) && !fileTimeLabel.value);

  function onFileTimeInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    versionDraft.value.file_created_at_override = localInputToIso(input.value);
  }

  async function submitVersionForm(): Promise<void> {
    if (isCreateMode.value) {
      await addVersion();
      return;
    }
    await saveEditableVersion();
  }

  function preventEnterSubmit(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    if (target && target.tagName === "INPUT") {
      event.preventDefault();
    }
  }

  async function loadEditableVersion(domainId = selectedDomainId.value, version = selectedVersion.value): Promise<void> {
    const domain = catalog.value.domains.find((item) => item.id === domainId);
    const isAndroid = supportsApkVersionEditor(domain?.platform);
    const isPc = supportsPcVersionEditor(domain);
    if (!isAndroid && !isPc) {
      editableLoaded.value = false;
      return;
    }
    if (!domainId || !version) {
      editableLoaded.value = false;
      return;
    }
    editableLoading.value = true;
    try {
      const data = await adminApi.editableVersion(domainId, version, token.value.trim());
      const editableArtifactsPayload = (data.artifacts || []).map((art) => ({
        artifact_id: art.artifact_id,
        kind: art.kind || "file",
        name: art.name || "",
        part: art.part,
        size: art.size,
        checksum_type: art.checksum_type,
        checksum_value: art.checksum_value,
        attributes: (art.attributes || {}) as Record<string, unknown>,
        urls: (art.urls || []).map((u) => ({
          url: u.url || "",
          priority: u.priority ?? 0,
          source_kind: u.source_kind || "official",
        })),
      }));
      const rawArtifacts = (data.artifacts || []).map((art, idx) => artifactDraftFromPayload({
        artifact_id: art.artifact_id,
        kind: art.kind || "file",
        name: art.name || "",
        part: art.part ?? (idx + 1),
        size: art.size ?? 0,
        checksum_type: art.checksum_type || "",
        checksum_value: art.checksum_value || "",
        attributes: art.attributes || {},
        urls: art.urls || [],
      }, idx));

      const attrs = (data.attributes || {}) as Record<string, any>;
      const firstArt = rawArtifacts[0];
      let artAttrs: Record<string, any> = {};
      if (firstArt?.attributesJson) {
        try {
          artAttrs = JSON.parse(firstArt.attributesJson || "{}");
        } catch {
          // ignore
        }
      }

      editableDraft.value = {
        version: "",
        channel: typeof attrs.channel === "string" ? attrs.channel : "official",
        version_code: typeof attrs.version_code === "number" ? attrs.version_code : null,
        is_visible: data.is_visible ?? true,
        file_created_at_override: data.file_created_at_override || "",
        checksum_etag: String(artAttrs.etag || ""),
        checksum_crc64: String(artAttrs.crc64 || (firstArt?.checksum_type === "crc64" ? firstArt.checksum_value : "")),
        checksum_md5: String(artAttrs.md5 || (firstArt?.checksum_type === "md5" ? firstArt.checksum_value : "")),
        artifacts: rawArtifacts,
        artifactsJson: JSON.stringify(editableArtifactsPayload, null, 2),
        artifactsMode: "visual",
      };

      // 用草稿回写后的形态作为基线：视觉编辑器会补默认属性、清理空值，
      // 直接拿接口原始 payload 当基线会让表单一打开就显示“未保存修改”。
      let initialArtifactsStr = "";
      try {
        initialArtifactsStr = normalizeArtifactsForComparison(buildArtifactsPayload());
      } catch {
        initialArtifactsStr = normalizeArtifactsForComparison(editableArtifactsPayload);
      }

      originalEditableJson.value = JSON.stringify({
        channel: editableDraft.value.channel.trim(),
        version_code: editableDraft.value.version_code,
        is_visible: editableDraft.value.is_visible,
        file_created_at_override: editableDraft.value.file_created_at_override.trim(),
        checksum_etag: editableDraft.value.checksum_etag.trim(),
        checksum_crc64: editableDraft.value.checksum_crc64.trim(),
        checksum_md5: editableDraft.value.checksum_md5.trim(),
        artifacts: initialArtifactsStr,
      });
      editableLoaded.value = true;
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        showError(reason);
      }
    } finally {
      editableLoading.value = false;
    }
  }

  async function onContentVersionSelect(version: string): Promise<void> {
    if (selectedVersion.value === version) return;
    if (isEditableDirty.value) {
      const confirmed = await askConfirm(
        `当前版本 (${selectedVersion.value}) 存在未保存的变更。\n切换到版本 ${version} 将丢弃未保存的修改，是否确定继续？`,
      );
      if (!confirmed) return;
    }
    selectedVersion.value = version;
    ensureVersionExpanded(version);
    await loadEditableVersion(selectedDomainId.value, version);
    scrollToActiveVersion();
  }

  async function discardChanges(): Promise<void> {
    if (!(await askConfirm("确定要放弃所有未保存的修改并还原为当前服务端配置吗？", {
      title: "放弃未保存的修改",
      confirmLabel: "放弃修改",
    })))
      return;
    await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
    success.value = "已放弃修改，表单已还原。";
  }

  async function saveEditableVersion(): Promise<void> {
    if (!selectedDomainSupportsManualVersion.value) {
      error.value = "当前模块暂不支持手工编辑。";
      return;
    }
    if (!selectedDomainId.value || !selectedVersion.value || !isEditableDirty.value) return;

    let artifactsPayload: ManualArtifactPayload[];
    try {
      artifactsPayload = buildArtifactsPayload();
    } catch (err) {
      error.value = err instanceof Error ? `Artifacts JSON 格式错误: ${err.message}` : "Artifacts 配置无效";
      return;
    }
    if (!artifactsPayload.length) {
      error.value = "Artifacts 至少需要包含一个资源文件";
      return;
    }

    const payload: AdminEditableVersionPayload = {
      attributes: {
        channel: editableDraft.value.channel.trim() || "official",
        version_code:
          editableDraft.value.version_code !== null &&
          editableDraft.value.version_code !== undefined &&
          String(editableDraft.value.version_code).trim() !== ""
            ? Number(editableDraft.value.version_code)
            : null,
      },
      artifacts: artifactsPayload,
    };

    const willProbe = selectedDomainSupportsCreateVersion.value && isUrlChanged.value;
    if (selectedDomainSupportsCreateVersion.value) {
      if (artifactsPayload.length !== 1) {
        error.value = "只允许包含一个 APK 文件";
        return;
      }
      const mainArt = artifactsPayload[0];
      mainArt.kind = "apk";
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

      const artAttrs = (mainArt.attributes || {}) as Record<string, unknown>;
      if (editableDraft.value.checksum_etag?.trim()) {
        artAttrs.etag = editableDraft.value.checksum_etag.trim();
      }
      if (editableDraft.value.checksum_crc64?.trim()) {
        artAttrs.crc64 = editableDraft.value.checksum_crc64.trim();
      }
      if (editableDraft.value.checksum_md5?.trim()) {
        artAttrs.md5 = editableDraft.value.checksum_md5.trim();
      }
      mainArt.attributes = artAttrs;
      payload.file_created_at_override = editableDraft.value.file_created_at_override.trim() || null;
      payload.file_path = mainArt.name.trim();
      payload.artifacts = [mainArt];
    } else if (selectedDomainUsesPcEditor.value) {
      try {
        validatePcArtifacts(artifactsPayload);
      } catch (err) {
        error.value = err instanceof Error ? err.message : "PC artifact 配置无效";
        return;
      }
      payload.file_created_at_override = editableDraft.value.file_created_at_override.trim() || null;
    }

    const actionPrompt = willProbe
      ? `确定要保存对版本【${selectedVersion.value}】的修改并立即向官方源探活吗？`
      : `确定要保存对版本【${selectedVersion.value}】的修改吗？`;
    const confirmed = await askConfirm(actionPrompt, {
      title: "保存版本修改",
      confirmLabel: willProbe ? "保存并探活" : "保存",
    });
    if (!confirmed) return;

    await withLoading(async (signal) => {
      await adminApi.updateEditableVersion(
        selectedDomainId.value,
        selectedVersion.value,
        payload,
        token.value,
        signal,
      );

      // 如果可见性发生变动，同步更新
      if (currentVersionItem.value && currentVersionItem.value.is_visible !== editableDraft.value.is_visible) {
        await adminApi.setVersionVisibility(
          selectedDomainId.value,
          selectedVersion.value,
          editableDraft.value.is_visible,
          token.value,
          signal,
        );
      }

      let probeCompleted = false;
      if (willProbe) {
        try {
          await adminApi.probeVersion(selectedDomainId.value, selectedVersion.value, token.value, signal);
          probeCompleted = true;
          notifyAvailabilityInvalidated(nextVersionProbeInvalidationId(selectedDomainId.value, selectedVersion.value));
        } catch {
          // 探活失败不阻塞保存
        }
      }

      const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
      versions.value = verRes.items;
      await loadEditableVersion(selectedDomainId.value, selectedVersion.value);
      success.value = willProbe
        ? probeCompleted
          ? `版本 ${selectedVersion.value} 修改已保存并已完成探活！`
          : `版本 ${selectedVersion.value} 修改已保存，但探活失败，请重试。`
        : `版本 ${selectedVersion.value} 的配置修改已保存成功。`;
    });
  }

  async function openContent(id = selectedDomainId.value): Promise<void> {
    selectedDomainId.value = id;
    selectDomain(id);
    tab.value = "content";
    stopProbePolling();
    await withLoading(async (signal) => {
      const response = await adminApi.versions(id, token.value, signal);
      versions.value = response.items;
      selectedVersion.value = versions.value[0]?.version || "";
      if (selectedVersion.value) {
        await loadEditableVersion(id, selectedVersion.value);
      } else {
        editableLoaded.value = false;
      }
    });
  }

  async function toggleVersionVisibility(): Promise<void> {
    const current = currentVersionItem.value;
    if (!selectedDomainId.value || !selectedVersion.value || !current) return;
    const actionText = current.is_visible ? "隐藏" : "公开";
    if (
      !(await askConfirm(`确定要将版本【${selectedVersion.value}】切换为【${actionText}】状态吗？`, {
        title: "切换版本可见性",
        confirmLabel: actionText,
      }))
    )
      return;

    await withLoading(async (signal) => {
      await adminApi.setVersionVisibility(
        selectedDomainId.value,
        selectedVersion.value,
        !current.is_visible,
        token.value,
        signal,
      );
      const response = await adminApi.versions(selectedDomainId.value, token.value, signal);
      versions.value = response.items;
      success.value = current.is_visible ? "版本已切换为隐藏状态。" : "版本已切换为公开状态。";
    });
  }

  async function deleteCurrentVersion(ver = selectedVersion.value): Promise<void> {
    if (!selectedDomainId.value || !ver) return;
    const confirmed = await askConfirm(
      `确定要彻底删除版本【${ver}】吗？\n\n此操作将永久清除该版本的所有 Revision 快照、资源文件及下载链接，不可撤销。`,
      { title: "删除版本", confirmLabel: "永久删除", tone: "danger" },
    );
    if (!confirmed) return;

    await withLoading(async (signal) => {
      await adminApi.deleteVersion(selectedDomainId.value, ver, token.value, signal);
      const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
      versions.value = verRes.items;

      const nextVer = versions.value.find((v) => v.version !== ver)?.version || versions.value[0]?.version || "";
      selectedVersion.value = nextVer;
      if (nextVer) {
        await loadEditableVersion(selectedDomainId.value, nextVer);
      } else {
        editableLoaded.value = false;
      }
      success.value = `版本 ${ver} 已成功永久删除。`;
    });
  }

  async function probeCurrentVersion(ver = selectedVersion.value): Promise<void> {
    if (!selectedDomainId.value || !ver) return;
    const confirmed = await askConfirm(
      `确定要向官方源发起对版本【${ver}】的实时探活并持久化保存吗？表单中未保存的修改不会被一并提交。`,
      { title: "实时探活", confirmLabel: "开始探活" },
    );
    if (!confirmed) return;

    await withLoading(async (signal) => {
      try {
        await adminApi.probeVersion(selectedDomainId.value, ver, token.value, signal);
        notifyAvailabilityInvalidated(nextVersionProbeInvalidationId(selectedDomainId.value, ver));
        const verRes = await adminApi.versions(selectedDomainId.value, token.value, signal);
        versions.value = verRes.items;
        await loadEditableVersion(selectedDomainId.value, ver);
        success.value = `版本【${ver}】已成功完成官方源探活并已持久化保存！`;
      } catch (err) {
        if (err instanceof ApiError && err.status === 502) {
          error.value = `探活失败 (HTTP 502)：网络探测异常，未能成功连接官方源。`;
          return;
        }
        throw err;
      }
    });
  }

  return {
    versionList,
    versions,
    contentSubTab,
    editableLoaded,
    editableLoading,
    checksumsOpen,
    moreActionsOpen,
    editableDraft,
    createDraft,
    versionDraft,
    isCreateMode,
    selectedDomainSupportsCreateVersion,
    selectedDomainUsesPcEditor,
    selectedDomainSupportsManualVersion,
    currentVersionHealth,
    pcArtifactsOverview,
    isUrlChanged,
    dirtyChangesCount,
    isEditableDirty,
    showApkFileCard,
    fileTimeRaw,
    fileTimeInputValue,
    fileTimeLabel,
    fileTimeUnparsable,
    urlProbeMap,
    clearActiveFileTime,
    copyUrl,
    openUrl,
    onFileTimeInput,
    submitVersionForm,
    preventEnterSubmit,
    addArtifactItem,
    removeArtifactItem,
    addArtifactUrlItem,
    removeArtifactUrlItem,
    handleArtifactUrlChange,
    forceExtractArtifactName,
    switchArtifactsMode,
    formatArtifactsJson,
    probeUrlItem,
    handleActiveArtifactUrlChange,
    forceExtractActiveArtifactName,
    syncArtifactsToJson,
    syncArtifactsJsonForActiveDraft,
    loadEditableVersion,
    onContentVersionSelect,
    discardChanges,
    openContent,
    toggleVersionVisibility,
    deleteCurrentVersion,
    copyCurrentVersionToCreateDraft,
    resetCreateDraft,
    probeCurrentVersion,
  };
}

export type AdminContent = ReturnType<typeof useAdminContent>;
