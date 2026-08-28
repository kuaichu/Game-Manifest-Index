import { createApp, nextTick, type App } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import ArchiveView from "./views/ArchiveView.vue";

const originalClipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const originalExecCommandDescriptor = Object.getOwnPropertyDescriptor(document, "execCommand");

const chunkUrl = "https://autopatchcn.bh3.com/chunk/manifest-1";

async function flushUpdates(): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

function stubClipboard(value: Clipboard | undefined): void {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value });
}

function stubExecCommand(value: Document["execCommand"]): void {
  Object.defineProperty(document, "execCommand", { configurable: true, value });
}

function restoreClipboardMocks(): void {
  if (originalClipboardDescriptor) {
    Object.defineProperty(navigator, "clipboard", originalClipboardDescriptor);
  } else {
    Reflect.deleteProperty(navigator, "clipboard");
  }
  if (originalExecCommandDescriptor) {
    Object.defineProperty(document, "execCommand", originalExecCommandDescriptor);
  } else {
    Reflect.deleteProperty(document, "execCommand");
  }
}

async function mountCopyableChunkArchive(): Promise<{ app: App; root: HTMLDivElement }> {
  const game = { id: "bh3", name: "崩坏3", sub_name: "Honkai Impact 3rd", icon_source: "", sort_order: 0 };
  const domain = {
    id: "bh3-pc", game_id: "bh3", kind: "mixed", platform: "windows",
    capabilities: ["packages", "chunks", "archive"], adapter: "hoyo",
    version_count: 55, latest_version: "8.9.0", source_current_version: "8.9.0", catalog_version_count: 55, sort_order: 0,
    capability_contract: {
      artifact_fields: { size: "supported", checksum: "supported", urls: "supported", provider: "supported", availability: "supported" },
      features: { chunks: "supported", chunk_pagination: "supported", history: "supported" },
      actions: { open: "conditional", copy: "conditional", download: "conditional" },
      availability_source_kinds: ["metadata_inference"], live_probe: false,
    },
  };
  const version = {
    version: "8.9.0", current_revision_id: 1, revision_count: 1,
    observed_at: "2026-07-11T03:30:47Z", source_updated_at: "2026-07-11T03:30:47Z", imported_at: "2026-07-31T00:00:00Z",
    packed_size: 100, unpacked_size: 120, artifact_count: 1,
    artifact_kinds: { chunk: { count: 1, size: 100, availability_states: { unknown: 1 } } },
    availability_states: { unknown: 1 }, attributes: { build_id: "build-1", chunk_file_count: 10, chunk_count: 20 }, provenance: {},
  };
  const chunk = {
    id: 1, kind: "chunk", name: "游戏资源-外网（新）", part: 1, size: 100,
    checksum_type: "md5", checksum_value: "1".repeat(32),
    attributes: { manifest_id: "manifest-1", matching_field: "game", file_count: 10, chunk_count: 20 },
    urls: [{
      id: 1, url: chunkUrl, priority: 0,
      source_kind: "official", provider: "autopatchcn.bh3.com", evidence_status: "no_evidence", current: null,
    }],
  };
  vi.spyOn(api, "games").mockResolvedValue([game] as never);
  vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
  vi.spyOn(api, "versions").mockResolvedValue([version] as never);
  vi.spyOn(api, "artifacts").mockResolvedValue({ items: [chunk], next_cursor: null } as never);

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
  });
  await router.push("/games/bh3/bh3-pc/8.9.0/chunks");
  await router.isReady();
  const root = document.createElement("div");
  document.body.appendChild(root);
  const app = createApp(ArchiveView);
  app.use(router);
  app.mount(root);
  await flushUpdates();
  await flushUpdates();
  return { app, root };
}

describe("archive copy actions", () => {
  let mountedApp: App | null = null;

  afterEach(() => {
    mountedApp?.unmount();
    mountedApp = null;
    vi.restoreAllMocks();
    restoreClipboardMocks();
    document.body.innerHTML = "";
  });

  it("falls back to a temporary textarea when copying on pages without the clipboard API", async () => {
    const execCommand = vi.fn().mockReturnValue(true);
    stubClipboard(undefined);
    stubExecCommand(execCommand);
    const { app, root } = await mountCopyableChunkArchive();
    mountedApp = app;

    (root.querySelector(".chunk-card button.icon-button") as HTMLButtonElement).click();
    await flushUpdates();

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(root.textContent).toContain("链接已复制");
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("uses navigator.clipboard first and shows a success toast", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const execCommand = vi.fn();
    stubClipboard({ writeText } as unknown as Clipboard);
    stubExecCommand(execCommand);
    const { app, root } = await mountCopyableChunkArchive();
    mountedApp = app;

    (root.querySelector(".chunk-card button.icon-button") as HTMLButtonElement).click();
    await flushUpdates();

    expect(writeText).toHaveBeenCalledWith(chunkUrl);
    expect(execCommand).not.toHaveBeenCalled();
    expect(root.textContent).toContain("链接已复制");
  });

  it("shows a manual-copy toast when clipboard and fallback copy both fail", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const execCommand = vi.fn().mockReturnValue(false);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubClipboard({ writeText } as unknown as Clipboard);
    stubExecCommand(execCommand);
    const { app, root } = await mountCopyableChunkArchive();
    mountedApp = app;

    (root.querySelector(".chunk-card button.icon-button") as HTMLButtonElement).click();
    await flushUpdates();

    expect(writeText).toHaveBeenCalledWith(chunkUrl);
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(root.textContent).toContain("复制失败，请手动复制");
    expect(consoleError).not.toHaveBeenCalled();
    expect(document.querySelector("textarea")).toBeNull();
  });
});
