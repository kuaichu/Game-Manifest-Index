import { ref, type Ref } from "vue";
import type { RouteLocationNormalizedLoaded, Router } from "vue-router";
import { api, isAbortError } from "../api";
import { displayVersionLabel, versionSupportsMode } from "../domain-presentation";
import type { ArchiveDomain, Game, VersionSummary } from "../types";

export interface ArchiveLoaderOptions {
  route: RouteLocationNormalizedLoaded;
  router: Router;
  searchableModes: ReadonlySet<string>;
  loadArtifacts: (append: boolean) => Promise<void>;
  invalidateArtifactLoad: () => void;
}

export interface ArchiveLoaderState {
  games: Ref<Game[]>;
  domains: Ref<ArchiveDomain[]>;
  versions: Ref<VersionSummary[]>;
  versionsDomainId: Ref<string>;
  loading: Ref<boolean>;
  registryError: Ref<Error | null>;
  scopedNotFound: Ref<string>;
  registryTargetGame: Ref<string>;
  registryTargetDomain: Ref<string>;
  loadRegistry: () => Promise<void>;
  dispose: () => void;
}

function preferredDomain(items: ArchiveDomain[]): ArchiveDomain | undefined {
  return [...items].sort((left, right) => {
    const score = (item: ArchiveDomain) =>
      item.adapter === "android" || item.capabilities.every((capability) => capability === "apk") ? 10 : 0;
    return score(left) - score(right);
  })[0];
}

