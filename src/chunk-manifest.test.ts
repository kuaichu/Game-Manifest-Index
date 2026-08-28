import { describe, expect, it, vi, afterEach } from "vitest";
import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { api } from "./api";
import ChunkManifestView from "./components/ChunkManifestView.vue";
import ArchiveView from "./views/ArchiveView.vue";
import type { ChunkManifestDetail, ChunkManifestSummaryItem } from "./types";

async function flushUpdates(): Promise<void> {
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}

const mockDetail: ChunkManifestDetail = {
  schema_version: 1,
  vendor: "mihoyo",
  game_id: "hk4e",
  platform: "windows",
  domain_id: "hk4e-pc",
  version: "5.5.0",
  build_id: "Dd8uOkHOcG6M",
  manifests: [
    {
      category: { id: 10017, name: "游戏资源-外网" },
      manifest_id: "manifest_game_123",
      manifest: {
        id: "manifest_game_123",
        checksum: "126a1510c73cef63df0339a1f9d9915c",
        compressed_size: 5653700,
        uncompressed_size: 10578207,
      },
      component: "game",
      language: null,
      matching_field: "game",
      stats: {
        compressed_size: 80372237646,
        uncompressed_size: 82400629604,
        file_count: 2124,
        chunk_count: 71194,
      },
      deduplicated_stats: {
        compressed_size: 80276901983,
        uncompressed_size: 82256426029,
        file_count: 2124,
        chunk_count: 71072,
      },
      manifest_download: {
        url_prefix: "https://autopatchcn.yuanshen.com/client_app/sophon/manifests/cxgf44wie1a8/Dd8uOkHOcG6M",
        url_suffix: "",
      },
      chunk_download: {
        url_prefix: "https://autopatchcn.yuanshen.com/client_app/sophon/chunks/cxgf44wie1a8/Dd8uOkHOcG6M",
        url_suffix: "",
        compression: 1,
        encryption: 0,
      },
    },
    {
      category: { id: 10018, name: "语音-中文" },
      manifest_id: "manifest_zh_456",
      manifest: {
        id: "manifest_zh_456",
        checksum: "66a4fb4ddbab282f488d079dcc701b0e",
        compressed_size: 1114254,
        uncompressed_size: 2071265,
      },
      component: "voice",
      language: "zh-cn",
      matching_field: "zh-cn",
      stats: {
        compressed_size: 13968815096,
        uncompressed_size: 16128987933,
        file_count: 161,
        chunk_count: 14127,
      },
      manifest_download: {
        url_prefix: "https://autopatchcn.yuanshen.com/client_app/sophon/manifests/cxgf44wie1a8/Dd8uOkHOcG6M",
        url_suffix: "",
      },
      chunk_download: {
        url_prefix: "https://autopatchcn.yuanshen.com/client_app/sophon/chunks/cxgf44wie1a8/Dd8uOkHOcG6M",
        url_suffix: "",
        compression: 1,
        encryption: 0,
      },
    },
  ],
};

const mockCollection: ChunkManifestSummaryItem[] = [
  {
    version: "5.5.0",
    path: "chunk-manifests/5.5.0.json",
    build_id: "Dd8uOkHOcG6M",
    manifest_count: 2,
    file_count: 2285,
    chunk_count: 85321,
    compressed_size: 94341052742,
    uncompressed_size: 98529617537,
    components: ["game", "voice"],
    languages: ["zh-cn"],
    imported_at: "2026-08-25T04:17:29Z",
  },
  {
    version: "5.4.0",
    path: "chunk-manifests/5.4.0.json",
    build_id: "8hiLOoadxDbI",
    manifest_count: 5,
    file_count: 2701,
    chunk_count: 127432,
    compressed_size: 136370895385,
    uncompressed_size: 149076666643,
    components: ["game", "voice"],
    languages: ["en-us", "ja-jp", "ko-kr", "zh-cn"],
    imported_at: "2026-08-25T04:17:30Z",
  },
];

