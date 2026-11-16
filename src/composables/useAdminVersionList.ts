import { type ComputedRef, type Ref, computed, nextTick, ref, watch } from "vue";
import {
  type VersionGroupEntry,
  type VersionMajorGroup,
  compareVersionsDesc,
  isVersionAvailable,
  isVersionUnavailable,
  isVersionUnknown,
  parseVersionKey,
} from "../admin-version-editor";
import type { VersionSummary } from "../types";
import type { AdminShell } from "./admin-shell";

export interface AdminVersionListDeps {
  versions: Ref<VersionSummary[]>;
  selectedVersion: Ref<string>;
  isEditableDirty: ComputedRef<boolean>;
  openContent: (id?: string) => Promise<void>;
  loadEditableVersion: (domainId?: string, version?: string) => Promise<void>;
}

export function useAdminVersionList(shell: AdminShell, deps: AdminVersionListDeps) {
  const { catalog, selectedGameId, selectedDomainId, askConfirm, selectGame } = shell;
  const { versions, selectedVersion, isEditableDirty, openContent, loadEditableVersion } = deps;

  const versionSearchQuery = ref("");

  const selectedGame = computed(() => catalog.value.games.find((item) => item.id === selectedGameId.value) || null);
  const selectedDomain = computed(() => catalog.value.domains.find((item) => item.id === selectedDomainId.value) || null);
  const selectedDomainGameName = computed(() => {
    if (!selectedDomain.value) return "";
    const game = catalog.value.games.find((g) => g.id === selectedDomain.value?.game_id);
    return game?.name || selectedDomain.value.game_id;
  });

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
    void openContent(selectedDomainId.value);
    gameDropdownOpen.value = false;
    gameDropdownSearch.value = "";
  }

  function handleDropdownSelectDomain(domainId: string): void {
    selectedDomainId.value = domainId;
    void openContent(domainId);
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

  return {
    selectedVersion,
    versionSearchQuery,
    selectedGame,
    selectedDomain,
    selectedDomainGameName,
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
    handleDropdownSelectGame,
    handleDropdownSelectDomain,
    handleGlobalDropdownClick,
    toggleVersionFilter,
    resetVersionFilter,
    toggleMajorGroup,
    toggleMinorGroup,
    ensureVersionExpanded,
    scrollToActiveVersion,
  };
}

export type AdminVersionListState = ReturnType<typeof useAdminVersionList>;