export function useArchiveLoader(options: ArchiveLoaderOptions): ArchiveLoaderState {
  const games = ref<Game[]>([]);
  const domains = ref<ArchiveDomain[]>([]);
  const versions = ref<VersionSummary[]>([]);
  const versionsDomainId = ref("");
  const loading = ref(true);
  const registryError = ref<Error | null>(null);
  const scopedNotFound = ref("");
  const registryTargetGame = ref("");
  const registryTargetDomain = ref("");
  let registryController: AbortController | null = null;
  let registryRequestId = 0;

  const loadRegistry = async (): Promise<void> => {
    registryController?.abort();
    options.invalidateArtifactLoad();
    const request = new AbortController();
    registryController = request;
    const requestId = ++registryRequestId;
    const isCurrent = () => registryRequestId === requestId && !request.signal.aborted;
    loading.value = true;
    registryError.value = null;
    scopedNotFound.value = "";
    try {
      const loadedGames = await api.games(request.signal);
      if (!isCurrent()) return;
      games.value = loadedGames;
      if (!loadedGames.length) {
        domains.value = [];
        versions.value = [];
        return;
      }
      const requestedGame = String(options.route.params.gameId || "");
      if (requestedGame && !loadedGames.some((item) => item.id === requestedGame)) {
        domains.value = [];
        versions.value = [];
        scopedNotFound.value = `游戏 ${requestedGame} 不存在。`;
        return;
      }
      const targetGame = requestedGame || loadedGames[0]?.id;
      if (!targetGame) return;
      registryTargetGame.value = targetGame;
      const loadedDomains = [...(await api.domains(targetGame, request.signal))].sort((left, right) => {
        const score = (item: ArchiveDomain) =>
          item.adapter === "android" || item.capabilities.every((capability) => capability === "apk") ? 10 : 0;
        return score(left) - score(right);
      });
      if (!isCurrent()) return;
      domains.value = loadedDomains;
      const rawRequestedDomain = String(options.route.params.domainId || "");
      const aliasDomain = rawRequestedDomain === "pc"
        ? loadedDomains.find((item) => item.id === `${targetGame}-pc` || item.platform?.toLowerCase() === "windows")?.id
        : rawRequestedDomain === "android"
          ? loadedDomains.find((item) => item.id === `${targetGame}-android` || item.platform?.toLowerCase() === "android")?.id
          : undefined;
      const requestedDomain = aliasDomain || rawRequestedDomain;
      if (requestedDomain && !loadedDomains.some((item) => item.id === requestedDomain)) {
        versions.value = [];
        scopedNotFound.value = `归档域 ${requestedDomain} 不属于 ${targetGame}。`;
        return;
      }
      const targetDomain = requestedDomain || preferredDomain(loadedDomains)?.id;
      if (!targetDomain) return;
      registryTargetDomain.value = targetDomain;
      const loadedVersions = await api.versions(targetDomain, request.signal);
      if (!isCurrent()) return;
      versions.value = loadedVersions;
      versionsDomainId.value = targetDomain;
      let requestedVersion = String(options.route.params.version || "");
      let requestedMode = String(options.route.params.mode || "");
      if (requestedVersion === "files") {
        requestedMode = "files";
        requestedVersion = String(options.route.query.version || "");
      }
      const targetDomainRow = loadedDomains.find((item) => item.id === targetDomain);
      const hasRequestedMode = Boolean(requestedMode && targetDomainRow?.capabilities.includes(requestedMode));
      const targetMode = hasRequestedMode ? requestedMode : targetDomainRow?.capabilities[0];
      if (!targetMode) return;
      const scopesHoYoVersions = targetDomainRow?.adapter === "hoyo"
        && ["packages", "patches", "chunks"].includes(targetMode);
      const modeVersions = scopesHoYoVersions
        ? loadedVersions.filter((item) => versionSupportsMode(item, targetMode, targetDomainRow?.adapter))
        : loadedVersions;
      const matchedVersion = modeVersions.find(
        (item) => item.version === requestedVersion || displayVersionLabel(item.version, item.attributes) === requestedVersion,
      )?.version;
      const targetVersion = matchedVersion || modeVersions[0]?.version || loadedVersions[0]?.version;
      if (!targetVersion) return;
      const requestedCompareFrom = String(options.route.query.from || "");
      const targetIndex = loadedVersions.findIndex((item) => item.version === targetVersion);
      const fallbackCompareFrom =
        loadedVersions[targetIndex + 1]?.version ||
        loadedVersions.find((item) => item.version !== targetVersion)?.version ||
        "";
      const cleanQuery: Record<string, string> = {};
      const cleanSearch = String(options.route.query.q || "").trim();
      const cleanAvailability = String(options.route.query.availability || "");
      if (options.searchableModes.has(targetMode) && cleanSearch) cleanQuery.q = cleanSearch;
      if (
        !["files", "legacy", "archive", "compare", "manifest"].includes(targetMode) &&
        targetDomainRow?.capability_contract?.artifact_fields?.availability === "supported" &&
        ["available", "unavailable", "unknown"].includes(cleanAvailability)
      ) {
        cleanQuery.availability = cleanAvailability;
      }
      if (targetMode === "files") {
        if (options.route.query.source) cleanQuery.source = String(options.route.query.source);
        if (options.route.query.identity) cleanQuery.identity = String(options.route.query.identity);
        if (options.route.query.path) cleanQuery.path = String(options.route.query.path);
      }
      const validCompareFrom =
        requestedCompareFrom !== targetVersion && loadedVersions.some((item) => item.version === requestedCompareFrom)
          ? requestedCompareFrom
          : fallbackCompareFrom;
      if (targetMode === "compare" && validCompareFrom) cleanQuery.from = validCompareFrom;
      const queryChanged = JSON.stringify(options.route.query) !== JSON.stringify(cleanQuery);
      if (!requestedGame || !requestedDomain || requestedVersion !== targetVersion || requestedMode !== targetMode || queryChanged) {
        if (!isCurrent()) return;
        await options.router.replace({
          name: "archive",
          params: { gameId: targetGame, domainId: targetDomain, version: targetVersion, mode: targetMode },
          query: cleanQuery,
        });
      }
      if (!isCurrent()) return;
      await options.loadArtifacts(false);
    } catch (reason) {
      if (isAbortError(reason)) return;
      if (!isCurrent()) return;
      registryError.value = reason instanceof Error ? reason : new Error(String(reason));
    } finally {
      if (registryController === request) loading.value = false;
    }
  };

  const dispose = (): void => {
    registryRequestId += 1;
    registryController?.abort();
    registryController = null;
  };

  return {
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
    dispose,
  };
}