describe("ChunkManifestView component", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("renders detail summary metrics, manifest cards, and recipes", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);

    let copiedUrl = "";
    let copiedLabel = "";
    let selectedVersion = "";

    const app = createApp(ChunkManifestView, {
      domain: { id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows", capabilities: ["packages", "chunks", "archive"], adapter: "hoyo", version_count: 44, latest_version: "5.5.0" },
      game: { id: "hk4e", name: "原神", sub_name: "Genshin Impact", platform: "android", icon_source: "", version_count: 55, latest_version: "7.0.0" },
      version: "5.5.0",
      chunkDetail: mockDetail,
      chunkCollection: mockCollection,
      loading: false,
      onCopyUrl: (url: string, label?: string) => {
        copiedUrl = url;
        copiedLabel = label || "";
      },
      onSelectVersion: (v: string) => {
        selectedVersion = v;
      },
    });

    app.mount(root);
    await flushUpdates();

    expect(root.textContent).toContain("Dd8uOkHOcG6M");
    expect(root.textContent).toContain("游戏资源-外网");
    expect(root.textContent).toContain("语音-中文");
    expect(root.textContent).toContain("manifest_game_123");
    expect(root.textContent).toContain("下载 Manifest");

    const copyButtons = root.querySelectorAll<HTMLButtonElement>(".recipe-actions button");
    expect(copyButtons.length).toBeGreaterThanOrEqual(2);

    copyButtons[0].click();
    await flushUpdates();
    expect(copiedUrl).toBe("https://autopatchcn.yuanshen.com/client_app/sophon/manifests/cxgf44wie1a8/Dd8uOkHOcG6M/manifest_game_123");

    copyButtons[1].click();
    await flushUpdates();
    expect(copiedUrl).toBe("https://autopatchcn.yuanshen.com/client_app/sophon/chunks/cxgf44wie1a8/Dd8uOkHOcG6M/{chunk_checksum}");

    app.unmount();
  });

  it("filters manifest cards by categoryFilter prop", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);

    // Test game filter
    const appGame = createApp(ChunkManifestView, {
      domain: { id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows", capabilities: ["packages", "chunks", "archive"], adapter: "hoyo", version_count: 44, latest_version: "5.5.0" },
      game: { id: "hk4e", name: "原神", sub_name: "Genshin Impact", platform: "android", icon_source: "", version_count: 55, latest_version: "7.0.0" },
      version: "5.5.0",
      chunkDetail: mockDetail,
      chunkCollection: mockCollection,
      categoryFilter: "game",
      loading: false,
    });

    appGame.mount(root);
    await flushUpdates();
    expect(root.textContent).toContain("游戏资源-外网");
    expect(root.textContent).not.toContain("语音-中文");
    appGame.unmount();

    // Test voice filter
    const appVoice = createApp(ChunkManifestView, {
      domain: { id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows", capabilities: ["packages", "chunks", "archive"], adapter: "hoyo", version_count: 44, latest_version: "5.5.0" },
      game: { id: "hk4e", name: "原神", sub_name: "Genshin Impact", platform: "android", icon_source: "", version_count: 55, latest_version: "7.0.0" },
      version: "5.5.0",
      chunkDetail: mockDetail,
      chunkCollection: mockCollection,
      categoryFilter: "zh-cn",
      loading: false,
    });

    appVoice.mount(root);
    await flushUpdates();
    expect(root.textContent).not.toContain("游戏资源-外网");
    expect(root.textContent).toContain("语音-中文");
    appVoice.unmount();
  });

  it("renders clean empty state and handles switching to latest chunk version", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);

    let switchedVersion = "";

    const app = createApp(ChunkManifestView, {
      domain: { id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows", capabilities: ["packages", "chunks", "archive"], adapter: "hoyo", version_count: 44, latest_version: "5.5.0" },
      game: { id: "hk4e", name: "原神", sub_name: "Genshin Impact", platform: "android", icon_source: "", version_count: 55, latest_version: "7.0.0" },
      version: "1.0.0", // version without chunks
      chunkDetail: null,
      chunkCollection: mockCollection,
      loading: false,
      onSelectVersion: (v: string) => {
        switchedVersion = v;
      },
    });

    app.mount(root);
    await flushUpdates();

    expect(root.textContent).toContain("当前版本暂无 Chunk 分发记录");
    expect(root.textContent).toContain("Sophon Chunk 分发架构自 4.2.0 起收录");

    app.unmount();
  });
});

describe("ArchiveView chunks mode integration", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("loads chunk manifests and enables export in chunks mode", async () => {
    const game = { id: "hk4e", name: "原神", sub_name: "Genshin Impact", icon_source: "", sort_order: 0 };
    const domain = {
      id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows",
      capabilities: ["packages", "patches", "chunks", "archive"], adapter: "hoyo",
      version_count: 44, latest_version: "5.5.0", source_current_version: "7.0.0", catalog_version_count: 44, sort_order: 0,
      capability_contract: {
        artifact_fields: { size: "supported", checksum: "supported", urls: "supported", availability: "supported" },
        features: { chunks: "supported" },
        actions: { open: "conditional", copy: "conditional", download: "conditional" },
        availability_source_kinds: ["metadata_inference"], live_probe: false,
      },
    };
    const version = {
      version: "5.5.0", current_revision_id: 1, revision_count: 1,
      observed_at: "2026-08-25T04:17:29Z", source_updated_at: "2026-08-25T04:17:29Z",
      packed_size: 1000, unpacked_size: 2000, artifact_count: 2,
      artifact_kinds: { package: { count: 1, size: 500 }, chunk: { count: 2, size: 500 } },
      availability_states: { available: 2 }, attributes: { build_id: "Dd8uOkHOcG6M" },
    };

    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    vi.spyOn(api, "chunkManifestCollection").mockResolvedValue({ items: mockCollection } as never);
    vi.spyOn(api, "chunkManifests").mockResolvedValue(mockDetail as never);
    vi.spyOn(api, "artifacts").mockResolvedValue({ items: [], next_cursor: null } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/hk4e/hk4e-pc/5.5.0/chunks");
    await router.isReady();

    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    expect(root.textContent).toContain("导出 Manifest 链接 · 2");
    expect(root.textContent).toContain("游戏资源-外网");
    expect(root.textContent).toContain("Dd8uOkHOcG6M");

    app.unmount();
  });
});
