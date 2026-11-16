import { computed, nextTick, ref, watch } from "vue";
import { ApiError, adminApi } from "../api";
import { supportsApkVersionEditor, manualVersionSavedMessage } from "../admin-ui-capabilities";
import { formatBytes } from "../admin-format";
import { formatFileTimeLabel, isoToLocalInput, localInputToIso } from "../admin-date-time";
import {
  type EditableArtifactDraft,
  type VersionDraft,
  type VersionGroupEntry,
  type VersionMajorGroup,
  applyArtifactFilenameFromUrl,
  artifactDraftFromPayload,
  buildVisualArtifactAttributes,
  compareVersionsDesc,
  defaultCreateDraft,
  isVersionAvailable,
  isVersionUnavailable,
  isVersionUnknown,
  normalizeArtifactUrls,
  normalizeArtifactsForComparison,
  parseArtifactsJsonPayload,
  parseVersionKey,
  supportsPcVersionEditor,
  validatePcArtifacts,
} from "../admin-version-editor";
import type {
  AdminEditableVersionPayload,
  ManualArtifactPayload,
  ProbeUrlResult,
  VersionSummary,
} from "../types";
import type { AdminShell } from "./admin-shell";
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
    selectedGameId,
    selectedDomainId,
    askConfirm,
    withLoading,
    showError,
    selectGame,
    selectDomain,
  } = shell;
  const { stopProbePolling } = deps;
  const { notifyAvailabilityInvalidated, nextVersionProbeInvalidationId } = deps.availability;

  const versionSearchQuery = ref("");
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

  const selectedDomainObj = computed(() =>
    catalog.value.domains.find((d) => d.id === selectedDomainId.value) || null,
  );

  const selectedDomainGameName = computed(() => {
    if (!selectedDomainObj.value) return "";
    const game = catalog.value.games.find((g) => g.id === selectedDomainObj.value?.game_id);
    return game?.name || selectedDomainObj.value.game_id;
  });

  const selectedDomainSupportsCreateVersion = computed(() =>
    supportsApkVersionEditor(selectedDomainObj.value?.platform),
  );

  const selectedDomainUsesPcEditor = computed(() =>
    supportsPcVersionEditor(selectedDomainObj.value),
  );

  const selectedDomainSupportsManualVersion = computed(() =>
    selectedDomainSupportsCreateVersion.value || selectedDomainUsesPcEditor.value,
  );

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
    try {
      await navigator.clipboard.writeText(url);
      success.value = "下载链接已成功复制到剪贴板！";
    } catch {
      error.value = "复制链接失败，请手动选择复制。";
    }
  }

  function openUrl(url: string): void {
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  function buildArtifactsPayload(): ManualArtifactPayload[] {
    if (editableDraft.value.artifactsMode === "json") {
      return parseArtifactsJsonPayload(editableDraft.value.artifactsJson);
    }

    return editableDraft.value.artifacts.map((art, idx) => {
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

  const isEditableDirty = computed(() => {
    if (!editableLoaded.value) return false;
    let currentArtifactsStr = "";
    try {
      currentArtifactsStr = normalizeArtifactsForComparison(buildArtifactsPayload());
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

  const createDraft = ref<VersionDraft>(defaultCreateDraft());

  const isCreateMode = computed(() => contentSubTab.value === "create");

  const versionDraft = computed(() => (isCreateMode.value ? createDraft.value : editableDraft.value));

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

  const selectedGame = computed(() => catalog.value.games.find((item) => item.id === selectedGameId.value) || null);
  const selectedDomain = computed(() => catalog.value.domains.find((item) => item.id === selectedDomainId.value) || null);
  const selectedVersionSummary = computed(() => versions.value.find((item) => item.version === selectedVersion.value) || null);

  const gameDropdownOpen = ref(false);
  const domainDropdownOpen = ref(false);
  const gameDropdownSearch = ref("");

  const filteredDropdownGames = computed(() => {
    const q = gameDropdownSearch.value.trim().toLowerCase();
    if (!q) return catalog.value.games;
    return catalog.value.games.filter(
      (g) => g.name.toLowerCase().includes(q) || g.id.toLowerCase().includes(q) || (g.sub_name && g.sub_name.toLowerCase().includes(q)),
    );
  });

  function handleDropdownSelectGame(gameId: string): void {
    selectedGameId.value = gameId;
    selectGame(gameId);
    openContent(selectedDomainId.value);
    gameDropdownOpen.value = false;
    gameDropdownSearch.value = "";
  }

  function handleDropdownSelectDomain(domainId: string): void {
    selectedDomainId.value = domainId;
    openContent(domainId);
    domainDropdownOpen.value = false;
  }

  function handleGlobalDropdownClick(event: MouseEvent): void {
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (!target.closest(".custom-dropdown-container.game-dropdown")) {
      gameDropdownOpen.value = false;
    }
    if (!target.closest(".custom-dropdown-container.domain-dropdown")) {
      domainDropdownOpen.value = false;
    }
  }

  const versionFilterState = ref<"all" | "unavailable" | "unknown">("all");

  async function toggleVersionFilter(target: "unavailable" | "unknown"): Promise<void> {
    if (isEditableDirty.value) {
      const confirmed = await askConfirm(
        `当前版本 (${selectedVersion.value}) 存在未保存的变更。\n切换筛选将丢弃未保存的修改，是否确定继续？`,
      );
      if (!confirmed) return;
    }

    if (versionFilterState.value === target) {
      // 取消筛选，恢复最新可用版本
      versionFilterState.value = "all";
      const latestAvailable = versions.value.find((v) => isVersionAvailable(v)) || versions.value[0];
      if (latestAvailable && latestAvailable.version !== selectedVersion.value) {
        selectedVersion.value = latestAvailable.version;
        await loadEditableVersion(selectedDomainId.value, latestAvailable.version);
      }
    } else {
      // 激活目标筛选，自动选中第一个匹配的版本
      versionFilterState.value = target;
      let targetVersion: VersionSummary | undefined;
      if (target === "unavailable") {
        targetVersion = versions.value.find((v) => isVersionUnavailable(v));
      } else if (target === "unknown") {
        targetVersion = versions.value.find((v) => isVersionUnknown(v));
      }

      if (targetVersion && targetVersion.version !== selectedVersion.value) {
        selectedVersion.value = targetVersion.version;
        await loadEditableVersion(selectedDomainId.value, targetVersion.version);
      }
    }
  }

  async function resetVersionFilter(): Promise<void> {
    if (isEditableDirty.value) {
      const confirmed = await askConfirm(
        `当前版本 (${selectedVersion.value}) 存在未保存的变更。\n清除筛选将丢弃未保存的修改，是否确定继续？`,
      );
      if (!confirmed) return;
    }

    versionFilterState.value = "all";
    const latestAvailable = versions.value.find((v) => isVersionAvailable(v)) || versions.value[0];
    if (latestAvailable && latestAvailable.version !== selectedVersion.value) {
      selectedVersion.value = latestAvailable.version;
      await loadEditableVersion(selectedDomainId.value, latestAvailable.version);
    }
  }

  const archiveHealthStats = computed(() => {
    const total = versions.value.length;
    const latest = versions.value[0]?.version || "—";
    let available = 0;
    let unavailable = 0;
    let unknown = 0;

    for (const v of versions.value) {
      if (isVersionUnavailable(v)) {
        unavailable++;
      } else if (isVersionUnknown(v)) {
        unknown++;
      } else {
        available++;
      }
    }

    return {
      total,
      latest,
      available,
      unavailable,
      unknown,
    };
  });

  const filteredVersions = computed(() => {
    let list = [...versions.value];
    if (versionFilterState.value === "unavailable") {
      list = list.filter((v) => isVersionUnavailable(v));
    } else if (versionFilterState.value === "unknown") {
      list = list.filter((v) => isVersionUnknown(v));
    }

    const q = versionSearchQuery.value.trim().toLowerCase();
    if (q) {
      list = list.filter((v) => v.version.toLowerCase().includes(q));
    }

    // 自然倒序排序
    list.sort(compareVersionsDesc);
    return list;
  });

  // 折叠展开状态管理
  const expandedMajorKeys = ref<Set<string>>(new Set());
  const expandedMinorKeys = ref<Set<string>>(new Set());
  const gameExpandedMajorCache: Record<string, string[]> = {};

  function toggleMajorGroup(majorKey: string): void {
    if (expandedMajorKeys.value.has(majorKey)) {
      expandedMajorKeys.value.delete(majorKey);
    } else {
      expandedMajorKeys.value.add(majorKey);
    }
    if (selectedGameId.value) {
      gameExpandedMajorCache[selectedGameId.value] = Array.from(expandedMajorKeys.value);
    }
  }

  function toggleMinorGroup(minorKey: string): void {
    if (expandedMinorKeys.value.has(minorKey)) {
      expandedMinorKeys.value.delete(minorKey);
    } else {
      expandedMinorKeys.value.add(minorKey);
    }
  }

  function ensureVersionExpanded(versionStr: string): void {
    const { majorKey, minorKey } = parseVersionKey(versionStr);
    expandedMajorKeys.value.add(majorKey);
    expandedMinorKeys.value.add(minorKey);
    if (selectedGameId.value) {
      gameExpandedMajorCache[selectedGameId.value] = Array.from(expandedMajorKeys.value);
    }
  }

  function scrollToActiveVersion(): void {
    nextTick(() => {
      const activeEl = document.querySelector(".version-master-item.active");
      activeEl?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  // 智能二级分层版本分组
  const groupedVersionList = computed<VersionMajorGroup[]>(() => {
    const list = filteredVersions.value;
    if (list.length === 0) return [];

    const majorMap = new Map<string, {
      majorKey: string;
      minorMap: Map<string, VersionSummary[]>;
      allItems: VersionSummary[];
    }>();

    for (const item of list) {
      const { majorKey, minorKey } = parseVersionKey(item.version);
      let majorEntry = majorMap.get(majorKey);
      if (!majorEntry) {
        majorEntry = {
          majorKey,
          minorMap: new Map(),
          allItems: [],
        };
        majorMap.set(majorKey, majorEntry);
      }
      majorEntry.allItems.push(item);

      let minorList = majorEntry.minorMap.get(minorKey);
      if (!minorList) {
        minorList = [];
        majorEntry.minorMap.set(minorKey, minorList);
      }
      minorList.push(item);
    }

    const result: VersionMajorGroup[] = [];

    for (const majorEntry of majorMap.values()) {
      majorEntry.allItems.sort(compareVersionsDesc);

      const entries: VersionGroupEntry[] = [];
      const sortedMinorEntries = Array.from(majorEntry.minorMap.entries()).sort((a, b) => {
        return compareVersionsDesc(a[1][0], b[1][0]);
      });

      for (const [minorKey, minorItems] of sortedMinorEntries) {
        minorItems.sort(compareVersionsDesc);
        if (minorItems.length === 1) {
          // 只有一个版本，直接平铺
          entries.push({
            type: "single",
            item: minorItems[0],
          });
        } else {
          // 存在多个补丁版本，增加二级折叠
          entries.push({
            type: "minorGroup",
            group: {
              minorKey,
              items: minorItems,
            },
          });
        }
      }

      const unavailableCount = majorEntry.allItems.filter((v) => isVersionUnavailable(v)).length;

      result.push({
        majorKey: majorEntry.majorKey,
        totalCount: majorEntry.allItems.length,
        unavailableCount,
        entries,
        allItems: majorEntry.allItems,
      });
    }

    result.sort((a, b) => {
      if (a.allItems[0] && b.allItems[0]) {
        return compareVersionsDesc(a.allItems[0], b.allItems[0]);
      }
      return b.majorKey.localeCompare(a.majorKey);
    });

    return result;
  });

  // 监听游戏、模块与版本变化，自动展开与恢复
  watch(
    () => [selectedDomainId.value, versions.value],
    () => {
      if (selectedGameId.value && gameExpandedMajorCache[selectedGameId.value]) {
        expandedMajorKeys.value = new Set(gameExpandedMajorCache[selectedGameId.value]);
      } else {
        expandedMajorKeys.value = new Set();
      }

      if (selectedVersion.value) {
        ensureVersionExpanded(selectedVersion.value);
      } else if (groupedVersionList.value.length > 0 && expandedMajorKeys.value.size === 0) {
        expandedMajorKeys.value.add(groupedVersionList.value[0].majorKey);
      }
      scrollToActiveVersion();
    },
    { immediate: true },
  );

  watch(
    () => selectedDomainSupportsCreateVersion.value,
    (supportsCreate) => {
      if (!supportsCreate && contentSubTab.value === "create") {
        contentSubTab.value = "edit";
      }
    },
  );

  // 监听健康筛选与搜索，自动展开匹配的大版本并在清除后精准恢复
  watch(
    () => [versionFilterState.value, versionSearchQuery.value] as const,
    ([filterState, query]) => {
      if (filterState !== "all" || (typeof query === "string" && query.trim())) {
        // 搜索或筛选中：自动展开所有匹配的大版本
        for (const g of groupedVersionList.value) {
          expandedMajorKeys.value.add(g.majorKey);
        }
      } else {
        // 清除搜索或筛选：恢复原先记忆状态或展开选中版本所在的大版本
        if (selectedGameId.value && gameExpandedMajorCache[selectedGameId.value]) {
          expandedMajorKeys.value = new Set(gameExpandedMajorCache[selectedGameId.value]);
        } else {
          expandedMajorKeys.value = new Set();
        }
        if (selectedVersion.value) {
          ensureVersionExpanded(selectedVersion.value);
        } else if (groupedVersionList.value.length > 0) {
          expandedMajorKeys.value.add(groupedVersionList.value[0].majorKey);
        }
      }
      scrollToActiveVersion();
    },
  );

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
    const current = selectedVersionSummary.value;
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
    versions,
    selectedVersion,
    versionSearchQuery,
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
    selectedDomainGameName,
    selectedGame,
    selectedDomain,
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
    gameDropdownOpen,
    domainDropdownOpen,
    gameDropdownSearch,
    filteredDropdownGames,
    versionFilterState,
    archiveHealthStats,
    filteredVersions,
    groupedVersionList,
    expandedMajorKeys,
    expandedMinorKeys,
    urlProbeMap,
    clearActiveFileTime,
    copyUrl,
    openUrl,
    onFileTimeInput,
    submitVersionForm,
    handleDropdownSelectGame,
    handleDropdownSelectDomain,
    handleGlobalDropdownClick,
    toggleVersionFilter,
    resetVersionFilter,
    toggleMajorGroup,
    toggleMinorGroup,
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
