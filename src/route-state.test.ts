import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import ArchiveView from "./views/ArchiveView.vue";
import NotFoundView from "./views/NotFoundView.vue";

async function flushUpdates(delay = 0): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, delay));
  await nextTick();
}

const game = { id: "demo", name: "演示", sub_name: "Demo", icon_source: "", version_count: 2, latest_version: "2.0", sort_order: 0 };
const domain = {
  id: "demo-pc", game_id: "demo", kind: "files", platform: "windows",
  capabilities: ["files", "compare"], adapter: "generic", version_count: 2, latest_version: "2.0", sort_order: 0,
  capability_contract: {
    artifact_fields: { urls: "supported", availability: "supported" },
    actions: { open: "conditional", copy: "conditional", download: "conditional" },
  },
};
const versions = ["2.0", "1.0"].map((version, index) => ({
  version, current_revision_id: index + 1, revision_count: 1, observed_at: "2026-07-18T00:00:00Z",
  packed_size: 1, unpacked_size: 1, artifact_count: 1,
  artifact_kinds: { file: { count: 1, size: 1, availability_states: { unknown: 1 } } },
  availability_states: { unknown: 1 }, attributes: {}, provenance: {},
}));

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView },
      { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundView },
    ],
  });
}

describe("archive route state", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("loads APK cards from the raw version.json endpoint", async () => {
    const apkDomain = {
      ...domain,
      id: "demo-android",
      kind: "apk",
      platform: "android",
      capabilities: ["apk"],
      adapter: "android",
    };
    const gamesRequest = vi.spyOn(api, "games").mockResolvedValue([game] as never);
    const domainsRequest = vi.spyOn(api, "domains").mockResolvedValue([apkDomain] as never);
    const versionsRequest = vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    const versionRecord = vi.spyOn(api, "versionRecord").mockImplementation(async (_domainId, version) => ({
      vendor: "demo", game_id: "demo", platform: "android", channel: "official",
      version, version_code: null, filename: `demo_${version}.apk`,
      url: `https://example.test/demo_${version}.apk`, size: 42,
      checksum: { etag: "etag", crc64: null, md5: null },
      file_time: "2026-08-01T00:00:00Z",
      status: { http_code: 206, available: true, last_checked_at: "2026-08-23T00:00:00Z" },
    }));
    const artifacts = vi.spyOn(api, "artifacts");
    const router = testRouter();
    await router.push("/games/demo/demo-android/2.0/apk"); await router.isReady();
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ArchiveView); app.use(router); app.mount(root);
    await flushUpdates(); await flushUpdates();

    expect(versionRecord).toHaveBeenCalledWith("demo-android", "2.0", expect.any(AbortSignal));
    expect(artifacts).not.toHaveBeenCalled();
    expect(root.textContent).toContain("demo_2.0.apk");
    expect(root.querySelector<HTMLAnchorElement>('a[href="/api/v1/domains/demo-android/versions/2.0"]')).not.toBeNull();

    gamesRequest.mockClear(); domainsRequest.mockClear(); versionsRequest.mockClear(); versionRecord.mockClear();
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    const older = Array.from(root.querySelectorAll<HTMLButtonElement>(".version-row")).find(
      (row) => row.querySelector(".version-number")?.textContent === "1.0",
    );
    older?.click();
    await flushUpdates(); await flushUpdates();
    expect(gamesRequest).not.toHaveBeenCalled();
    expect(domainsRequest).not.toHaveBeenCalled();
    expect(versionsRequest).not.toHaveBeenCalled();
    expect(versionRecord).toHaveBeenCalledWith("demo-android", "1.0", expect.any(AbortSignal));
    app.unmount();
  });

  it("keeps file search while discarding URL availability state", async () => {
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue({ items: [], next_cursor: null });
    const router = testRouter();
    await router.push("/games/demo/demo-pc/2.0/files?q=needle&availability=unknown"); await router.isReady();
    const replace = vi.spyOn(router, "replace");
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ArchiveView); app.use(router); app.mount(root);
    await flushUpdates(); await flushUpdates();
    expect(artifacts).toHaveBeenCalledWith("demo-pc", "2.0", expect.objectContaining({ query: "needle", state: undefined }), expect.any(AbortSignal));
    expect(router.currentRoute.value.query).toEqual({ q: "needle" });
    const input = root.querySelector(".search-box input") as HTMLInputElement;
    input.value = "changed";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flushUpdates(220);
    expect(router.currentRoute.value.query).toEqual({ q: "changed" });
    expect(replace).toHaveBeenCalled();
    app.unmount();
  });

  it("persists the compare base as the only compare query state", async () => {
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    vi.spyOn(api, "compare").mockResolvedValue({ from_version: "1.0", to_version: "2.0", summary: { added: 0, removed: 0, changed: 0, size_delta: 0 }, items: [], next_cursor: null } as never);
    const router = testRouter();
    await router.push("/games/demo/demo-pc/2.0/compare?ignored=value&q=stale&availability=unknown&from=2.0"); await router.isReady();
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ArchiveView); app.use(router); app.mount(root);
    await flushUpdates(); await flushUpdates();
    expect(router.currentRoute.value.query).toEqual({ from: "1.0" });
    expect(root.querySelector(".search-box")).toBeNull();
    expect(api.compare).toHaveBeenCalledWith("demo-pc", expect.objectContaining({ fromVersion: "1.0", toVersion: "2.0" }), expect.any(AbortSignal));
    app.unmount();
  });

  it("removes fake search state from every non-search artifact mode", async () => {
    const mixedDomain = {
      ...domain,
      kind: "mixed",
      capabilities: ["files", "legacy", "archive", "compare", "manifest", "resources"],
    };
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([mixedDomain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    vi.spyOn(api, "leads").mockResolvedValue([] as never);
    vi.spyOn(api, "versionRecord").mockResolvedValue({} as never);
    vi.spyOn(api, "compare").mockResolvedValue({ from_version: "1.0", to_version: "2.0", summary: { added: 0, removed: 0, changed: 0, size_delta: 0 }, items: [], next_cursor: null } as never);
    vi.spyOn(api, "artifacts").mockResolvedValue({ items: [], next_cursor: null } as never);
    vi.spyOn(api, "artifactTree").mockResolvedValue({ prefix: "", folders: [], items: [], next_cursor: null } as never);

    for (const currentMode of ["legacy", "archive", "compare", "manifest", "resources"]) {
      const router = testRouter();
      await router.push(`/games/demo/demo-pc/2.0/${currentMode}?q=stale`); await router.isReady();
      const root = document.createElement("div"); document.body.appendChild(root);
      const app = createApp(ArchiveView); app.use(router); app.mount(root);
      await flushUpdates(); await flushUpdates();
      expect(router.currentRoute.value.query.q, currentMode).toBeUndefined();
      expect(root.querySelector(".search-box"), currentMode).toBeNull();
      app.unmount();
      root.remove();
    }
  });

  it("shows a scoped not-found state for an explicit invalid domain", async () => {
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    const artifacts = vi.spyOn(api, "artifacts");
    const router = testRouter();
    await router.push("/games/demo/missing/2.0/files"); await router.isReady();
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ArchiveView); app.use(router); app.mount(root);
    await flushUpdates();
    expect(root.textContent).toContain("请求的归档范围不存在");
    expect(root.textContent).toContain("missing");
    expect(artifacts).not.toHaveBeenCalled();
    app.unmount();
  });

  it("shows an empty registry state without inventing a default game", async () => {
    vi.spyOn(api, "games").mockResolvedValue([] as never);
    const router = testRouter();
    await router.push("/games/"); await router.isReady();
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ArchiveView); app.use(router); app.mount(root);
    await flushUpdates();
    expect(root.textContent).toContain("还没有游戏归档");
    app.unmount();
  });

  it("retries a registry failure in place", async () => {
    const games = vi.spyOn(api, "games")
      .mockRejectedValueOnce(new Error("registry unavailable"))
      .mockResolvedValueOnce([] as never);
    const router = testRouter();
    await router.push("/games/demo"); await router.isReady();
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ArchiveView); app.use(router); app.mount(root);
    await flushUpdates();
    expect(root.textContent).toContain("registry unavailable");
    (root.querySelector("button") as HTMLButtonElement).click();
    await flushUpdates();
    expect(games).toHaveBeenCalledTimes(2);
    expect(root.textContent).toContain("还没有游戏归档");
    app.unmount();
  });

  it("renders the catch-all not-found route", async () => {
    const router = testRouter();
    await router.push("/missing-page"); await router.isReady();
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(NotFoundView); app.use(router); app.mount(root);
    expect(router.currentRoute.value.name).toBe("not-found");
    expect(root.textContent).toContain("没有这个归档页面");
    app.unmount();
  });
});
