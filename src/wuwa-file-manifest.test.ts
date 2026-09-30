import { createApp, nextTick, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import ArchiveView from "./views/ArchiveView.vue";
import RemoteArtifactTree from "./components/RemoteArtifactTree.vue";
import type { ArtifactTreePage } from "./types";

async function flush(): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

describe("WuWa file-manifest package and patch cards", () => {
  let app: App | null = null;
  const totals: Record<string, number> = { "3.7.0": 86456782554, "3.6.0": 89408316433, "3.4.0": 112192002858 };
  const emptyTree = { prefix: "", folders: [], items: [], next_cursor: null };

  async function mountFiles(path = "/games/wuwa/wuwa-pc/3.7.0/files", fileBucket = false) {
    vi.spyOn(api, "games").mockResolvedValue([{ id: "wuwa", name: "鸣潮", sub_name: "", icon_source: "", sort_order: 0 }] as never);
    vi.spyOn(api, "domains").mockResolvedValue([{
      id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
      capabilities: ["files", "patches"], adapter: "wuwa", version_count: 3, latest_version: "3.7.0", sort_order: 0,
    }] as never);
    vi.spyOn(api, "versions").mockResolvedValue(Object.entries(totals).map(([version, size]) => ({
      version, current_revision_id: 1, revision_count: 1, observed_at: null,
      packed_size: 4100074944134, unpacked_size: 0, artifact_count: 49,
      artifact_kinds: { package: { count: 1, size }, patch: { count: 48, size: 4013618161580 },
        ...(fileBucket ? { file: { count: 809, size } } : {}) },
      availability_states: { available: 49 }, attributes: {}, provenance: {},
    })) as never);
    vi.spyOn(api, "artifacts").mockResolvedValue({ items: [], next_cursor: null } as never);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }] });
    await router.push(path);
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flush();
    await flush();
    return { root, router, header: () => root.querySelector(".panel-title-row")?.textContent || "" };
  }

  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason: Error) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  }

  afterEach(() => {
    app?.unmount();
    app = null;
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("renders manifest actions in the real WuWa package branch without download hrefs", async () => {
    const game = { id: "wuwa", name: "Wuthering Waves", sub_name: "", icon_source: "", sort_order: 0 };
    const domain = {
      id: "wuwa-pc", game_id: "wuwa", kind: "packages", platform: "windows",
      capabilities: ["packages", "patches", "files"], adapter: "wuwa", version_count: 1,
      latest_version: "3.6.0", source_current_version: "3.6.0", catalog_version_count: 1, sort_order: 0,
      capability_contract: {
        artifact_fields: { size: "supported", checksum: "supported", urls: "supported", availability: "supported" },
        url_source_kinds: ["official"], availability_source_kinds: ["metadata_inference"],
        actions: { open: "conditional", copy: "conditional", download: "conditional" }, live_probe: false,
      },
    };
    const version = {
      version: "3.6.0", current_revision_id: 1, revision_count: 1, observed_at: null,
      packed_size: 10, unpacked_size: 10, artifact_count: 1,
      artifact_kinds: { package: { count: 1, size: 10, availability_states: { unknown: 1 } } },
      availability_states: { unknown: 1 }, attributes: {}, provenance: {},
    };
    const artifact = {
      id: 1, kind: "package", name: "WutheringWaves-3.6.0-full", part: 1, size: 10,
      checksum_type: null, checksum_value: null,
      attributes: {
        delivery_mode: "file_manifest", manifest_urls: ["https://pcdownload-aliyun.aki-game.com/root/indexFile.json"],
        base_urls: ["https://pcdownload-aliyun.aki-game.com/root/"],
      },
      urls: [{ id: 1, url: "https://pcdownload-aliyun.aki-game.com/root/indexFile.json", priority: 0, source_kind: "official", evidence_status: "no_evidence", current: null }],
    };
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    vi.spyOn(api, "artifacts").mockResolvedValue({ items: [artifact], next_cursor: null } as never);

    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }] });
    await router.push("/games/wuwa/wuwa-pc/3.6.0/packages");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flush();
    await flush();

    expect(root.textContent).toContain("查看清单");
    expect(root.textContent).toContain("复制清单链接");
    expect(root.textContent).toContain("复制资源文件根目录");
    expect(root.querySelector(".file-actions")?.textContent).not.toContain("下载");
    expect(root.querySelector(".file-actions a")).toBeNull();
    (root.querySelector(".file-actions button") as HTMLButtonElement).click();
    await flush();
    expect(router.currentRoute.value.params.mode).toBe("files");
  });

  it("shows full manifest totals for recent and historical versions, preserving the patch header", async () => {
    const tree = vi.spyOn(api, "artifactTree").mockImplementation(async (_domain, version) => ({
      ...emptyTree, manifest_total_size: totals[version],
      folders: [{ path: "Client", name: "Client", artifact_count: 809, total_size: 86015296263 }],
    }));
    const { root, router, header } = await mountFiles();
    expect(header()).toContain("总大小80.52 GB");
    expect(root.textContent).toContain("80.11 GB");
    expect(header()).not.toContain("3.73 TB");
    expect(tree).toHaveBeenCalledTimes(1);
    for (const [version, expected] of [["3.6.0", "83.27 GB"], ["3.4.0", "104.49 GB"]]) {
      await router.push(`/games/wuwa/wuwa-pc/${version}/files`);
      await flush(); await flush();
      expect(header()).toContain(`总大小${expected}`);
    }
    await router.push("/games/wuwa/wuwa-pc/3.7.0/patches");
    await flush(); await flush();
    expect(header()).toContain("总大小3.65 TB");
    expect(header()).not.toContain("80.52 GB");
  });

  it("keeps the whole manifest size through subfolders, pagination, filtering and search", async () => {
    const tree = vi.spyOn(api, "artifactTree").mockImplementation(async (_domain, _version, options) => ({
      ...emptyTree, prefix: options.prefix || "", manifest_total_size: totals["3.7.0"],
      folders: options.prefix ? [] : [{ path: "Client", name: "Client", artifact_count: 2, total_size: 100 }],
      next_cursor: options.prefix && !options.cursor ? "1" : null,
    }));
    const { root, router, header } = await mountFiles();
    (root.querySelector(".folder-row") as HTMLElement).click();
    await flush();
    expect(header()).toContain("80.52 GB");
    (root.querySelector(".tree-load-btn") as HTMLButtonElement).click();
    await flush();
    expect(header()).toContain("80.52 GB");
    expect(tree).toHaveBeenLastCalledWith("wuwa-pc", "3.7.0", expect.objectContaining({ prefix: "Client", cursor: "1" }), expect.any(AbortSignal));
    await router.push("/games/wuwa/wuwa-pc/3.7.0/files?availability=available");
    await flush(); await flush();
    expect(header()).toContain("80.52 GB");
    const callsBeforeSearch = tree.mock.calls.length;
    const input = root.querySelector(".search-box input") as HTMLInputElement;
    input.value = "Client";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush(); await flush();
    expect(header()).toContain("80.52 GB");
    expect(tree).toHaveBeenCalledTimes(callsBeforeSearch);
  });

  it.each([undefined, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, NaN])("hides unavailable or invalid manifest totals (%s) without using package or patch sums", async (size) => {
    vi.spyOn(api, "artifactTree").mockResolvedValue({ ...emptyTree, manifest_total_size: size });
    const { header } = await mountFiles();
    expect(header()).not.toContain("总大小");
    expect(header()).not.toContain("TB");
  });

  it("shows an empty manifest as zero bytes", async () => {
    vi.spyOn(api, "artifactTree").mockResolvedValue({ ...emptyTree, manifest_total_size: 0 });
    const { header } = await mountFiles();
    expect(header()).toContain("总大小0 B");
  });

  it("shows the current official manifest time and preserves it in the local search tree", async () => {
    const tree = vi.spyOn(api, "artifactTree").mockResolvedValue({ ...emptyTree, manifest_total_size: totals["3.7.0"], file_time: "2026-09-29T20:00:03Z", file_time_source: "manifest" });
    const { root, header } = await mountFiles();
    expect(header()).toContain("文件时间2026.09.30 04:00");
    expect(root.querySelector(".panel-meta-inline [title]")?.getAttribute("title")).toContain("官方清单文件");
    const input = root.querySelector(".search-box input") as HTMLInputElement;
    input.value = "Client";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush(); await flush();
    expect(header()).toContain("文件时间2026.09.30 04:00");
    expect(tree).toHaveBeenCalledTimes(1);
  });

  it("uses one root metadata request for date and size on an initial search", async () => {
    const tree = vi.spyOn(api, "artifactTree").mockResolvedValue({ ...emptyTree, manifest_total_size: totals["3.7.0"], file_time: "2026-09-29T20:00:03Z", file_time_source: "manifest" });
    const { header } = await mountFiles("/games/wuwa/wuwa-pc/3.7.0/files?q=Client");
    expect(header()).toContain("文件时间2026.09.30 04:00");
    expect(header()).toContain("80.52 GB");
    expect(tree).toHaveBeenCalledTimes(1);
  });

  it("preserves a genuine legacy file bucket with an older API", async () => {
    vi.spyOn(api, "artifactTree").mockResolvedValue(emptyTree);
    const { header } = await mountFiles(undefined, true);
    expect(header()).toContain("总大小80.52 GB");
  });

  it("hides the previous version while loading or after failure and ignores its late result", async () => {
    const oldRequest = deferred<ArtifactTreePage>();
    const nextRequest = deferred<ArtifactTreePage>();
    const tree = vi.spyOn(api, "artifactTree").mockResolvedValue({ ...emptyTree, manifest_total_size: totals["3.7.0"] });
    const { root, router, header } = await mountFiles();
    expect(header()).toContain("80.52 GB");
    tree.mockImplementation((_domain, version) => version === "3.6.0" ? oldRequest.promise : nextRequest.promise);
    await router.push("/games/wuwa/wuwa-pc/3.6.0/files");
    await flush();
    expect(header()).not.toContain("总大小");
    await router.push("/games/wuwa/wuwa-pc/3.4.0/files");
    await flush();
    oldRequest.resolve({ ...emptyTree, manifest_total_size: totals["3.6.0"] });
    await flush();
    expect(header()).not.toContain("83.27 GB");
    nextRequest.reject(new Error("manifest unavailable"));
    await flush();
    expect(root.textContent).toContain("manifest unavailable");
    expect(header()).not.toContain("总大小");
  });

  it("loads only root total metadata when entering directly with a search, including version switches", async () => {
    const tree = vi.spyOn(api, "artifactTree").mockImplementation(async (_domain, version) => ({ ...emptyTree, manifest_total_size: totals[version] }));
    const { router, header } = await mountFiles("/games/wuwa/wuwa-pc/3.7.0/files?q=Client");
    expect(header()).toContain("80.52 GB");
    expect(tree).toHaveBeenCalledTimes(1);
    expect(tree).toHaveBeenLastCalledWith("wuwa-pc", "3.7.0", { kind: "file", limit: 1 }, expect.any(AbortSignal));
    await router.push("/games/wuwa/wuwa-pc/3.6.0/files?q=Client");
    await flush(); await flush();
    expect(header()).toContain("83.27 GB");
    expect(header()).not.toContain("80.52 GB");
    expect(tree).toHaveBeenCalledTimes(2);
  });

  it("ignores late search metadata after the normal tree has supplied the current total", async () => {
    const pending = deferred<ArtifactTreePage>();
    const tree = vi.spyOn(api, "artifactTree").mockReturnValue(pending.promise);
    const { root, header } = await mountFiles("/games/wuwa/wuwa-pc/3.7.0/files?q=Client");
    expect(header()).not.toContain("总大小");
    tree.mockResolvedValue({ ...emptyTree, manifest_total_size: totals["3.7.0"] });
    const input = root.querySelector(".search-box input") as HTMLInputElement;
    input.value = "";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush(); await flush();
    expect(header()).toContain("80.52 GB");
    pending.reject(new Error("obsolete metadata failure"));
    await flush();
    expect(header()).toContain("80.52 GB");
    expect(tree).toHaveBeenCalledTimes(2);
  });

  it("rejects a tree result if props change before their watcher starts the next request", async () => {
    const pending = deferred<ArtifactTreePage>();
    const tree = vi.spyOn(api, "artifactTree").mockReturnValue(pending.promise);
    const sizes: Array<{ version: string; size: number | null }> = [];
    const root = document.createElement("div");
    document.body.appendChild(root);
    app = createApp(RemoteArtifactTree, { domainId: "wuwa-pc", version: "3.7.0", kind: "file", onManifestSizeChange: (size: { version: string; size: number | null }) => sizes.push(size) });
    const child = app.mount(root);
    // Queue the response continuation first, then queue Vue's prop watcher flush.
    pending.resolve({ ...emptyTree, manifest_total_size: totals["3.7.0"] });
    child.$.props.version = "3.6.0";
    tree.mockReturnValue(new Promise(() => {}));
    await flush();
    expect(sizes).not.toContainEqual({ domainId: "wuwa-pc", version: "3.7.0", kind: "file", size: totals["3.7.0"] });
  });
});
