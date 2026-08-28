import { createApp, h, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import VersionPicker from "./components/VersionPicker.vue";
import type { ArchiveDomain, VersionSummary } from "./types";
import { versionFamily } from "./version-grouping";

describe("version family labels", () => {
  it("keeps HoYo and WuWa major families while splitting NTE by release family", () => {
    expect(versionFamily("9.0.0", "hoyo", "bh3")).toBe("9.x");
    expect(versionFamily("1.3.7", "nte", "nte")).toBe("1.3.x");
    expect(versionFamily("3.41.0", "wuwa", "wuwa")).toBe("3.x");
  });

  it("uses the same two-segment family for Endfield resources and leaves other Android catalogs major-based", () => {
    expect(versionFamily("1.2.4", "endfield-resources", "endfield")).toBe("1.2.x");
    expect(versionFamily("1.2.0", "android", "nte")).toBe("1.2.x");
    expect(versionFamily("8.6.0", "android", "bh3")).toBe("8.x");
  });
});

describe("full-history version picker", () => {
  afterEach(() => { document.body.innerHTML = ""; });

  it("renders and selects all 42 WuWa versions without eager artifact loading", async () => {
    const versions = Array.from({ length: 42 }, (_, index) => ({
      version: `3.${41 - index}.0`, current_revision_id: index + 1, revision_count: 1,
      observed_at: "2026-07-11T03:30:45Z", packed_size: 1, unpacked_size: 1,
      artifact_count: 1, artifact_kinds: { file: { count: 1, size: 1 } },
      availability_states: {}, attributes: {}, provenance: {},
    })) as VersionSummary[];
    const domain = {
      id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
      capabilities: ["files", "patches", "archive", "compare"], adapter: "wuwa",
      version_count: 42, latest_version: "3.41.0",
      capability_contract: { features: { split_versions: "supported", package_file_list: "supported" } },
    } as ArchiveDomain;
    let selected = "";
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({
      render: () => h(VersionPicker, {
        versions,
        modelValue: versions[0].version,
        domain,
        onSelect: (value: string) => { selected = value; },
      }),
    });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    expect(root.querySelectorAll(".version-row")).toHaveLength(42);
    (root.querySelectorAll(".version-row")[41] as HTMLButtonElement).click();
    expect(selected).toBe("3.0.0");
    app.unmount();
  });

  it("renders a complete 55-version HoYo catalog and keeps selection local", async () => {
    const versions = Array.from({ length: 55 }, (_, index) => ({
      version: `8.${54 - index}.0`, current_revision_id: index + 1, revision_count: 1,
      observed_at: "2026-07-11T03:25:37.217Z", packed_size: 1, unpacked_size: 1,
      artifact_count: 1, artifact_kinds: { package: { count: 1, size: 1 } },
      availability_states: {}, attributes: { catalog_position: index }, provenance: {},
    })) as VersionSummary[];
    const domain = {
      id: "bh3-pc", game_id: "bh3", kind: "mixed", platform: "windows",
      capabilities: ["packages", "chunks", "archive", "compare"], adapter: "hoyo",
      version_count: 55, latest_version: "8.54.0", source_current_version: "8.54.0",
      capability_contract: { features: { split_versions: "supported", selected_version_loading: "supported", compare: "supported" } },
    } as ArchiveDomain;
    let selected = "";
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({
      render: () => h(VersionPicker, {
        versions, modelValue: versions[0].version, domain,
        onSelect: (value: string) => { selected = value; },
      }),
    });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    expect(root.querySelectorAll(".version-row")).toHaveLength(55);
    (root.querySelectorAll(".version-row")[54] as HTMLButtonElement).click();
    expect(selected).toBe("8.0.0");
    app.unmount();
  });

  it("renders NTE release families separately", async () => {
    const versions = ["1.3.7", "1.3.6", "1.2.21"].map((version, index) => ({
      version, current_revision_id: index + 1, revision_count: 1,
      observed_at: "2026-08-15T04:00:00Z", packed_size: 1, unpacked_size: 1,
      artifact_count: 1, artifact_kinds: { chunk: { count: 1, size: 1 } },
      availability_states: {}, attributes: {}, provenance: {},
    })) as VersionSummary[];
    const domain = {
      id: "nte-pc", game_id: "nte", kind: "mixed", platform: "windows",
      capabilities: ["chunks", "archive"], adapter: "nte", version_count: 3,
      latest_version: "1.3.7", capability_contract: { features: {} },
    } as ArchiveDomain;
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({ render: () => h(VersionPicker, { versions, modelValue: versions[0].version, domain, onSelect: () => {} }) });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    expect(root.querySelectorAll(".version-group")).toHaveLength(2);
    expect(root.textContent).toContain("1.3.x 版本");
    expect(root.textContent).toContain("1.2.x 版本");
    app.unmount();
  });
});

describe("multi-channel Android versions", () => {
  it("collapses same-base channel versions into a single picker row", async () => {
    const versions = [
      { version: "1.2.0@mihoyo", current_revision_id: 1, revision_count: 1, observed_at: "2026-07-01T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: {}, attributes: { channel: "mihoyo" }, provenance: {} },
      { version: "1.2.0@mihoyo_8", current_revision_id: 2, revision_count: 1, observed_at: "2026-07-01T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: {}, attributes: { channel: "mihoyo_8" }, provenance: {} },
      { version: "4.4.0", current_revision_id: 3, revision_count: 1, observed_at: "2026-08-01T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: {}, attributes: {}, provenance: {} },
    ] as VersionSummary[];
    const domain = {
      id: "hkrpg-android", game_id: "hkrpg", kind: "apk", platform: "android",
      capabilities: ["apk", "archive"], adapter: "android",
      version_count: 3, latest_version: "4.4.0",
      capability_contract: { features: {} },
    } as ArchiveDomain;
    let selected = "";
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({
      render: () => h(VersionPicker, {
        versions,
        modelValue: "1.2.0@mihoyo",
        domain,
        onSelect: (value: string) => { selected = value; },
      }),
    });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    const rows = Array.from(root.querySelectorAll(".version-row"));
    // 1.2.0 collapses into one row; 4.4.0 is its own row.
    const labels = rows.map((row) => row.querySelector(".version-number")?.textContent || "");
    expect(labels.filter((label) => label === "1.2.0")).toHaveLength(1);
    expect(labels).toContain("4.4.0");
    const oneTwo = rows.find((row) => row.querySelector(".version-number")?.textContent === "1.2.0");
    expect(oneTwo?.textContent).not.toContain("渠道");
    // Clicking 1.2.0 selects the first channel identity.
    (oneTwo as HTMLButtonElement).click();
    expect(selected).toBe("1.2.0@mihoyo");
    app.unmount();
  });
});

describe("multi-channel availability badges", () => {
  it("does not mark a collapsed version unavailable while one URL still works", async () => {
    const versions = [
      { version: "1.2.0@mihoyo", current_revision_id: 1, revision_count: 1, observed_at: "2026-07-01T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: { available: 1 }, attributes: { channel: "mihoyo" }, provenance: {} },
      { version: "1.2.0@mihoyo_8", current_revision_id: 2, revision_count: 1, observed_at: "2026-07-01T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: { unavailable: 1 }, attributes: { channel: "mihoyo_8" }, provenance: {} },
    ] as VersionSummary[];
    const domain = {
      id: "hkrpg-android", game_id: "hkrpg", kind: "apk", platform: "android",
      capabilities: ["apk", "archive"], adapter: "android",
      version_count: 2, latest_version: "1.2.0",
      capability_contract: { features: {} },
    } as ArchiveDomain;
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({
      render: () => h(VersionPicker, {
        versions,
        modelValue: "1.2.0@mihoyo",
        domain,
        onSelect: () => {},
      }),
    });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    const row = Array.from(root.querySelectorAll(".version-row")).find(
      (item) => item.querySelector(".version-number")?.textContent === "1.2.0",
    );
    expect(row?.textContent).not.toContain("渠道");
    expect(row?.textContent).not.toContain("含失效");
    expect(row?.textContent).toContain("可用");
    expect(row?.textContent).not.toContain("不可用");
    app.unmount();
  });

  it("dynamically shows available and unavailable version counts in group headers", async () => {
    const versions = [
      // 13.x: all available (2 available)
      { version: "13.3.8", current_revision_id: 1, revision_count: 1, observed_at: "2026-08-07T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: { available: 1 }, attributes: {}, provenance: {} },
      { version: "13.2.8", current_revision_id: 2, revision_count: 1, observed_at: "2026-06-12T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: { available: 1 }, attributes: {}, provenance: {} },
      // 12.x: all unavailable (2 unavailable)
      { version: "12.6.101", current_revision_id: 3, revision_count: 1, observed_at: "2026-05-01T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: { unavailable: 1 }, attributes: {}, provenance: {} },
      { version: "12.6.54", current_revision_id: 4, revision_count: 1, observed_at: "2026-04-01T00:00:00Z", packed_size: 1, unpacked_size: 1, artifact_count: 1, artifact_kinds: { apk: { count: 1, size: 1 } }, availability_states: { unavailable: 1 }, attributes: {}, provenance: {} },
    ] as VersionSummary[];
    const domain = {
      id: "bh3-android", game_id: "bh3", kind: "apk", platform: "android",
      capabilities: ["apk", "archive"], adapter: "android",
      version_count: 4, latest_version: "13.3.8",
      capability_contract: { features: {} },
    } as ArchiveDomain;
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({
      render: () => h(VersionPicker, {
        versions,
        modelValue: "13.3.8",
        domain,
        onSelect: () => {},
      }),
    });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    const groupMetas = Array.from(root.querySelectorAll(".version-group .group-meta")).map(el => el.textContent?.trim());
    expect(groupMetas).toContain("2 可用");
    expect(groupMetas).toContain("2 不可用");
    app.unmount();
  });
});

describe("WuWa PC files availability fallback", () => {
  afterEach(() => { document.body.innerHTML = ""; });

  const domain = {
    id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows",
    capabilities: ["files", "patches"], adapter: "wuwa", version_count: 1,
    latest_version: "3.5.3", capability_contract: { features: {} },
  } as ArchiveDomain;
  const summaryFor = (artifact_kinds: VersionSummary["artifact_kinds"]) => ({
    version: "3.5.3", current_revision_id: 1, revision_count: 1,
    observed_at: "2026-08-01T00:00:00Z", packed_size: 1, unpacked_size: 1,
    artifact_count: 0, artifact_kinds, availability_states: {}, attributes: {}, provenance: {},
  } as VersionSummary);

  it.each([
    ["package only", { package: { count: 1, size: 1, availability_states: { available: 1 } } }, "可用"],
    ["patch only", { patch: { count: 1, size: 1, availability_states: { available: 1 } } }, "可用"],
    ["package and patch with one unavailable", {
      package: { count: 1, size: 1, availability_states: { available: 1 } },
      patch: { count: 1, size: 1, availability_states: { unavailable: 1 } },
    }, "含失效 1"],
    ["unknown only", { package: { count: 1, size: 1, availability_states: { unknown: 1 } } }, "未判定"],
    ["available and unknown", { package: { count: 2, size: 1, availability_states: { available: 1, unknown: 1 } } }, "含未判定 1"],
    ["without package or patch", {}, "无数据"],
  ])("uses real package/patch summary for %s", async (_name, artifact_kinds, expected) => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({ render: () => h(VersionPicker, {
      versions: [summaryFor(artifact_kinds)], modelValue: "3.5.3", domain, mode: "files", onSelect: () => {},
    }) });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    const row = root.querySelector(".version-row");
    const rowText = row?.textContent || "";
    expect(rowText).toContain(expected);
    if (expected === "未判定" || expected === "含未判定 1") {
      expect(rowText.match(new RegExp(expected, "g"))).toHaveLength(1);
    }
    app.unmount();
  });

  it("keeps the legacy file-kind behavior for non-WuWa files", async () => {
    const item = summaryFor({ package: { count: 1, size: 1, availability_states: { available: 1 } } });
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({ render: () => h(VersionPicker, {
      versions: [item], modelValue: item.version,
      domain: { ...domain, adapter: "nte", game_id: "nte" }, mode: "files", onSelect: () => {},
    }) });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    expect(root.querySelector(".version-row")?.textContent).toContain("无数据");
    app.unmount();
  });

  it("shows archived for a local-only WuWa manifest", async () => {
    const item = summaryFor({ package: { count: 1, size: 1, availability_states: { unknown: 1 } } });
    item.attributes = { delivery_mode: "file_manifest", local_manifest: "kuro/wuwa/pc/manifests/2.6.0.json", manifest_urls: [] };
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({ render: () => h(VersionPicker, {
      versions: [item], modelValue: item.version, domain, mode: "files", onSelect: () => {},
    }) });
    app.mount(root);
    (root.querySelector(".select-button") as HTMLButtonElement).click();
    await nextTick();
    const rowText = root.querySelector(".version-row")?.textContent || "";
    expect(rowText).toContain("已归档");
    expect(rowText).not.toContain("未判定");
    app.unmount();
  });
});
