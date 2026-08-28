import { createApp, nextTick, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import ArchiveView from "./views/ArchiveView.vue";

async function flush(): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

describe("WuWa file-manifest package and patch cards", () => {
  let app: App | null = null;

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
});
