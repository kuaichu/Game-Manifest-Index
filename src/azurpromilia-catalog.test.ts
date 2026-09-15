import { createApp, nextTick, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import ArchiveView from "./views/ArchiveView.vue";
import { publisherGroups } from "./game-meta";

async function flush(): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

describe("Azur Promilia generic file-manifest catalog", () => {
  let app: App | null = null;

  afterEach(() => {
    app?.unmount();
    app = null;
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("shows the unknown game, paginates packages, and browses the file manifest", async () => {
    const iconUrl = "https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/8e/6f/71/8e6f710c-03f5-9a08-870d-ebb5f9ebc221/AppIcon-0-0-1x_U007emarketing-0-8-0-85-220.png/512x512bb.jpg";
    const game = {
      id: "azurpromilia",
      name: "蓝色星原：旅谣",
      sub_name: "Azur Promilia",
      platform: "windows",
      icon_source: iconUrl,
      version_count: 1,
      latest_version: "0.3.0.6",
      sort_order: 12,
    };
    expect(publisherGroups([game]).map((group) => group.publisher)).toEqual(["蛮啾网络"]);
    const domain = {
      id: "azurpromilia-pc",
      game_id: "azurpromilia",
      kind: "files",
      platform: "windows",
      capabilities: ["packages", "files", "archive"],
      adapter: "generic",
      version_count: 1,
      latest_version: "0.3.0.6",
      capability_contract: {
        artifact_fields: { size: "supported", checksum: "supported", urls: "supported", availability: "supported" },
        url_source_kinds: ["official"],
        checksum_algorithms: ["md5"],
        availability_source_kinds: ["metadata_inference"],
        actions: { download: "conditional" },
        live_probe: false,
      },
    };
    const version = {
      version: "0.3.0.6",
      current_revision_id: 1,
      revision_count: 1,
      observed_at: null,
      packed_size: 142235777925,
      unpacked_size: 77865464813,
      artifact_count: 645,
      artifact_kinds: {
        package: { count: 645, size: 142235777925, availability_states: { unknown: 645 } },
      },
      availability_states: { unknown: 645 },
      attributes: {},
      provenance: { source_kind: "official_sync" },
    };
    const packageArtifact = (name: string, id: number) => ({
      id,
      kind: "package",
      name,
      part: id,
      size: 100,
      checksum_type: "md5",
      checksum_value: "a".repeat(32),
      attributes: { component: "game", package_type: id === 1 ? "full" : "segment", delivery_mode: id === 1 ? "file_manifest" : "direct" },
      urls: [{ id, url: `https://syncstation.manjuu.com/${name}`, priority: 0, source_kind: "official", provider: "manjuu", evidence_status: "unverified", current: null }],
    });
    const rootFiles = {
      source: "package",
      fetch_mode: "checked_in_manifest",
      identity: "1",
      path: "",
      q: null,
      items: [
        { type: "directory", name: "AzurPromilia_Data", path: "AzurPromilia_Data", file_count: 34736, size: 77800000000 },
        { type: "file", name: "AzurPromilia.exe", path: "AzurPromilia.exe", size: 807528, md5: "b".repeat(32), download_url: "https://syncstation.manjuu.com/target/AzurPromilia.exe" },
      ],
      total: 100,
      next_cursor: null,
      totals: { files: 34758, directories: 3, size: 77865464813 },
    };
    const searchFiles = {
      ...rootFiles,
      q: "AzurPromilia.exe",
      items: [rootFiles.items[1]],
      total: 1,
      totals: { files: 1, directories: 0, size: 807528 },
    };
    const detail = {
      source: "package",
      fetch_mode: "checked_in_manifest",
      identity: "1",
      ...rootFiles.items[1],
    };

    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    const artifacts = vi.spyOn(api, "artifacts").mockImplementation(async (_domainId, _version, options) => ({
      items: [packageArtifact(options.cursor ? "pg_chunk.0001" : "AzurPromilia-0.3.0.6-pg_item_v2", options.cursor ? 2 : 1)],
      next_cursor: options.cursor ? null : "next",
      total: 100,
    } as never));
    const versionFiles = vi.spyOn(api, "versionFiles").mockImplementation(async (_domainId, _version, params) => (
      (params?.q ? searchFiles : rootFiles) as never
    ));
    const versionFileDetail = vi.spyOn(api, "versionFileDetail").mockResolvedValue(detail as never);
    const chunkCollection = vi.spyOn(api, "chunkManifestCollection").mockRejectedValue(new Error("generic files must not load chunks"));
    const chunkManifests = vi.spyOn(api, "chunkManifests").mockRejectedValue(new Error("generic files must not load chunks"));

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/azurpromilia/azurpromilia-pc/0.3.0.6/packages");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flush();
    await flush();

    expect(root.textContent).toContain("蓝色星原：旅谣");
    expect(root.querySelector(`img[src="${iconUrl}"]`)).not.toBeNull();
    expect(root.textContent).toContain("AzurPromilia-0.3.0.6-pg_item_v2");
    expect(root.textContent).not.toContain("无证据");
    expect(root.querySelector<HTMLAnchorElement>('a.icon-button[href="https://syncstation.manjuu.com/AzurPromilia-0.3.0.6-pg_item_v2"]')).not.toBeNull();
    expect(root.querySelector("button.is-locked")).toBeNull();
    const pageTwo = Array.from(root.querySelectorAll<HTMLButtonElement>(".artifact-page-button"))
      .find((button) => button.textContent?.trim() === "2");
    expect(pageTwo).not.toBeUndefined();
    pageTwo?.click();
    await flush();
    expect(artifacts.mock.calls.some(([, , options]) => options.cursor === "50")).toBe(true);
    expect(root.textContent).toContain("pg_chunk.0001");

    await router.push("/games/azurpromilia/azurpromilia-pc/0.3.0.6/files");
    await flush();
    await flush();
    expect(root.textContent).toContain("AzurPromilia_Data");
    expect(root.textContent).toContain("34758");
    expect(chunkCollection).not.toHaveBeenCalled();
    expect(chunkManifests).not.toHaveBeenCalled();

    const search = root.querySelector<HTMLInputElement>(".search-box input");
    expect(search).not.toBeNull();
    search!.value = "AzurPromilia.exe";
    search!.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((resolve) => window.setTimeout(resolve, 220));
    await flush();
    expect(versionFiles.mock.calls.some(([, , params]) => params?.q === "AzurPromilia.exe")).toBe(true);
    const fileRow = root.querySelector(".cfb-grid-row.row-is-file") as HTMLElement;
    expect(fileRow.textContent).toContain("AzurPromilia.exe");
    fileRow.click();
    await flush();
    expect(versionFileDetail).toHaveBeenCalled();
    expect(document.body.textContent).toContain("官方完整文件");
    expect(document.body.textContent).toContain("立即下载");
  });
});
