import { createApp, h, nextTick, ref } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import ArtifactTree from "./components/ArtifactTree.vue";
import ComparePanel from "./components/ComparePanel.vue";
import RemoteArtifactTree from "./components/RemoteArtifactTree.vue";

async function flushUpdates(): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

describe("read-only product components", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("renders searched fragment files with standard grouped download actions and no URL status rows", async () => {
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ArtifactTree, { artifacts: [{
      id: 1, kind: "file", name: "Client/a.bin", part: 1, size: 10,
      checksum_type: "md5", checksum_value: "1".repeat(32), attributes: {},
      urls: [
        { id: 20, url: "https://cdn-b.example/a.bin", priority: 1, source_kind: "official", provider: "cdn-b.example", evidence_status: "no_evidence", current: null },
        { id: 30, url: "https://cdn-a.example/a.bin", priority: 0, source_kind: "official", provider: "cdn-a.example", evidence_status: "no_evidence", current: null },
        { id: 10, url: "https://cdn-c.example/a.bin", priority: 1, source_kind: "official", provider: "cdn-c.example", evidence_status: "no_evidence", current: null },
      ],
    }] });
    app.mount(root);
    (root.querySelector(".folder-card") as HTMLButtonElement).click();
    await nextTick();
    (root.querySelector(".fragment-file-row") as HTMLButtonElement).click();
    await nextTick();
    expect(root.textContent).toContain("a.bin");
    expect(root.textContent).toContain("1".repeat(32));
    expect(root.textContent).toContain("可用 / Client/a.bin");
    expect(root.textContent).toContain("复制官方入口");
    expect(root.textContent).toContain("官方入口");
    expect(root.textContent).toContain("CDN2");
    expect(root.textContent).toContain("CDN3");
    expect(Array.from(root.querySelectorAll<HTMLAnchorElement>(".fragment-file-actions a")).map((link) => link.href)).toEqual([
      "https://cdn-a.example/a.bin",
      "https://cdn-c.example/a.bin",
      "https://cdn-b.example/a.bin",
    ]);
    expect(root.textContent).not.toContain("cdn-a.example");
    expect(root.textContent).not.toContain("https://cdn-a.example/a.bin");
    expect(root.textContent).not.toContain("未验证");
    expect(root.textContent).not.toContain("不可操作");
    expect(root.querySelector(".availability")).toBeNull();
    app.unmount();
  });

  it("paginates comparisons with the server cursor", async () => {
    vi.spyOn(api, "compare")
      .mockResolvedValueOnce({
        from_version: "1", to_version: "2", summary: { added: 2, removed: 0, changed: 0, size_delta: 30 },
        items: [{ change: "added", identity: { kind: "file", name: "a" }, before: null, after: { name: "a", part: 1, kind: "file", size: 10, checksum_type: null, checksum_value: null, attributes: {} } }],
        next_cursor: "cursor-2",
      } as never)
      .mockResolvedValueOnce({
        from_version: "1", to_version: "2", summary: { added: 2, removed: 0, changed: 0, size_delta: 30 },
        items: [{ change: "added", identity: { kind: "file", name: "b" }, before: null, after: { name: "b", part: 2, kind: "file", size: 20, checksum_type: null, checksum_value: null, attributes: {} } }],
        next_cursor: null,
      } as never);
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ComparePanel, { domainId: "demo-pc", fromVersion: "1", toVersion: "2" });
    app.mount(root);
    await flushUpdates();
    (root.querySelector(".load-more") as HTMLButtonElement).click();
    await flushUpdates();
    expect(api.compare).toHaveBeenLastCalledWith("demo-pc", expect.objectContaining({ cursor: "cursor-2" }), expect.any(AbortSignal));
    expect(root.textContent).toContain("a");
    expect(root.textContent).toContain("b");
    app.unmount();
  });

  it("renders file-level comparison paths and requests file scope", async () => {
    vi.spyOn(api, "compare").mockResolvedValue({
      from_version: "1", to_version: "2", compare_scope: "files",
      summary: { added: 0, removed: 0, changed: 1, size_delta: 1 },
      items: [{
        change: "changed",
        identity: { path: "Client/Bin/game.dll" },
        before: { name: "game.dll", part: 1, kind: "file", size: 9, checksum_type: "md5", checksum_value: "c".repeat(32), attributes: { path: "Client/Bin/game.dll" } },
        after: { name: "game.dll", part: 1, kind: "file", size: 10, checksum_type: "md5", checksum_value: "d".repeat(32), attributes: { path: "Client/Bin/game.dll" } },
      }],
      next_cursor: null,
    } as never);
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ComparePanel, { domainId: "nte-pc", fromVersion: "1", toVersion: "2", compareScope: "files" });
    app.mount(root);
    await flushUpdates();
    expect(api.compare).toHaveBeenCalledWith("nte-pc", expect.objectContaining({ compareScope: "files", kind: "file" }), expect.any(AbortSignal));
    expect(root.textContent).toContain("Client/Bin/game.dll");
    expect(root.textContent).toContain("9 B");
    expect(root.textContent).toContain("10 B");
    app.unmount();
  });

  it("shows comparison errors and retries without client-side artifact loading", async () => {
    vi.spyOn(api, "compare")
      .mockRejectedValueOnce(new Error("compare unavailable"))
      .mockResolvedValueOnce({ from_version: "1", to_version: "2", summary: { added: 0, removed: 0, changed: 0, size_delta: 0 }, items: [], next_cursor: null } as never);
    const allArtifacts = vi.spyOn(api, "allArtifacts");
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(ComparePanel, { domainId: "demo-pc", fromVersion: "1", toVersion: "2" });
    app.mount(root);
    await flushUpdates();
    expect(root.textContent).toContain("compare unavailable");
    ([...root.querySelectorAll("button")].find((button) => button.textContent === "重试") as HTMLButtonElement).click();
    await flushUpdates();
    expect(api.compare).toHaveBeenCalledTimes(2);
    expect(allArtifacts).not.toHaveBeenCalled();
    app.unmount();
  });

  it("keeps the latest remote tree request authoritative during rapid switches", async () => {
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const emittedProbeTimes: Array<string | null> = [];
    vi.spyOn(api, "artifactTree")
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }) as never)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }) as never);
    const version = ref("1.0");
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp({ render: () => h(RemoteArtifactTree, {
      domainId: "demo-pc", version: version.value, kind: "file",
      onProbeTimeChange: (value: string | null) => emittedProbeTimes.push(value),
    }) });
    app.mount(root);
    await flushUpdates();
    version.value = "2.0";
    await flushUpdates();

    resolveFirst({ prefix: "", folders: [], items: [{
      id: 1, kind: "file", name: "old.bin", part: 1, size: 1,
      checksum_type: null, checksum_value: null, attributes: {}, urls: [],
    }], next_cursor: null });
    await flushUpdates();
    expect(root.textContent).toContain("正在读取目录索引");
    expect(root.textContent).not.toContain("old.bin");
    expect(emittedProbeTimes).toEqual([null, null]);

    resolveSecond({ prefix: "", folders: [], items: [{
      id: 2, kind: "file", name: "new.bin", part: 1, size: 1,
      checksum_type: null, checksum_value: null, attributes: {},
      urls: [{
        id: 2, url: "https://cdn.example/new.bin", priority: 0, source_kind: "official",
        evidence_status: "verified", current: {
          state: "available", reason: "http_2xx", confidence: "high", retained: false,
          checked_at: "2026-08-30T02:00:00Z", source_kind: "live_probe",
          source_confidence: "high", observed_at: "2026-08-30T02:00:00Z",
          expires_at: null, evidence_status: "verified",
        },
      }],
    }], next_cursor: null });
    await flushUpdates();
    expect(root.textContent).toContain("new.bin");
    expect(root.textContent).not.toContain("old.bin");
    expect(emittedProbeTimes).toEqual([null, null, "2026-08-30T02:00:00Z"]);
    app.unmount();
  });

  it("treats non-DOM AbortError values as cancellation in the remote tree", async () => {
    vi.spyOn(api, "artifactTree").mockRejectedValue(
      Object.assign(new Error("aborted"), { name: "AbortError" }),
    );
    const root = document.createElement("div"); document.body.appendChild(root);
    const app = createApp(RemoteArtifactTree, {
      domainId: "demo-pc", version: "1.0", kind: "file",
    });
    app.mount(root);
    await flushUpdates();
    expect(root.textContent).not.toContain("目录加载失败");
    expect(root.textContent).not.toContain("aborted");
    app.unmount();
  });
});
