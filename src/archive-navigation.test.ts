import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import ArchiveView from "./views/ArchiveView.vue";

const emptyPage = { items: [], next_cursor: null };

async function flushUpdates(): Promise<void> {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

describe("archive cross-game navigation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("loads the bounded NTE version on demand and keeps unverified/helper actions hidden", async () => {
    const game = { id: "nte", name: "异环", sub_name: "Neverness to Everness", icon_source: "", sort_order: 0 };
    const domain = {
      id: "nte-pc", game_id: "nte", kind: "mixed", platform: "windows",
      capabilities: ["files", "patches", "manifest"], adapter: "nte",
      version_count: 1, latest_version: "1.0.1", source_current_version: null, catalog_version_count: 78, sort_order: 0,
      capability_contract: {
        artifact_fields: { path: "supported", size: "supported", checksum: "supported", urls: "supported", provider: "supported", availability: "supported", patch_route: "unsupported" },
        version_fields: { source_released_at: "unsupported", source_updated_at: "supported", archived_at: "unsupported", observed_at: "supported" },
        features: { artifact_list: "supported", version_selector: "supported", history: "unsupported", compare: "unsupported" },
        actions: { open: "conditional", copy: "conditional", download: "conditional" },
        availability_source_kinds: ["live_probe", "metadata_inference"], url_providers: ["yhcdn1.wmupd.com"], live_probe: false,
      },
    };
    const version = {
      version: "1.0.1", current_revision_id: 1, revision_count: 1,
      observed_at: "2026-07-11T03:22:58Z", source_released_at: null,
      source_updated_at: "2026-04-17T02:00:39Z", archived_at: null, imported_at: "2026-07-19T00:00:00Z",
      packed_size: 117, unpacked_size: 0, artifact_count: 3,
      artifact_kinds: { file: { count: 2, size: 30, availability_states: { unknown: 2 } }, patch: { count: 1, size: 7, availability_states: { unknown: 1 } }, manifest: { count: 1, size: 64, availability_states: { available: 1 } } },
      availability_states: { available: 1, unavailable: 2 }, attributes: { release_type: "patch" }, provenance: { source_kind: "legacy_nte_root_catalog_lists" },
    };
    const file = {
      id: 2, kind: "file", name: "Client/path/game.bin", part: 2, size: 10,
      checksum_type: "md5", checksum_value: "1".repeat(32), attributes: { relative_path: "Client/path/game.bin" },
      urls: [{
        id: 2, url: "https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/1/object", priority: 0,
        source_kind: "official", provider: "yhcdn1.wmupd.com", evidence_status: "unverified",
        current: { state: "unknown", reason: "not_probed", confidence: "medium", retained: false, checked_at: "2026-07-11T03:22:58Z", source_kind: "metadata_inference", source_confidence: "medium", observed_at: "2026-07-11T03:22:58Z", expires_at: null, evidence_status: "unverified" },
      }],
    };
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    const versions = vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue({ items: [file], next_cursor: null } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/nte/nte-pc/1.0.1/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    expect(versions).toHaveBeenCalledWith("nte-pc", expect.any(AbortSignal));
    expect(artifacts.mock.calls.some(([domainId, selected]) => domainId === "nte-pc" && selected === "1.0.1")).toBe(true);
    expect(root.textContent).toContain("文件清单");
    expect(root.textContent).toContain("更新补丁");
    expect(root.textContent).toContain("清单文件");
    expect(root.textContent).toContain("10 B");
    expect(root.textContent).toContain("1".repeat(32));
    expect(root.querySelector<HTMLInputElement>(".search-box input")?.placeholder).toBe("文件名 / MD5 / URL");
    expect(root.textContent).not.toContain("未验证");
    expect(root.textContent).not.toContain("含失效");
    expect(root.textContent).not.toContain("CDN 候选");
    expect(root.textContent).not.toContain("yhcdn1.wmupd.com");
    expect(root.textContent).not.toContain("https://yhcdn1.wmupd.com");
    expect(root.textContent).not.toContain("个 URL");
    const nteFileRow = root.querySelector(".fragment-file-row") as HTMLButtonElement;
    nteFileRow.click();
    await nextTick();
    expect(root.textContent).toContain("Client/path/game.bin");
    expect(root.textContent).toContain("可用 / Client/path/game.bin");
    expect(root.textContent).toContain("复制链接");
    expect(root.textContent).toContain("打开");
    expect(root.querySelector<HTMLAnchorElement>(".fragment-file-actions a")?.href).toBe(file.urls[0].url);
    expect(root.querySelector(".fragment-file-actions .availability")).toBeNull();
    expect(root.textContent).not.toContain("版本对比");
    expect(root.textContent).not.toContain("aria2");
    expect(root.textContent).not.toContain("helper");
    expect(root.textContent).not.toContain("打开已验证 URL");
    app.unmount();
  });

  it("keeps HoYo chunk manifests downloadable when live-probe evidence is absent", async () => {
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
        id: 1, url: "https://autopatchcn.bh3.com/chunk/manifest-1", priority: 0,
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

    expect(root.textContent).toContain("游戏资源-外网（新）");
    expect(root.textContent).toContain("无证据");
    expect(root.textContent).toContain("下载 Manifest");
    expect(root.textContent).toContain("复制链接");
    expect(root.querySelector<HTMLAnchorElement>(".chunk-card a.icon-button")?.href).toBe(chunk.urls[0].url);
    app.unmount();
  });

  it("redirects an unsupported HoYo package version to the latest version with packages", async () => {
    const game = { id: "hkrpg", name: "崩坏：星穹铁道", sub_name: "Honkai: Star Rail", icon_source: "", sort_order: 0 };
    const domain = {
      id: "hkrpg-pc", game_id: "hkrpg", kind: "mixed", platform: "windows",
      capabilities: ["packages", "patches", "chunks"], adapter: "hoyo",
      version_count: 2, latest_version: "4.5.0", sort_order: 0, capability_contract: { features: {} },
    };
    const versions = [
      {
        version: "4.5.0", current_revision_id: 2, revision_count: 1, observed_at: "2026-08-29T00:00:00Z",
        packed_size: 0, unpacked_size: 0, artifact_count: 0, artifact_kinds: {}, availability_states: {},
        attributes: { has_chunk: true }, provenance: {},
      },
      {
        version: "4.4.0", current_revision_id: 1, revision_count: 1, observed_at: "2026-08-01T00:00:00Z",
        packed_size: 1, unpacked_size: 1, artifact_count: 1,
        artifact_kinds: { package: { count: 1, size: 1, availability_states: { available: 1 } } },
        availability_states: { available: 1 }, attributes: {}, provenance: {},
      },
    ];
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/hkrpg/hkrpg-pc/4.5.0/packages");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    expect(router.currentRoute.value.fullPath).toBe("/games/hkrpg/hkrpg-pc/4.4.0/packages");
    expect(artifacts.mock.calls.some(([domainId, version]) => domainId === "hkrpg-pc" && version === "4.4.0")).toBe(true);
    app.unmount();
  });

  it("renders NTE full-history selection and evidence-only partial/404 candidates", async () => {
    const game = { id: "nte", name: "异环", sub_name: "Neverness to Everness", icon_source: "", sort_order: 0 };
    const domain = {
      id: "nte-pc", game_id: "nte", kind: "mixed", platform: "windows",
      capabilities: ["files", "patches", "manifest", "archive", "compare", "legacy"], adapter: "nte",
      version_count: 43, latest_version: "1.2.12", source_current_version: null, catalog_version_count: 78, sort_order: 0,
      capability_contract: {
        features: { version_selector: "supported", history: "supported", compare: "supported", archive_classification: "supported", historical_404: "supported" },
        actions: { open: "conditional", copy: "conditional", download: "conditional" },
        availability_source_kinds: ["live_probe", "metadata_inference"], url_providers: ["yhcdn1.wmupd.com"], live_probe: false,
      },
    };
    const versions = Array.from({ length: 43 }, (_, index) => ({
      version: index === 42 ? "1.2.12" : `1.1.${index}`,
      current_revision_id: index + 1, revision_count: 1, observed_at: "2026-07-11T03:22:58Z",
      packed_size: 1, unpacked_size: 0, artifact_count: 1,
      artifact_kinds: { file: { count: 1, size: 1 } }, availability_states: { unknown: 1 },
      attributes: { archive_classification: "complete_archived" }, provenance: { source_current_version: null },
    }));
    const leads = [
      {
        id: 1, external_id: "nte-catalog:1.0.0", domain_id: "nte-pc", platform: "Windows", version: "1.0.0",
        inferred_context: "partial_archived", filename: "NTE 1.0.0 ResList.bin.zip", generated_at: "2026-07-11T03:22:58Z",
        source_note: "catalog evidence", notes: "patches:list_missing", capture_event_id: 1,
        urls: [{ id: 1, url: "https://yhcdn1.wmupd.com/partial", source_kind: "official_candidate", current_facts: { classification: "partial_archived", status_code: 200, reason: "not_probed", action_allowed: false }, archive_facts: { classification_reason: "patches:list_missing", action_allowed: false } }],
      },
      {
        id: 2, external_id: "nte-catalog:1.0.3", domain_id: "nte-pc", platform: "Windows", version: "1.0.3",
        inferred_context: "historical_404", filename: "NTE 1.0.3 ResList.bin.zip", generated_at: "2026-07-11T03:22:58Z",
        source_note: "catalog evidence", notes: "catalog_status_404", capture_event_id: 1,
        urls: [{ id: 2, url: "https://yhcdn1.wmupd.com/dead", source_kind: "official_candidate", current_facts: { classification: "historical_404", status_code: 404, reason: "http_404", action_allowed: false }, archive_facts: { classification_reason: "catalog_status_404", action_allowed: false } }],
      },
    ];
    const missingActionLead = structuredClone(leads[1]);
    missingActionLead.id = 3;
    missingActionLead.external_id = "nte-catalog:missing-action";
    Reflect.deleteProperty(missingActionLead.urls[0].current_facts, "action_allowed");
    const nullActionLead = structuredClone(leads[1]);
    nullActionLead.id = 4;
    nullActionLead.external_id = "nte-catalog:null-action";
    (nullActionLead.urls[0].current_facts as Record<string, unknown>).action_allowed = null;
    const malformedActionLead = structuredClone(leads[1]);
    malformedActionLead.id = 5;
    malformedActionLead.external_id = "nte-catalog:malformed-action";
    (malformedActionLead.urls[0].current_facts as Record<string, unknown>).action_allowed = "true";
    leads.push(missingActionLead, nullActionLead, malformedActionLead);
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    vi.spyOn(api, "leads").mockResolvedValue(leads as never);

    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }] });
    await router.push("/games/nte/nte-pc/1.2.12/legacy");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    expect(root.textContent).toContain("42 可用");
    expect(root.textContent).toContain("1 可用");
    expect(root.textContent).toContain("版本对比");
    expect(root.textContent).toContain("部分归档");
    expect(root.textContent).toContain("历史 404");
    expect(root.textContent).toContain("http_404");
    expect(root.textContent).not.toContain("复制官方入口");
    expect(root.querySelectorAll(".legacy-candidate-card")).toHaveLength(5);
    expect(root.querySelectorAll(".legacy-candidate-card .file-actions")).toHaveLength(0);
    expect(root.textContent).not.toContain("aria2");
    app.unmount();
  });

  it("does not request the destination domain with the previous game's version", async () => {
    const games = [
      { id: "nte", name: "NTE", sub_name: "异环", icon_source: "", sort_order: 0 },
      { id: "endfield", name: "Arknights: Endfield", sub_name: "明日方舟：终末地", icon_source: "", sort_order: 1 },
    ];
    const nteDomain = {
      id: "nte-pc", game_id: "nte", kind: "files", platform: "Windows", capabilities: ["files"],
      capability_contract: {}, adapter: "generic", version_count: 1, latest_version: "1.2.15", sort_order: 0,
    };
    const endfieldDomain = {
      id: "endfield-pc", game_id: "endfield", kind: "packages", platform: "Windows", capabilities: ["packages"],
      capability_contract: {}, adapter: "endfield", version_count: 1, latest_version: "1.3.3", sort_order: 0,
    };
    const nteVersions = [{ version: "1.2.15", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];
    const endfieldVersions = [{ version: "1.3.3", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];
    let resolveEndfieldVersions!: (value: typeof endfieldVersions) => void;
    const pendingEndfieldVersions = new Promise<typeof endfieldVersions>((resolve) => { resolveEndfieldVersions = resolve; });

    vi.spyOn(api, "games").mockResolvedValue(games as never);
    vi.spyOn(api, "domains").mockImplementation(async (gameId) => (
      gameId === "endfield" ? [endfieldDomain] : [nteDomain]
    ) as never);
    vi.spyOn(api, "versions").mockImplementation((domainId) => (
      domainId === "endfield-pc" ? pendingEndfieldVersions : Promise.resolve(nteVersions)
    ) as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/nte/nte-pc/1.2.15/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();

    await router.push("/games/endfield");
    await flushUpdates();

    expect(artifacts.mock.calls.some(([domainId, version]) => (
      domainId === "endfield-pc" && version === "1.2.15"
    ))).toBe(false);

    resolveEndfieldVersions(endfieldVersions);
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.params).toMatchObject({
      gameId: "endfield", domainId: "endfield-pc", version: "1.3.3", mode: "packages",
    });
    app.unmount();
  });

  it("renders WuWa fragment URLs as standard grouped actions without URL status rows", async () => {
    const game = { id: "wuwa", name: "鸣潮", sub_name: "Wuthering Waves", icon_source: "", sort_order: 0 };
    const domain = {
      id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
      capabilities: ["files", "patches", "archive", "compare"], adapter: "wuwa",
      version_count: 1, latest_version: "3.3.0", sort_order: 0,
      capability_contract: {
        artifact_fields: { urls: "supported", availability: "supported", provider: "supported", size: "supported", checksum: "supported" },
        features: { split_versions: "supported", package_file_list: "supported", multi_cdn: "supported", provenance: "supported" },
        actions: { open: "conditional", copy: "conditional", download: "conditional" },
        url_providers: ["cdn-a.example", "cdn-b.example", "cdn-c.example"],
      },
    };
    const version = {
      version: "3.3.0", attributes: { region: "cn", channel: "live", cdn_count: 3, patch_route_count: 1 },
      provenance: { source_kind: "tomyjan-import", publication_state: "promoted", source_commit: "abc123", source_manifest_digest: "digest123" },
      artifact_kinds: { file: { count: 1, size: 10, availability_states: { available: 1 } } },
      artifact_count: 1, availability_states: { available: 1 }, packed_size: 10, unpacked_size: 10,
      current_revision_id: 1, revision_count: 1, observed_at: "2026-07-11T03:30:45Z",
    };
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    vi.spyOn(api, "artifactTree").mockResolvedValue({
      prefix: "", folders: [], next_cursor: null,
      items: [{
        id: 1, kind: "file", name: "Client/a.bin", part: 1, size: 10,
        checksum_type: "md5", checksum_value: "1".repeat(32), attributes: {},
        urls: [
          { id: 1, url: "https://cdn-a.example/a.bin", priority: 0, source_kind: "official", provider: "cdn-a.example", evidence_status: "verified", current: { state: "available", reason: "http_2xx", confidence: "high", retained: false, checked_at: "2026-07-06T00:00:00Z", source_kind: "live_probe", source_confidence: "high", observed_at: "2026-07-06T00:00:00Z", expires_at: null, evidence_status: "verified" } },
          { id: 2, url: "https://cdn-b.example/a.bin", priority: 1, source_kind: "official", provider: "cdn-b.example", evidence_status: "no_evidence", current: null },
          { id: 3, url: "https://cdn-c.example/a.bin", priority: 2, source_kind: "official", provider: "cdn-c.example", evidence_status: "verified", current: { state: "unavailable", reason: "http_404", confidence: "high", retained: false, checked_at: "2026-07-06T00:00:00Z", source_kind: "live_probe", source_confidence: "high", observed_at: "2026-07-06T00:00:00Z", expires_at: null, evidence_status: "verified" } },
        ],
      }],
    } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/wuwa/wuwa-pc/3.3.0/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    const fileRow = root.querySelector(".file-row") as HTMLButtonElement;
    fileRow.click();
    await nextTick();
    expect(root.textContent).toContain("a.bin");
    expect(root.textContent).toContain("1".repeat(32));
    expect(root.querySelector(".availability-toolbar")).toBeNull();
    expect(root.querySelector(".browser-availability")).toBeNull();
    expect(root.querySelector(".browser-url-list")).toBeNull();
    expect(root.textContent).toContain("可用 / Client/a.bin");
    expect(root.textContent).toContain("复制官方入口");
    expect(root.textContent).toContain("官方入口");
    expect(root.textContent).toContain("CDN2");
    expect(root.textContent).toContain("CDN3");
    expect(Array.from(root.querySelectorAll<HTMLAnchorElement>(".fragment-file-actions a")).map((link) => link.href)).toEqual([
      "https://cdn-a.example/a.bin",
      "https://cdn-b.example/a.bin",
      "https://cdn-c.example/a.bin",
    ]);
    expect(root.textContent).not.toContain("cdn-a.example");
    expect(root.textContent).not.toContain("https://cdn-a.example/a.bin");
    expect(root.textContent).not.toContain("不可操作");
    expect(root.querySelector(".fragment-file-actions .availability")).toBeNull();
    app.unmount();
  });

  it("compares two selected versions from a 42-version WuWa catalog on demand", async () => {
    const game = { id: "wuwa", name: "鸣潮", sub_name: "Wuthering Waves", icon_source: "", sort_order: 0 };
    const domain = {
      id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
      capabilities: ["files", "patches", "archive", "compare"], adapter: "wuwa",
      version_count: 42, latest_version: "3.5.0", sort_order: 0,
      capability_contract: { artifact_fields: { patch_route: "supported" }, features: { split_versions: "supported" } },
    };
    const versions = Array.from({ length: 42 }, (_, index) => ({
      version: index === 0 ? "3.5.0" : index === 1 ? "3.4.2" : `2.${42 - index}.0`,
      current_revision_id: index + 1, revision_count: 1, observed_at: "2026-07-11T03:30:45Z",
      packed_size: 1, unpacked_size: 1, artifact_count: 1,
      artifact_kinds: { file: { count: 1, size: 1 } }, availability_states: {}, attributes: {},
    }));
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versions as never);
    const compare = vi.spyOn(api, "compare").mockResolvedValue({
      from_version: "3.4.2", to_version: "3.5.0",
      summary: { added: 0, removed: 0, changed: 1, size_delta: 10 },
      items: [{
        change: "changed", identity: { kind: "file", name: "Client/a.bin" },
        before: { name: "Client/a.bin", kind: "file", part: 1, size: 10, checksum_type: "md5", checksum_value: "1".repeat(32), attributes: {} },
        after: { name: "Client/a.bin", kind: "file", part: 1, size: 20, checksum_type: "md5", checksum_value: "2".repeat(32), attributes: {} },
      }],
      next_cursor: null,
    } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/wuwa/wuwa-pc/3.5.0/compare");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();
    expect(compare).toHaveBeenCalledWith("wuwa-pc", expect.objectContaining({
      fromVersion: "3.4.2", toVersion: "3.5.0",
    }), expect.any(AbortSignal));
    expect(root.textContent).toContain("3.4.2 → 3.5.0");
    expect(root.textContent).toContain("修改1 个");
    expect(root.textContent).not.toContain("复制");
    app.unmount();
  });

  it("ignores a late versions response from a domain that is no longer selected", async () => {
    const game = { id: "demo", name: "Demo", sub_name: "演示", icon_source: "", sort_order: 0 };
    const domainA = {
      id: "demo-a", game_id: "demo", kind: "files", platform: "Windows", capabilities: ["files"],
      capability_contract: {}, adapter: "generic", version_count: 1, latest_version: "a1", sort_order: 0,
    };
    const domainB = {
      id: "demo-b", game_id: "demo", kind: "packages", platform: "Windows", capabilities: ["packages"],
      capability_contract: {}, adapter: "generic", version_count: 1, latest_version: "b1", sort_order: 1,
    };
    const versionsA = [{ version: "a1", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];
    const versionsB = [{ version: "b1", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];
    let resolveVersionsB!: (value: typeof versionsB) => void;
    const pendingVersionsB = new Promise<typeof versionsB>((resolve) => { resolveVersionsB = resolve; });

    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domainA, domainB] as never);
    vi.spyOn(api, "versions").mockImplementation((domainId) => (
      domainId === "demo-b" ? pendingVersionsB : Promise.resolve(versionsA)
    ) as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/demo/demo-a/a1/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();

    await router.push("/games/demo/demo-b");
    await flushUpdates();
    await router.push("/games/demo/demo-a");
    await flushUpdates();

    resolveVersionsB(versionsB);
    await flushUpdates();
    await flushUpdates();

    expect(artifacts.mock.calls.some(([domainId, version]) => (
      domainId === "demo-a" && version === "b1"
    ))).toBe(false);
    app.unmount();
  });

  it("unifies PC and Android compare tabs into one top tab and provides in-panel platform switching", async () => {
    const game = { id: "hk4e", name: "原神", sub_name: "Genshin Impact", icon_source: "", sort_order: 0 };
    const pcDomain = {
      id: "hk4e-pc", game_id: "hk4e", kind: "mixed", platform: "windows",
      capabilities: ["packages", "patches", "chunks", "compare"], adapter: "hoyo",
      version_count: 2, latest_version: "5.5.0", sort_order: 0,
      capability_contract: { features: { compare: "supported" } },
    };
    const androidDomain = {
      id: "hk4e-android", game_id: "hk4e", kind: "apk", platform: "android",
      capabilities: ["apk", "compare"], adapter: "android",
      version_count: 2, latest_version: "5.5.0", sort_order: 1,
      capability_contract: { features: { compare: "supported" } },
    };
    const pcVersions = [
      { version: "5.5.0", current_revision_id: 2, revision_count: 1, observed_at: "2026-07-11T00:00:00Z", packed_size: 100, unpacked_size: 200, artifact_count: 2, artifact_kinds: { package: { count: 2, size: 100 } }, availability_states: {}, attributes: {} },
      { version: "5.4.0", current_revision_id: 1, revision_count: 1, observed_at: "2026-06-11T00:00:00Z", packed_size: 100, unpacked_size: 200, artifact_count: 2, artifact_kinds: { package: { count: 2, size: 100 } }, availability_states: {}, attributes: {} },
    ];
    const androidVersions = [
      { version: "5.5.0", current_revision_id: 2, revision_count: 1, observed_at: "2026-07-11T00:00:00Z", packed_size: 50, unpacked_size: 50, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 50 } }, availability_states: {}, attributes: { channel: "official" } },
      { version: "5.4.0", current_revision_id: 1, revision_count: 1, observed_at: "2026-06-11T00:00:00Z", packed_size: 50, unpacked_size: 50, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 50 } }, availability_states: {}, attributes: { channel: "official" } },
    ];

    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([pcDomain, androidDomain] as never);
    vi.spyOn(api, "versions").mockImplementation(async (domainId) => (
      domainId === "hk4e-android" ? androidVersions : pcVersions
    ) as never);
    const compare = vi.spyOn(api, "compare").mockImplementation(async (domainId) => ({
      from_version: "5.4.0", to_version: "5.5.0",
      summary: { added: 1, removed: 0, changed: 0, size_delta: 50 },
      items: [{
        change: "added", identity: { kind: domainId === "hk4e-android" ? "apk" : "package", name: domainId === "hk4e-android" ? "yuanshen.apk" : "pkg.zip" },
        after: { name: domainId === "hk4e-android" ? "yuanshen.apk" : "pkg.zip", kind: domainId === "hk4e-android" ? "apk" : "package", part: 1, size: 50, checksum_type: "md5", checksum_value: "1".repeat(32), attributes: {} },
      }],
      next_cursor: null,
    } as never));

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/hk4e/hk4e-pc/5.5.0/compare");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    // 1. Verify only ONE "版本对比" tab exists in top nav
    const modeTabs = Array.from(root.querySelectorAll(".mode-tab")).map((el) => el.textContent?.trim());
    const compareTabs = modeTabs.filter((text) => text === "版本对比");
    expect(compareTabs).toHaveLength(1);
    expect(modeTabs).toEqual(["完整包", "更新补丁", "Chunk 信息", "版本对比", "Android APK"]);

    // 2. Verify platform switcher buttons exist in compare panel
    const platformTabs = root.querySelectorAll(".compare-platform-tab");
    expect(platformTabs).toHaveLength(2);
    expect(platformTabs[0].textContent?.trim()).toBe("HOYO PC 客户端");
    expect(platformTabs[1].textContent?.trim()).toBe("Android 官方客户端");
    expect(platformTabs[0].classList.contains("active")).toBe(true);

    // Initial load was for PC
    expect(compare).toHaveBeenCalledWith("hk4e-pc", expect.objectContaining({
      fromVersion: "5.4.0", toVersion: "5.5.0",
    }), expect.any(AbortSignal));

    // 3. Click "Android 官方客户端" platform button
    (platformTabs[1] as HTMLButtonElement).click();
    await flushUpdates();
    await flushUpdates();

    expect(compare).toHaveBeenCalledWith("hk4e-android", expect.objectContaining({
      fromVersion: "5.4.0", toVersion: "5.5.0",
    }), expect.any(AbortSignal));
    expect(router.currentRoute.value.params).toMatchObject({
      gameId: "hk4e", domainId: "hk4e-android", version: "5.5.0", mode: "compare",
    });

    // Top "版本对比" tab remains active
    const activeModeTab = root.querySelector(".mode-tab.active");
    expect(activeModeTab?.textContent?.trim()).toBe("版本对比");

    app.unmount();
  });

  it("keeps a user-selected compare base when switching compare platforms", async () => {
    const game = { id: "hk4e", name: "原神", sub_name: "Genshin Impact", icon_source: "", sort_order: 0 };
    const pcDomain = {
      id: "hk4e-pc", game_id: "hk4e", kind: "mixed", platform: "windows",
      capabilities: ["packages", "compare"], adapter: "hoyo",
      version_count: 3, latest_version: "5.5.0", sort_order: 0,
      capability_contract: { features: { compare: "supported" } },
    };
    const androidDomain = {
      id: "hk4e-android", game_id: "hk4e", kind: "apk", platform: "android",
      capabilities: ["apk", "compare"], adapter: "android",
      version_count: 3, latest_version: "5.5.0", sort_order: 1,
      capability_contract: { features: { compare: "supported" } },
    };
    const versionsFor = () => ["5.5.0", "5.4.0", "5.3.0"].map((version, index) => ({
      version, current_revision_id: 3 - index, revision_count: 1, observed_at: "2026-07-11T00:00:00Z",
      packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { package: { count: 1, size: 1 } }, availability_states: {}, attributes: {},
    }));

    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([pcDomain, androidDomain] as never);
    vi.spyOn(api, "versions").mockResolvedValue(versionsFor() as never);
    const compare = vi.spyOn(api, "compare").mockResolvedValue({
      from_version: "5.3.0", to_version: "5.5.0",
      summary: { added: 0, removed: 0, changed: 1, size_delta: 1 },
      items: [], next_cursor: null,
    } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/hk4e/hk4e-pc/5.5.0/compare");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    // The admin selects the non-default base 5.3.0 (default would be 5.4.0).
    await router.replace({ name: "archive", params: router.currentRoute.value.params, query: { from: "5.3.0" } });
    await flushUpdates();

    (root.querySelectorAll(".compare-platform-tab")[1] as HTMLButtonElement).click();
    await flushUpdates();
    await flushUpdates();

    expect(router.currentRoute.value.fullPath).toBe("/games/hk4e/hk4e-android/5.5.0/compare?from=5.3.0");
    expect(compare).toHaveBeenCalledWith("hk4e-android", expect.objectContaining({
      fromVersion: "5.3.0", toVersion: "5.5.0",
    }), expect.any(AbortSignal));
    expect(root.querySelector(".mode-tab.active")?.textContent?.trim()).toBe("版本对比");

    app.unmount();
  });

  it("falls back to a legal compare base when the selected base is missing on the target platform", async () => {
    const game = { id: "hk4e", name: "原神", sub_name: "Genshin Impact", icon_source: "", sort_order: 0 };
    const pcDomain = {
      id: "hk4e-pc", game_id: "hk4e", kind: "mixed", platform: "windows",
      capabilities: ["packages", "compare"], adapter: "hoyo",
      version_count: 3, latest_version: "5.5.0", sort_order: 0,
      capability_contract: { features: { compare: "supported" } },
    };
    const androidDomain = {
      id: "hk4e-android", game_id: "hk4e", kind: "apk", platform: "android",
      capabilities: ["apk", "compare"], adapter: "android",
      version_count: 3, latest_version: "5.5.0", sort_order: 1,
      capability_contract: { features: { compare: "supported" } },
    };
    const pcVersions = ["5.5.0", "5.4.0", "5.3.0"].map((version, index) => ({
      version, current_revision_id: 3 - index, revision_count: 1, observed_at: "2026-07-11T00:00:00Z",
      packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { package: { count: 1, size: 1 } }, availability_states: {}, attributes: {},
    }));
    const androidVersions = ["5.5.0", "5.2.0", "5.1.0"].map((version, index) => ({
      version, current_revision_id: 3 - index, revision_count: 1, observed_at: "2026-07-11T00:00:00Z",
      packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: {}, attributes: {},
    }));

    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([pcDomain, androidDomain] as never);
    vi.spyOn(api, "versions").mockImplementation(async (domainId) => (
      domainId === "hk4e-android" ? androidVersions : pcVersions
    ) as never);
    const compare = vi.spyOn(api, "compare").mockResolvedValue({
      from_version: "5.2.0", to_version: "5.5.0",
      summary: { added: 1, removed: 0, changed: 0, size_delta: 1 },
      items: [], next_cursor: null,
    } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/hk4e/hk4e-pc/5.5.0/compare?from=5.3.0");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    (root.querySelectorAll(".compare-platform-tab")[1] as HTMLButtonElement).click();
    await flushUpdates();
    await flushUpdates();

    expect(router.currentRoute.value.fullPath).toBe("/games/hk4e/hk4e-android/5.5.0/compare?from=5.2.0");
    expect(compare).toHaveBeenCalledWith("hk4e-android", expect.objectContaining({
      fromVersion: "5.2.0", toVersion: "5.5.0",
    }), expect.any(AbortSignal));

    app.unmount();
  });

  it("reloads archive data on availability invalidation and stops after unmount", async () => {
    const game = { id: "wuwa", name: "鸣潮", sub_name: "Wuthering Waves", icon_source: "", sort_order: 0 };
    const domain = {
      id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
      capabilities: ["files"], adapter: "generic",
      version_count: 1, latest_version: "3.3.0", sort_order: 0,
      capability_contract: {},
    };
    const version = { version: "3.3.0", attributes: {}, artifact_kinds: {}, artifact_count: 0 };
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/wuwa/wuwa-pc/3.3.0/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();

    artifacts.mockClear();
    vi.mocked(api.games).mockClear();
    // Same-tab notification triggers a reload of the current page data.
    window.dispatchEvent(new CustomEvent("gmi-availability-invalidated", { detail: { jobId: "job-1" } }));
    await flushUpdates();
    expect(api.games).toHaveBeenCalledTimes(1);
    expect(artifacts.mock.calls.some(([domainId, selected]) => domainId === "wuwa-pc" && selected === "3.3.0")).toBe(true);

    // Cross-tab notification arrives through the storage event.
    window.dispatchEvent(new StorageEvent("storage", { key: "gmi-availability-invalidated-at", newValue: "job-1:1" }));
    await flushUpdates();
    expect(api.games).toHaveBeenCalledTimes(2);

    // Unrelated storage keys are ignored.
    window.dispatchEvent(new StorageEvent("storage", { key: "unrelated-key", newValue: "x" }));
    await flushUpdates();
    expect(api.games).toHaveBeenCalledTimes(2);

    app.unmount();
    window.dispatchEvent(new CustomEvent("gmi-availability-invalidated", { detail: { jobId: "job-2" } }));
    window.dispatchEvent(new StorageEvent("storage", { key: "gmi-availability-invalidated-at", newValue: "job-2:2" }));
    await flushUpdates();
    expect(api.games).toHaveBeenCalledTimes(2);
  });

  it("exposes verified live-probe actions and keeps verified unavailable downloads locked", async () => {
    const game = { id: "hk4e", name: "原神", sub_name: "Genshin Impact", icon_source: "", sort_order: 0 };
    const domain = {
      id: "hk4e-pc", game_id: "hk4e", kind: "mixed", platform: "windows",
      capabilities: ["packages"], adapter: "hoyo",
      version_count: 1, latest_version: "5.5.0", sort_order: 0,
      capability_contract: {
        artifact_fields: { availability: "supported", size: "supported", checksum: "supported" },
        url_source_kinds: ["official"],
        actions: { download: "conditional" },
        availability_source_kinds: [], live_probe: false,
      },
    };
    const version = {
      version: "5.5.0", current_revision_id: 1, revision_count: 1, observed_at: "2026-08-29T00:00:00Z",
      packed_size: 3, unpacked_size: 3, artifact_count: 3, artifact_kinds: { package: { count: 3, size: 3 } },
      availability_states: { available: 1, unavailable: 1, unknown: 1 }, attributes: {},
    };
    const probedAt = "2026-08-29T01:00:00Z";
    const verifiedCurrent = (state: string, reason: string) => ({
      state, reason, confidence: "low", retained: false, checked_at: probedAt,
      source_kind: "live_probe", source_confidence: "low", observed_at: probedAt, expires_at: null, evidence_status: "verified",
    });
    const staleCurrent = {
      state: "available", reason: "HTTP 206", confidence: "low", retained: false, checked_at: "2026-08-27T00:00:00Z",
      source_kind: "live_probe", source_confidence: "low", observed_at: "2026-08-27T00:00:00Z",
      expires_at: "2026-08-27T20:00:00Z", evidence_status: "stale",
    };
    const items = [
      {
        id: 1, kind: "package", name: "game.zip", part: 1, size: 1, checksum_type: "md5", checksum_value: "1".repeat(32), attributes: {},
        urls: [{ id: 1, url: "https://autopatchcn.yuanshen.com/game.zip", priority: 0, source_kind: "official", provider: "mihoyo", evidence_status: "verified", current: verifiedCurrent("available", "HTTP 206") }],
      },
      {
        id: 2, kind: "package", name: "old.zip", part: 1, size: 1, checksum_type: "md5", checksum_value: "2".repeat(32), attributes: {},
        urls: [{ id: 2, url: "https://autopatchcn.yuanshen.com/old.zip", priority: 0, source_kind: "official", provider: "mihoyo", evidence_status: "verified", current: verifiedCurrent("unavailable", "HTTP 404") }],
      },
      {
        id: 3, kind: "package", name: "stale.zip", part: 1, size: 1, checksum_type: "md5", checksum_value: "3".repeat(32), attributes: {},
        urls: [{ id: 3, url: "https://autopatchcn.yuanshen.com/stale.zip", priority: 0, source_kind: "official", provider: "mihoyo", evidence_status: "stale", current: staleCurrent }],
      },
    ];
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    vi.spyOn(api, "artifacts").mockResolvedValue({ items, next_cursor: null } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/hk4e/hk4e-pc/5.5.0/packages");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    const cards = Array.from(root.querySelectorAll(".file-card"));
    expect(cards).toHaveLength(3);
    const badges = cards.map((card) => card.querySelector(".availability")?.textContent?.trim());
    expect(badges).toEqual(["可用", "失效", "证据已陈旧"]);
    const downloadLinks = cards.map((card) => card.querySelector(".file-actions a.icon-button"));
    expect((downloadLinks[0] as HTMLAnchorElement)?.getAttribute("href")).toBe("https://autopatchcn.yuanshen.com/game.zip");
    for (const card of cards.slice(1)) {
      const lockedDownload = card.querySelector(".file-actions button.is-locked") as HTMLButtonElement;
      expect(lockedDownload).not.toBeNull();
      expect(lockedDownload.disabled).toBe(true);
      expect(card.querySelector(".file-actions a.icon-button")).toBeNull();
    }

    app.unmount();
  });

  it("keeps the destination page intact when a superseded refresh returns late", async () => {
    const games = [
      { id: "nte", name: "NTE", sub_name: "异环", platform: "PC", icon_source: "", version_count: 1, latest_version: "1.2.15", sort_order: 0 },
      { id: "endfield", name: "Arknights: Endfield", sub_name: "明日方舟：终末地", platform: "PC", icon_source: "", version_count: 1, latest_version: "1.3.3", sort_order: 1 },
    ];
    const nteDomain = {
      id: "nte-pc", game_id: "nte", kind: "files", platform: "Windows", capabilities: ["files"],
      capability_contract: {}, adapter: "generic", version_count: 1, latest_version: "1.2.15", sort_order: 0,
    };
    const endfieldDomain = {
      id: "endfield-pc", game_id: "endfield", kind: "packages", platform: "Windows", capabilities: ["packages"],
      capability_contract: {}, adapter: "endfield", version_count: 1, latest_version: "1.3.3", sort_order: 0,
    };
    const nteVersions = [{ version: "1.2.15", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];
    const endfieldVersions = [{ version: "1.3.3", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];

    vi.spyOn(api, "games").mockResolvedValue(structuredClone(games) as never);
    vi.spyOn(api, "domains").mockImplementation(async (gameId) => (
      gameId === "endfield" ? [endfieldDomain] : [nteDomain]
    ) as never);
    const versions = vi.spyOn(api, "versions").mockImplementation((domainId) => (
      domainId === "endfield-pc" ? Promise.resolve(endfieldVersions) : Promise.resolve(nteVersions)
    ) as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/nte/nte-pc/1.2.15/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();

    // The invalidation refresh starts but its games request stays pending.
    const pendingGames: Array<(value: typeof games) => void> = [];
    vi.spyOn(api, "games").mockImplementation(() => new Promise((resolve) => { pendingGames.push(resolve); }));
    window.dispatchEvent(new CustomEvent("gmi-availability-invalidated", { detail: { jobId: "job-1" } }));
    await flushUpdates();
    expect(pendingGames).toHaveLength(1);

    // The user leaves for another game while the refresh is still pending.
    await router.push("/games/endfield");
    await flushUpdates();
    expect(pendingGames).toHaveLength(2);

    // The new page's request completes first.
    pendingGames[1](structuredClone(games));
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/endfield/endfield-pc/1.3.3/packages");

    // The superseded refresh returns late and must change nothing.
    pendingGames[0](structuredClone(games));
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/endfield/endfield-pc/1.3.3/packages");
    expect(versions).toHaveBeenCalledTimes(2);
    expect(versions).toHaveBeenLastCalledWith("endfield-pc", expect.anything());
    expect(artifacts).toHaveBeenLastCalledWith("endfield-pc", "1.3.3", expect.anything(), expect.anything());
    expect(root.textContent).not.toContain("正在读取归档 API");
    expect(root.textContent).not.toContain("1.2.15");
    expect(root.textContent).toContain("1.3.3");

    app.unmount();
  });

  it("ignores an old artifact response that returns after the destination page", async () => {
    const games = [
      { id: "nte", name: "NTE", sub_name: "异环", platform: "PC", icon_source: "", version_count: 1, latest_version: "1.2.15", sort_order: 0 },
      { id: "endfield", name: "Endfield", sub_name: "终末地", platform: "PC", icon_source: "", version_count: 1, latest_version: "1.3.3", sort_order: 1 },
    ];
    const nteDomain = {
      id: "nte-pc", game_id: "nte", kind: "packages", platform: "windows",
      capabilities: ["packages"], capability_contract: {}, adapter: "generic",
      version_count: 1, latest_version: "1.2.15", sort_order: 0,
    };
    const endfieldDomain = {
      id: "endfield-pc", game_id: "endfield", kind: "packages", platform: "windows",
      capabilities: ["packages"], capability_contract: {}, adapter: "generic",
      version_count: 1, latest_version: "1.3.3", sort_order: 0,
    };
    const nteVersions = [{ version: "1.2.15", attributes: {}, artifact_kinds: {}, artifact_count: 1 }];
    const endfieldVersions = [{ version: "1.3.3", attributes: {}, artifact_kinds: {}, artifact_count: 1 }];
    const packageArtifact = (id: number, name: string) => ({
      id, kind: "package", name, part: 1, size: 1,
      checksum_type: "md5", checksum_value: String(id).repeat(32), attributes: {}, urls: [],
    });

    vi.spyOn(api, "games").mockResolvedValue(games as never);
    vi.spyOn(api, "domains").mockImplementation(async (gameId) => (
      gameId === "endfield" ? [endfieldDomain] : [nteDomain]
    ) as never);
    vi.spyOn(api, "versions").mockImplementation(async (domainId) => (
      domainId === "endfield-pc" ? endfieldVersions : nteVersions
    ) as never);
    const artifacts = vi.spyOn(api, "artifacts").mockResolvedValue({
      items: [packageArtifact(1, "initial-nte.zip")], next_cursor: null,
    } as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/nte/nte-pc/1.2.15/packages");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    let resolveOldArtifacts!: (value: { items: ReturnType<typeof packageArtifact>[]; next_cursor: null }) => void;
    artifacts.mockImplementation((domainId) => {
      if (domainId === "nte-pc") {
        return new Promise((resolve) => { resolveOldArtifacts = resolve; }) as never;
      }
      return Promise.resolve({ items: [packageArtifact(2, "current-endfield.zip")], next_cursor: null }) as never;
    });

    window.dispatchEvent(new CustomEvent("gmi-availability-invalidated", { detail: { jobId: "job-artifact-race" } }));
    await flushUpdates();
    await router.push("/games/endfield");
    await flushUpdates();
    await flushUpdates();
    expect(root.textContent).toContain("current-endfield.zip");

    resolveOldArtifacts({ items: [packageArtifact(3, "late-old-nte.zip")], next_cursor: null });
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/endfield/endfield-pc/1.3.3/packages");
    expect(root.textContent).toContain("current-endfield.zip");
    expect(root.textContent).not.toContain("late-old-nte.zip");

    app.unmount();
  });

  it("commits only the last refresh when two invalidations arrive back to back", async () => {
    const game = { id: "wuwa", name: "鸣潮", sub_name: "Wuthering Waves", platform: "PC", icon_source: "", version_count: 1, latest_version: "3.3.0", sort_order: 0 };
    const domain = {
      id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
      capabilities: ["files"], adapter: "generic",
      version_count: 1, latest_version: "3.3.0", sort_order: 0,
      capability_contract: {},
    };
    const version = { version: "3.3.0", attributes: {}, artifact_kinds: {}, artifact_count: 0 };
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    const versions = vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/wuwa/wuwa-pc/3.3.0/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();

    const pendingGames: Array<(value: typeof game[]) => void> = [];
    vi.spyOn(api, "games").mockImplementation(() => new Promise((resolve) => { pendingGames.push(resolve); }));
    window.dispatchEvent(new CustomEvent("gmi-availability-invalidated", { detail: { jobId: "job-1" } }));
    await flushUpdates();
    window.dispatchEvent(new CustomEvent("gmi-availability-invalidated", { detail: { jobId: "job-2" } }));
    await flushUpdates();
    expect(pendingGames).toHaveLength(2);

    versions.mockClear();
    pendingGames[1]([game]);
    await flushUpdates();
    await flushUpdates();
    expect(versions).toHaveBeenCalledTimes(1);

    pendingGames[0]([game]);
    await flushUpdates();
    await flushUpdates();
    expect(versions).toHaveBeenCalledTimes(1);

    app.unmount();
  });

  it("ignores pending refresh responses after unmount", async () => {
    const game = { id: "wuwa", name: "鸣潮", sub_name: "Wuthering Waves", platform: "PC", icon_source: "", version_count: 1, latest_version: "3.3.0", sort_order: 0 };
    const domain = {
      id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
      capabilities: ["files"], adapter: "generic",
      version_count: 1, latest_version: "3.3.0", sort_order: 0,
      capability_contract: {},
    };
    const version = { version: "3.3.0", attributes: {}, artifact_kinds: {}, artifact_count: 0 };
    vi.spyOn(api, "games").mockResolvedValue([game] as never);
    vi.spyOn(api, "domains").mockResolvedValue([domain] as never);
    const versions = vi.spyOn(api, "versions").mockResolvedValue([version] as never);
    vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/wuwa/wuwa-pc/3.3.0/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();

    const pendingGames: Array<(value: typeof game[]) => void> = [];
    vi.spyOn(api, "games").mockImplementation(() => new Promise((resolve) => { pendingGames.push(resolve); }));
    window.dispatchEvent(new CustomEvent("gmi-availability-invalidated", { detail: { jobId: "job-1" } }));
    await flushUpdates();
    expect(pendingGames).toHaveLength(1);

    versions.mockClear();
    app.unmount();
    pendingGames[0]([game]);
    await flushUpdates();
    expect(versions).not.toHaveBeenCalled();
  });

  it("loads the previous route again on browser back navigation", async () => {
    const games = [
      { id: "nte", name: "NTE", sub_name: "异环", platform: "PC", icon_source: "", version_count: 1, latest_version: "1.2.15", sort_order: 0 },
      { id: "endfield", name: "Arknights: Endfield", sub_name: "明日方舟：终末地", platform: "PC", icon_source: "", version_count: 1, latest_version: "1.3.3", sort_order: 1 },
    ];
    const nteDomain = {
      id: "nte-pc", game_id: "nte", kind: "files", platform: "Windows", capabilities: ["files"],
      capability_contract: {}, adapter: "generic", version_count: 1, latest_version: "1.2.15", sort_order: 0,
    };
    const endfieldDomain = {
      id: "endfield-pc", game_id: "endfield", kind: "packages", platform: "Windows", capabilities: ["packages"],
      capability_contract: {}, adapter: "endfield", version_count: 1, latest_version: "1.3.3", sort_order: 0,
    };
    const nteVersions = [{ version: "1.2.15", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];
    const endfieldVersions = [{ version: "1.3.3", attributes: {}, artifact_kinds: {}, artifact_count: 0 }];
    vi.spyOn(api, "games").mockResolvedValue(games as never);
    vi.spyOn(api, "domains").mockImplementation(async (gameId) => (
      gameId === "endfield" ? [endfieldDomain] : [nteDomain]
    ) as never);
    const versions = vi.spyOn(api, "versions").mockImplementation((domainId) => (
      domainId === "endfield-pc" ? Promise.resolve(endfieldVersions) : Promise.resolve(nteVersions)
    ) as never);
    vi.spyOn(api, "artifacts").mockResolvedValue(emptyPage as never);

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView }],
    });
    await router.push("/games/nte/nte-pc/1.2.15/files");
    await router.isReady();
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp(ArchiveView);
    app.use(router);
    app.mount(root);
    await flushUpdates();
    await flushUpdates();

    await router.push("/games/endfield");
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.params).toMatchObject({ gameId: "endfield", domainId: "endfield-pc" });

    versions.mockClear();
    await router.back();
    await flushUpdates();
    await flushUpdates();
    expect(router.currentRoute.value.fullPath).toBe("/games/nte/nte-pc/1.2.15/files");
    expect(versions).toHaveBeenCalledWith("nte-pc", expect.anything());

    app.unmount();
  });

});
