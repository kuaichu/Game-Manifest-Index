import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { domainRouteLabel, resolveRouteDomain } from "./composables/useArchiveLoader";
import type { ArchiveDomain } from "./types";
import ArchiveView from "./views/ArchiveView.vue";

const mountedApps: ReturnType<typeof createApp>[] = [];

async function flushUpdates(): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, 0));
  await nextTick();
}

function summary(version: string, kind: "apk" | "package" = "package") {
  return {
    version,
    current_revision_id: 1,
    revision_count: 1,
    observed_at: "2026-09-01T00:00:00Z",
    source_released_at: null,
    source_updated_at: null,
    archived_at: null,
    imported_at: "2026-09-01T00:00:00Z",
    packed_size: 1,
    unpacked_size: 1,
    artifact_count: 1,
    artifact_kinds: { [kind]: { count: 1, size: 1, availability_states: { unknown: 1 } } },
    availability_states: { unknown: 1 },
    attributes: {},
    provenance: {},
  };
}

function routerFor() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
  });
}

async function mountAt(path: string) {
  const router = routerFor();
  await router.push(path);
  await router.isReady();
  const root = document.createElement("div");
  document.body.appendChild(root);
  const app = createApp(ArchiveView);
  app.use(router);
  app.mount(root);
  mountedApps.push(app);
  await flushUpdates();
  await flushUpdates();
  return { app, root, router };
}

function game() {
  return { id: "nap", name: "绝区零", sub_name: "Zenless Zone Zero", icon_source: "", sort_order: 0 };
}

function androidDomain() {
  return {
    id: "nap-android", game_id: "nap", kind: "apk", platform: "android",
    capabilities: ["apk", "compare"], adapter: "android", version_count: 2, latest_version: "3.2",
    sort_order: 1, capability_contract: { features: { compare: "supported" } },
  };
}

function pcDomain() {
  return {
    id: "nap-pc", game_id: "nap", kind: "mixed", platform: "windows",
    capabilities: ["packages", "compare"], adapter: "generic", version_count: 4, latest_version: "3.2.0",
    sort_order: 0, capability_contract: { features: { compare: "supported" } },
  };
}

