import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { api } from "./api";
import ChunkFileBrowser from "./components/ChunkFileBrowser.vue";
import type { ChunkFileDetail, ChunkFilesPage, ChunkManifestDetail } from "./types";

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
  version: "7.0.0",
  build_id: "test_build_123",
  manifests: [
    {
      category: { id: 10017, name: "游戏主资源" },
      manifest_id: "manifest_game_123",
      manifest: { id: "manifest_game_123", checksum: "abc", compressed_size: 100, uncompressed_size: 200 },
      component: "game",
      language: null,
      matching_field: "game",
      stats: { compressed_size: 1000, uncompressed_size: 2000, file_count: 5, chunk_count: 10 },
      chunk_download: {
        url_prefix: "https://autopatchcn.yuanshen.com/client_app/sophon/chunks/test/build",
        url_suffix: "",
      },
    },
    {
      category: { id: 10018, name: "中文语音包" },
      manifest_id: "manifest_zh_123",
      manifest: { id: "manifest_zh_123", checksum: "def", compressed_size: 50, uncompressed_size: 80 },
      component: "voice",
      language: "zh-cn",
      matching_field: "zh-cn",
      stats: { compressed_size: 500, uncompressed_size: 800, file_count: 2, chunk_count: 4 },
      chunk_download: {
        url_prefix: "https://autopatchcn.yuanshen.com/client_app/sophon/chunks/test/build_zh",
        url_suffix: "",
      },
    },
  ],
};

const mockChunkFiles: ChunkFilesPage = {
  source: "chunk_manifest",
  identity: "game",
  path: "",
  q: null,
  items: [
    { type: "directory", name: "YuanShen_Data", path: "YuanShen_Data", file_count: 4, size: 2048000 },
    { type: "file", name: "YuanShen.exe", path: "YuanShen.exe", size: 431085976, hash: "e1114eb3dd032ff9162fbd97e252f717", chunk_count: 308 },
  ],
  total: 2,
  next_cursor: null,
  totals: { files: 1, directories: 1, size: 433133976 },
};

const mockPackageFiles: ChunkFilesPage = {
  source: "package_pkg_version",
  fetch_mode: "official_scattered_files",
  identity: "game",
  path: "",
  q: null,
  items: [
    { type: "directory", name: "YuanShen_Data", path: "YuanShen_Data", file_count: 16000, size: 76686757576 },
    {
      type: "file",
      name: "YuanShen.exe",
      path: "YuanShen.exe",
      size: 5382648,
      md5: "55d27e108ff16e2fcdd8bade44431e1d",
      download_url: "https://autopatchcn.yuanshen.com/client_app/download/pc_zip/YuanShen.exe",
    },
  ],
  total: 2,
  next_cursor: null,
  totals: { files: 1, directories: 1, size: 76692140224 },
  network_bytes: 0,
};

const mockSubfolderFiles: ChunkFilesPage = {
  source: "chunk_manifest",
  identity: "game",
  path: "YuanShen_Data",
  q: null,
  items: [
    { type: "file", name: "global-metadata.dat", path: "YuanShen_Data/global-metadata.dat", size: 1024, hash: "abc123md5", chunk_count: 1 },
  ],
  total: 1,
  next_cursor: null,
  totals: { files: 1, directories: 0, size: 1024 },
};

const mockFileDetail: ChunkFileDetail = {
  source: "chunk_manifest",
  identity: "game",
  name: "YuanShen.exe",
  path: "YuanShen.exe",
  size: 431085976,
  hash: "e1114eb3dd032ff9162fbd97e252f717",
  chunk_count: 2,
  chunks: [
    { name: "chunk_1", hash: "hash_chunk_1", offset: 0, size: 1000, size_decompressed: 2000 },
    { name: "chunk_2", hash: "hash_chunk_2", offset: 2000, size: 1500, size_decompressed: 3000 },
  ],
};

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div />" } }],
  });
}

