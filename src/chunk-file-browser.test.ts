import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h, nextTick, ref } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { api } from "./api";
import ChunkFileBrowser from "./components/ChunkFileBrowser.vue";
import * as chunkDownload from "./chunk-download";
import * as directoryDownload from "./chunk-directory-download";
import type { ChunkFileDetail, ChunkFilesPage, ChunkManifestDetail, FileTimeChange } from "./types";

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
  it("emits source and identity dates and rejects obsolete identity and version responses", async () => {
    const pending: Array<{ resolve: (page: ChunkFilesPage) => void }> = [];
    vi.spyOn(api, "versionFiles").mockImplementation(() => new Promise((resolve) => pending.push({ resolve })));
    const dates: FileTimeChange[] = [];
    const version = ref("7.0.0");
    const host = document.createElement("div");
    document.body.appendChild(host);
    const router = createTestRouter();
    await router.push("/"); await router.isReady();
    const app = createApp({ setup: () => () => h(ChunkFileBrowser, {
      domainId: "hk4e-pc", version: version.value, game: null, domain: null, chunkDetail: mockDetail,
      versionSummary: { version: version.value, current_revision_id: 1, revision_count: 1, observed_at: null,
        packed_size: 0, unpacked_size: 0, artifact_count: 3, availability_states: {}, attributes: {},
        artifact_kinds: { package: { count: 1, size: 0 }, chunk: { count: 2, size: 0 } } },
      onFileTimeChange: (event: FileTimeChange) => dates.push(event),
    }) });
    app.use(router); app.mount(host); await flushUpdates();
    expect(dates.at(-1)).toMatchObject({ source: "package", identity: "game", fileTime: null, loading: true });
    pending[0].resolve({ ...mockPackageFiles, file_time: "2026-09-01T00:00:00Z", file_time_source: "package" });
    await flushUpdates();
    expect(dates.at(-1)).toMatchObject({ source: "package", fileTime: "2026-09-01T00:00:00Z", timeSource: "package" });
    (host.querySelectorAll<HTMLButtonElement>(".cfb-source-switch-group button")[1]).click(); await flushUpdates();
    expect(dates.at(-1)).toMatchObject({ source: "chunk", identity: "game", fileTime: null, loading: true });
    (host.querySelectorAll<HTMLButtonElement>(".cfb-identity-chips button")[1]).click(); await flushUpdates();
    pending[1].resolve({ ...mockChunkFiles, file_time: "2026-09-02T00:00:00Z", file_time_source: "manifest" });
    await flushUpdates();
    expect(dates.at(-1)?.loading).toBe(true);
    pending[2].resolve({ ...mockChunkFiles, identity: "zh-cn", file_time: "2026-09-03T00:00:00Z", file_time_source: "manifest" });
    await flushUpdates();
    expect(dates.at(-1)).toMatchObject({ source: "chunk", identity: "zh-cn", fileTime: "2026-09-03T00:00:00Z" });
    version.value = "7.1.0"; await flushUpdates();
    expect(dates.at(-1)).toMatchObject({ version: "7.1.0", fileTime: null, loading: true });
    app.unmount(); host.remove();
    pending[3].resolve({ ...mockChunkFiles, file_time: "2026-09-04T00:00:00Z", file_time_source: "manifest" });
    await flushUpdates();
    expect(dates.at(-1)?.loading).toBe(true);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
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
    expect(dialog?.textContent).toContain("下载完整文件");
    const synthesis = vi.spyOn(chunkDownload, "synthesizeChunkFile").mockResolvedValue(new Blob(["restored"]));
    const save = vi.spyOn(chunkDownload, "saveBlob").mockImplementation(() => undefined);
    const downloadButton = [...dialog!.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("下载完整文件"))!;
    downloadButton.click();
    await flushUpdates();
    expect(synthesis).toHaveBeenCalledWith(expect.objectContaining({ chunk_download: mockDetail.manifests[0].chunk_download }), expect.any(AbortSignal), expect.any(Function), expect.any(Function));
    const makeUrl = synthesis.mock.calls[0][3]!;
    expect(makeUrl(mockFileDetail.chunks![0])).toContain("identity=game");
    expect(save).toHaveBeenCalledWith(expect.any(Blob), "YuanShen.exe");

    // Close modal
    const closeBtn = dialog?.querySelector(".cfb-modal-close") as HTMLElement;
    closeBtn.click();
    await flushUpdates();

    expect(document.body.querySelector(".cfb-modal-card")).toBeNull();

    app.unmount();
    host.remove();
  });

  it("streams files larger than the Blob limit using a save picker", async () => {
    vi.spyOn(api, "versionFiles").mockResolvedValue(mockChunkFiles);
    vi.spyOn(api, "versionFileDetail").mockResolvedValue({ ...mockFileDetail, size: 600 * 1024 * 1024 });
    const writable = { write: vi.fn(), close: vi.fn(), abort: vi.fn() };
    const picker = vi.fn().mockResolvedValue({ createWritable: vi.fn().mockResolvedValue(writable) });
    vi.stubGlobal("showSaveFilePicker", picker);
    const stream = vi.spyOn(chunkDownload, "writeChunkFile").mockResolvedValue(undefined);
    const synthesis = vi.spyOn(chunkDownload, "synthesizeChunkFile");
    const host = document.createElement("div");
    document.body.appendChild(host);
    const router = createTestRouter();
    await router.push("/");
    await router.isReady();
    const app = createApp(ChunkFileBrowser, { domainId: "hk4e-pc", version: "7.0.0", game: null, domain: null, chunkDetail: mockDetail });
    app.use(router);
    app.mount(host);
    await flushUpdates();
    (host.querySelector(".row-is-file") as HTMLElement).click();
    await flushUpdates();
    const button = [...document.body.querySelectorAll<HTMLButtonElement>(".cfb-modal-card button")].find((item) => item.textContent?.includes("下载完整文件"))!;
    button.click();
    await flushUpdates();
    expect(picker).toHaveBeenCalledWith({ suggestedName: "YuanShen.exe" });
    expect(stream).toHaveBeenCalledWith(expect.objectContaining({ size: 600 * 1024 * 1024 }), writable, expect.any(AbortSignal), expect.any(Function), expect.any(Function));
    expect(synthesis).not.toHaveBeenCalled();
    app.unmount();
    host.remove();
  });

  it("downloads selected full components independently of the current search", async () => {
    vi.spyOn(api, "versionFiles").mockResolvedValue(mockChunkFiles);
    const directory = { getDirectoryHandle: vi.fn(), getFileHandle: vi.fn() };
    const picker = vi.fn().mockResolvedValue(directory);
    vi.stubGlobal("showDirectoryPicker", picker);
    const download = vi.spyOn(directoryDownload, "downloadChunkDirectory").mockResolvedValue({ directoryName: "hk4e-7.0.0", files: 7, bytes: 2800 });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const router = createTestRouter();
    await router.push("/");
    await router.isReady();
    const app = createApp(ChunkFileBrowser, { domainId: "hk4e-pc", version: "7.0.0", game: null, domain: null, chunkDetail: mockDetail, searchQuery: "only-one-file" });
    app.use(router);
    app.mount(host);
    await flushUpdates();
    (host.querySelector(".cfb-directory-toggle") as HTMLButtonElement).click();
    await flushUpdates();
    const checkboxes = host.querySelectorAll<HTMLInputElement>(".cfb-directory-components input");
    expect([...checkboxes].map((item) => item.checked)).toEqual([true, true]);
    checkboxes[1].click();
    await flushUpdates();
    (host.querySelector(".cfb-directory-actions .dl-btn") as HTMLButtonElement).click();
    await flushUpdates();
    expect(picker).toHaveBeenCalledWith({ mode: "readwrite" });
    expect(download).toHaveBeenCalledWith(expect.objectContaining({ domainId: "hk4e-pc", version: "7.0.0", identities: ["game"], root: directory }));
    expect(download.mock.calls[0][0]).not.toHaveProperty("q");
    expect(host.textContent).toContain("已保存 7 个文件");
    app.unmount();
    host.remove();
  });

  it("cancels directory writes on a version change and ignores old completion", async () => {
    vi.spyOn(api, "versionFiles").mockResolvedValue(mockChunkFiles);
    vi.stubGlobal("showDirectoryPicker", vi.fn().mockResolvedValue({ getDirectoryHandle: vi.fn(), getFileHandle: vi.fn() }));
    let finish!: (value: directoryDownload.ChunkDirectoryDownloadResult) => void;
    const download = vi.spyOn(directoryDownload, "downloadChunkDirectory").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const version = ref("7.0.0");
    const host = document.createElement("div");
    document.body.appendChild(host);
    const router = createTestRouter();
    await router.push("/");
    await router.isReady();
    const app = createApp({ setup: () => () => h(ChunkFileBrowser, { domainId: "hk4e-pc", version: version.value, game: null, domain: null, chunkDetail: mockDetail }) });
    app.use(router);
    app.mount(host);
    await flushUpdates();
    (host.querySelector(".cfb-directory-toggle") as HTMLButtonElement).click();
    await flushUpdates();
    (host.querySelector(".cfb-directory-actions .dl-btn") as HTMLButtonElement).click();
    await flushUpdates();
    const oldSignal = download.mock.calls[0][0].signal;
    version.value = "7.1.0";
    await flushUpdates();
    expect(oldSignal.aborted).toBe(true);
    finish({ directoryName: "old-version", files: 7, bytes: 2800 });
    await flushUpdates();
    (host.querySelector(".cfb-directory-toggle") as HTMLButtonElement).click();
    await flushUpdates();
    expect(host.textContent).not.toContain("old-version");
    expect(host.querySelector<HTMLButtonElement>(".cfb-directory-actions .dl-btn")?.disabled).toBe(false);
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
