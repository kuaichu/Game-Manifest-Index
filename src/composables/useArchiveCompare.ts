import { computed, type Ref } from "vue";
import type { RouteLocationNormalizedLoaded } from "vue-router";
import { displayVersionLabel, routeVersionLabel } from "../domain-presentation";
import type { ArchiveDomain, VersionSummary } from "../types";

export interface ArchiveCompareOptions {
  route: RouteLocationNormalizedLoaded;
  domains: Ref<ArchiveDomain[]>;
  domain: Ref<ArchiveDomain | null>;
  domainId: Ref<string>;
  versions: Ref<VersionSummary[]>;
  selectedVersion: Ref<string>;
  selectedSummary: Ref<VersionSummary | null>;
  navigate: (params: Record<string, string>) => Promise<void>;
  replaceQuery: (name: "q" | "availability" | "from", value: string) => Promise<void>;
}

function hasHoyoPackageFiles(summary: VersionSummary | null | undefined): boolean {
  return Number(summary?.artifact_kinds?.package?.count || 0) > 0;
}

export function comparePlatformLabel(item: ArchiveDomain): string {
  if (item.adapter === "android" || item.platform?.toLowerCase() === "android" || item.kind === "apk") {
    return "Android 官方客户端";
  }
  if (item.adapter === "hoyo") {
    return "HOYO PC 客户端";
  }
  if (item.platform?.toLowerCase() === "windows" || item.platform?.toLowerCase() === "pc") {
    return "PC 客户端";
  }
  return item.platform || item.id;
}

export function useArchiveCompare(options: ArchiveCompareOptions) {
  const compareBaseOptions = computed(() =>
    options.versions.value.filter((item) => item.version !== options.selectedVersion.value),
  );

  const compareDomains = computed(() =>
    options.domains.value.filter((item) => item.capabilities.includes("compare")),
  );

  async function switchCompareDomain(targetDomain: ArchiveDomain): Promise<void> {
    if (targetDomain.id === options.domainId.value) return;
    await options.navigate({
      domainId: targetDomain.id,
      version: options.selectedVersion.value || targetDomain.latest_version || "",
      mode: "compare",
    });
  }

  const compareBaseVersion = computed(() => {
    const requested = String(options.route.query.from || "");
    const requestedItem = options.versions.value.find(
      (item) => item.version === requested || routeVersionLabel(item.version) === requested,
    );
    if (requestedItem && requestedItem.version !== options.selectedVersion.value) {
      return requestedItem.version;
    }
    const currentIndex = options.versions.value.findIndex((item) => item.version === options.selectedVersion.value);
    return options.versions.value[currentIndex + 1]?.version || compareBaseOptions.value[0]?.version || "";
  });

  const compareBaseSummary = computed(
    () => options.versions.value.find((item) => item.version === compareBaseVersion.value) || null,
  );

  const compareBaseDisplayVersion = computed(() =>
    displayVersionLabel(compareBaseVersion.value, compareBaseSummary.value?.attributes),
  );

  const compareScope = computed<"artifacts" | "files">(() => {
    const adapter = options.domain.value?.adapter;
    if (adapter === "perfectworld_patcher" || adapter === "nte" || adapter === "wuwa") {
      return "files";
    }
    if (adapter === "hoyo" && hasHoyoPackageFiles(options.selectedSummary.value) && hasHoyoPackageFiles(compareBaseSummary.value)) {
      return "files";
    }
    return "artifacts";
  });

  function updateCompareBase(value: string): void {
    void options.replaceQuery("from", routeVersionLabel(value));
  }

  return {
    compareBaseOptions,
    compareDomains,
    compareBaseVersion,
    compareBaseSummary,
    compareBaseDisplayVersion,
    compareScope,
    switchCompareDomain,
    updateCompareBase,
  };
}