describe("ChunkFileBrowser", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders identities, folder rows, file rows, and breadcrumbs in chunk mode", async () => {
    const versionFilesMock = vi.spyOn(api, "versionFiles").mockResolvedValue(mockChunkFiles);

    const host = document.createElement("div");
    document.body.appendChild(host);

    const router = createTestRouter();
    await router.push("/");
    await router.isReady();

    const app = createApp(ChunkFileBrowser, {
      domainId: "hk4e-pc",
      version: "7.0.0",
      game: { id: "hk4e", name: "原神", publisher: "mihoyo", is_enabled: true },
      domain: { id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows", capabilities: ["files"], adapter: "hoyo", version_count: 56, latest_version: "7.0.0" },
      chunkDetail: mockDetail,
      versionSummary: {
        version: "7.0.0",
        artifact_count: 5,
        packed_size: 182872375187,
        artifact_kinds: { chunk: { count: 5, size: 182872375187 } },
      },
    });
    app.use(router);
    app.mount(host);

    await flushUpdates();

    expect(versionFilesMock).toHaveBeenCalledWith("hk4e-pc", "7.0.0", expect.objectContaining({ source: "chunk", identity: "game" }), expect.any(AbortSignal));
    expect(host.textContent).toContain("游戏主资源");
    expect(host.textContent).toContain("中文语音包");
    expect(host.textContent).toContain("YuanShen_Data");
    expect(host.textContent).toContain("YuanShen.exe");
    expect(host.textContent).toContain("e1114eb3dd032ff9162fbd97e252f717");
    expect(host.textContent).toContain("308 块");

    app.unmount();
    host.remove();
  });

  it("defaults to package source and shows download url when package is available", async () => {
    const versionFilesMock = vi.spyOn(api, "versionFiles").mockResolvedValue(mockPackageFiles);

    const host = document.createElement("div");
    document.body.appendChild(host);

    const router = createTestRouter();
    await router.push("/");
    await router.isReady();

    const app = createApp(ChunkFileBrowser, {
      domainId: "hk4e-pc",
      version: "4.5.0",
      game: null,
      domain: { id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows", capabilities: ["packages", "files"], adapter: "hoyo", version_count: 56, latest_version: "7.0.0" },
      chunkDetail: mockDetail,
      versionSummary: {
        version: "4.5.0",
        artifact_count: 22,
        packed_size: 136325318117,
        artifact_kinds: {
          package: { count: 12, size: 136325318117 },
          chunk: { count: 5, size: 127759732042 },
        },
      },
    });
    app.use(router);
    app.mount(host);

    await flushUpdates();

    expect(versionFilesMock).toHaveBeenCalledWith("hk4e-pc", "4.5.0", expect.objectContaining({ source: "package" }), expect.any(AbortSignal));
    expect(host.textContent).toContain("55d27e108ff16e2fcdd8bade44431e1d");
    expect(host.textContent).toContain("下载");
    expect(host.textContent).toContain("复制");
    expect(host.textContent).toContain("命中缓存");

    app.unmount();
    host.remove();
  });

  it("navigates into directory on click and updates breadcrumbs", async () => {
    const versionFilesMock = vi.spyOn(api, "versionFiles")
      .mockResolvedValueOnce(mockChunkFiles)
      .mockResolvedValueOnce(mockSubfolderFiles);

    const host = document.createElement("div");
    document.body.appendChild(host);

    const router = createTestRouter();
    await router.push("/");
    await router.isReady();

    const app = createApp(ChunkFileBrowser, {
      domainId: "hk4e-pc",
      version: "7.0.0",
      game: null,
      domain: null,
      chunkDetail: mockDetail,
      versionSummary: {
        version: "7.0.0",
        artifact_count: 5,
        packed_size: 182872375187,
        artifact_kinds: { chunk: { count: 5, size: 182872375187 } },
      },
    });
    app.use(router);
    app.mount(host);

    await flushUpdates();

    const folderRow = host.querySelector(".row-is-dir") as HTMLElement;
    expect(folderRow).not.toBeNull();
    folderRow.click();

    await flushUpdates();

    expect(versionFilesMock).toHaveBeenLastCalledWith("hk4e-pc", "7.0.0", expect.objectContaining({ path: "YuanShen_Data" }), expect.any(AbortSignal));
    expect(host.textContent).toContain("global-metadata.dat");
    expect(host.textContent).toContain("上一级");

    app.unmount();
    host.remove();
  });

  it("opens file chunk detail modal and displays chunks list with download urls", async () => {
    vi.spyOn(api, "versionFiles").mockResolvedValue(mockChunkFiles);
    const detailMock = vi.spyOn(api, "versionFileDetail").mockResolvedValue(mockFileDetail);

    const host = document.createElement("div");
    document.body.appendChild(host);

    const router = createTestRouter();
    await router.push("/");
    await router.isReady();

    const app = createApp(ChunkFileBrowser, {
      domainId: "hk4e-pc",
      version: "7.0.0",
      game: null,
      domain: null,
      chunkDetail: mockDetail,
      versionSummary: {
        version: "7.0.0",
        artifact_count: 5,
        packed_size: 182872375187,
        artifact_kinds: { chunk: { count: 5, size: 182872375187 } },
      },
    });
    app.use(router);
    app.mount(host);

    await flushUpdates();

    const fileRow = host.querySelector(".row-is-file") as HTMLElement;
    fileRow.click();

    await flushUpdates();

    expect(detailMock).toHaveBeenCalledWith("hk4e-pc", "7.0.0", expect.objectContaining({ path: "YuanShen.exe" }), expect.any(AbortSignal));
    const dialog = document.body.querySelector(".cfb-modal-card");
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain("YuanShen.exe");
    expect(dialog?.textContent).toContain("hash_chunk_1");
    expect(dialog?.textContent).toContain("hash_chunk_2");
    expect(dialog?.textContent).toContain("复制");

    // Close modal
    const closeBtn = dialog?.querySelector(".cfb-modal-close") as HTMLElement;
    closeBtn.click();
    await flushUpdates();

    expect(document.body.querySelector(".cfb-modal-card")).toBeNull();

    app.unmount();
    host.remove();
  });

  it("displays friendly unavailable notice when version package is expired on CDN", async () => {
    vi.spyOn(api, "versionFiles").mockRejectedValue(new Error("package Range 请求失败"));

    const host = document.createElement("div");
    document.body.appendChild(host);

    const router = createTestRouter();
    await router.push("/");
    await router.isReady();

    const app = createApp(ChunkFileBrowser, {
      domainId: "hk4e-pc",
      version: "3.4.0",
      game: null,
      domain: { id: "hk4e-pc", game_id: "hk4e", kind: "packages", platform: "windows", capabilities: ["packages", "files"], adapter: "hoyo", version_count: 56, latest_version: "7.0.0" },
      chunkDetail: null,
      versionSummary: {
        version: "3.4.0",
        artifact_count: 20,
        packed_size: 47899622769,
        artifact_kinds: {
          package: {
            count: 10,
            size: 85308787919,
            availability_states: { available: 0, unavailable: 10, unknown: 0 },
          },
          patch: {
            count: 10,
            size: 5292432817,
            availability_states: { available: 8, unavailable: 2, unknown: 0 },
          },
        },
      },
    });
    app.use(router);
    app.mount(host);

    await flushUpdates();

    expect(host.textContent).toContain("官方资源已失效下架");
    expect(host.textContent).toContain("该版本的官方完整包下载链接已失效");

    app.unmount();
    host.remove();
  });
});