afterEach(() => {
  for (const app of mountedApps.splice(0)) app.unmount();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("public version route aliases", () => {
  it.each(["nap-android/3.2", "android/3.2", "nap-android/3.2.0", "android/3.2.0"])("loads APK route %s with raw records and supports back/forward", async (path) => {
    const versions = [summary("3.2", "apk"), summary("3.1", "apk")];
    const games = vi.spyOn(api, "games").mockResolvedValue([game()] as never);
    vi.spyOn(api, "domains").mockResolvedValue([androidDomain()] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    const versionRecord = vi.spyOn(api, "versionRecord").mockImplementation(async (_domain, version) => ({
      vendor: "mihoyo", game_id: "nap", platform: "android", channel: "official", version,
      version_code: null, filename: `nap_${version}.apk`, url: `https://example.test/${version}.apk`, size: 1,
      checksum: { etag: null, crc64: null, md5: null }, file_time: null,
      status: { http_code: 206, available: true, last_checked_at: "2026-09-01T00:00:00Z" },
    }));

    const { root, router } = await mountAt(`/games/nap/${path}/apk`);
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/android/3.2.0/apk");
    expect(versionRecord).toHaveBeenCalledWith("nap-android", "3.2", expect.any(AbortSignal));
    expect(root.textContent).toContain("3.2.0");
    expect(root.querySelector(".select-button")?.textContent).toContain("3.2.0");
    expect(games).toHaveBeenCalledTimes(1);

    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    const firstVersion = root.querySelector(".version-row .version-number")?.textContent?.trim();
    expect(firstVersion).toBe("3.2.0");
    const older = Array.from(root.querySelectorAll<HTMLButtonElement>(".version-row")).find(
      (row) => row.querySelector(".version-number")?.textContent?.trim() === "3.1.0",
    );
    expect(older).toBeDefined();
    older!.click();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/android/3.1.0/apk");
    expect(versionRecord).toHaveBeenCalledWith("nap-android", "3.1", expect.any(AbortSignal));

    await router.back();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/android/3.2.0/apk");
    await router.forward();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/android/3.1.0/apk");
  });

  it.each(["nap-pc/3.2", "pc/3.2", "nap-pc/3.2.0", "pc/3.2.0"])("loads PC route %s with raw API domain and version", async (path) => {
    const versions = [summary("3.2"), summary("3.1")];
    vi.spyOn(api, "games").mockResolvedValue([game()] as never);
    vi.spyOn(api, "domains").mockResolvedValue([pcDomain()] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue({ items: [], next_cursor: null } as never);

    const { root, router } = await mountAt(`/games/nap/${path}/packages`);
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/pc/3.2.0/packages");
    expect(root.querySelector(".select-button")?.textContent).toContain("3.2.0");
    expect(artifacts.mock.calls.some(([domain, version]) => domain === "nap-pc" && version === "3.2")).toBe(true);
  });

  it("normalizes compare path and query aliases but sends raw versions to compare", async () => {
    const versions = [summary("2.8"), summary("2.7"), summary("2.6")];
    const domain = { ...pcDomain(), version_count: 3, latest_version: "2.8" };
    vi.spyOn(api, "games").mockResolvedValue([game()] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    const compare = vi.spyOn(api, "compare").mockResolvedValue({
      from_version: "2.6", to_version: "2.8", summary: { added: 0, removed: 0, changed: 0, size_delta: 0 },
      items: [], next_cursor: null,
    } as never);

    const { router } = await mountAt("/games/nap/pc/2.8/compare?from=2.6");
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/pc/2.8.0/compare?from=2.6.0");
    expect(compare).toHaveBeenCalledWith("nap-pc", expect.objectContaining({ fromVersion: "2.6", toVersion: "2.8" }), expect.any(AbortSignal));
  });

  it("keeps an old Android target and non-default compare base across PC switches", async () => {
    const androidVersions = [summary("3.2", "apk"), summary("3.1", "apk"), summary("3.0", "apk"), summary("2.9", "apk")];
    const pcVersions = [summary("3.2.0"), summary("3.1.0"), summary("3.0.0"), summary("2.9.0")];
    vi.spyOn(api, "games").mockResolvedValue([game()] as never);
    vi.spyOn(api, "domains").mockResolvedValue([pcDomain(), androidDomain()] as never);
    vi.spyOn(api, "versions").mockImplementation(async (domainId) => (domainId === "nap-android" ? androidVersions : pcVersions) as never);
    const compare = vi.spyOn(api, "compare").mockResolvedValue({
      from_version: "2.9", to_version: "3.1", summary: { added: 0, removed: 0, changed: 0, size_delta: 0 },
      items: [], next_cursor: null,
    } as never);

    const { root, router } = await mountAt("/games/nap/android/3.1/compare?from=2.9");
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/android/3.1.0/compare?from=2.9.0");
    expect(compare).toHaveBeenCalledWith("nap-android", expect.objectContaining({ fromVersion: "2.9", toVersion: "3.1" }), expect.any(AbortSignal));
    const platformTabs = root.querySelectorAll<HTMLButtonElement>(".compare-platform-tab");
    expect(platformTabs).toHaveLength(2);
    platformTabs[0].click();
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/pc/3.1.0/compare?from=2.9.0");
    expect(compare).toHaveBeenCalledWith("nap-pc", expect.objectContaining({ fromVersion: "2.9.0", toVersion: "3.1.0" }), expect.any(AbortSignal));

    const backToAndroid = Array.from(root.querySelectorAll<HTMLButtonElement>(".compare-platform-tab"))
      .find((button) => button.textContent?.includes("Android"));
    backToAndroid!.click();
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/nap/android/3.1.0/compare?from=2.9.0");
    expect(compare).toHaveBeenCalledWith("nap-android", expect.objectContaining({ fromVersion: "2.9", toVersion: "3.1" }), expect.any(AbortSignal));
  });
});

describe("public platform aliases", () => {
  const pc = { ...pcDomain(), id: "endfield-pc", game_id: "endfield" } as ArchiveDomain;
  const resources = { ...pc, id: "endfield-resources", capabilities: ["resources"] };

  it("resolves pc to the primary catalog even when a secondary resource domain comes first", () => {
    expect(resolveRouteDomain("endfield", "pc", [resources, pc])?.id).toBe("endfield-pc");
    expect(domainRouteLabel("endfield", resources)).toBe("endfield-resources");
    expect(resolveRouteDomain("endfield", "endfield-resources", [resources, pc])?.id).toBe("endfield-resources");
  });

  it("does not resolve a platform from the previous game's catalog", () => {
    expect(resolveRouteDomain("nap", "pc", [pc])).toBeUndefined();
    expect(resolveRouteDomain("endfield", "android", [resources, pc])).toBeUndefined();
  });
});
