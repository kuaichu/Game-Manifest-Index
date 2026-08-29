import { describe, expect, it } from "vitest";
import type { ArchiveDomain, Artifact, AvailabilityCurrent, VersionSummary } from "./types";
import { artifactActionLabel, archiveSourceLabel, artifactKindForMode, artifactUrlStateCounts, availabilityStatesForMode, availableArchiveModes, availabilityLabel, buildArchiveOverview, buildSyncStatusPresentation, buildVersionBadges, distributionProfile, domainActionSupport, domainFeatureSupport, domainFieldSupport, domainModeLabel, fileTimestampEvidence, hoyoArtifactCardPresentation, isAvailabilityActionable, preferredArtifactAction, preferredDomainArtifactAction , displayVersionLabel } from "./domain-presentation";

describe("WuWa historical provenance presentation", () => {
  it("labels the real 3.5.3 migration summary as archived community data", () => {
    const summary = {
      version: "3.5.3",
      provenance: { source_kind: "legacy_migration" },
    } as unknown as VersionSummary;
    expect(archiveSourceLabel("wuwa", summary.provenance?.source_kind)).toBe("历史迁移/社区归档资源");
    expect(archiveSourceLabel("wuwa", "official_launcher")).toBe("鸣潮官方启动器索引");
  });
});
import { deliveryLabel } from "./domain-presentation";

describe("WuWa manifest delivery", () => {
  it("uses resource-list labels", () => {
    expect(deliveryLabel({ kind: "package", attributes: { delivery_mode: "file_manifest" } } as any)).toBe("官方资源清单");
    expect(deliveryLabel({ kind: "patch", attributes: { delivery_mode: "file_manifest" } } as any)).toBe("更新资源清单");
  });
});

function domain(adapter: string, capabilities: string[], gameId = "game", platform = "windows", id = `${gameId}-${platform}`): ArchiveDomain {
  return { id, game_id: gameId, kind: "mixed", platform, capabilities, capability_contract: {}, adapter, version_count: 1, latest_version: "1.0.0", sort_order: 0 };
}

function summary(overrides: Partial<VersionSummary> = {}): VersionSummary {
  return {
    version: "1.2.3", current_revision_id: 1, revision_count: 1, observed_at: "2026-07-13T03:00:00Z",
    source_released_at: null, source_updated_at: null, archived_at: null, imported_at: null,
    packed_size: 1000, unpacked_size: 2000, artifact_count: 10,
    artifact_kinds: { file: { count: 7, size: 700 }, package: { count: 2, size: 500 }, patch: { count: 3, size: 300 }, apk: { count: 1, size: 900 }, chunk: { count: 4, size: 400 }, resource: { count: 6, size: 600 }, manifest: { count: 1, size: 10 } },
    availability_states: { available: 5 }, attributes: {}, ...overrides,
  };
}

const formatBytes = (value: number) => `${value} B`;
const formatDate = (value?: string | null) => value || "—";
const overview = (current: ArchiveDomain, mode: string, currentSummary = summary()) => buildArchiveOverview({ domain: current, summary: currentSummary, mode, version: currentSummary.version, formatBytes, formatDate });

function availability(overrides: Partial<AvailabilityCurrent> = {}): AvailabilityCurrent {
  return {
    state: "available", reason: "http_2xx", confidence: "high", retained: false,
    checked_at: "2026-07-17T00:00:00Z", source_kind: "live_probe", source_confidence: "high",
    observed_at: "2026-07-17T00:00:00Z", expires_at: null, evidence_status: "verified", ...overrides,
  };
}

function artifact(
  urls: Array<Omit<Artifact["urls"][number], "evidence_status"> & { evidence_status?: Artifact["urls"][number]["evidence_status"] }>,
  overrides: Partial<Artifact> = {},
): Artifact {
  return {
    id: 1, kind: "package", name: "game.zip", part: 1, size: 1,
    checksum_type: "md5", checksum_value: "abc", attributes: {},
    urls: urls.map((item) => ({
      ...item,
      evidence_status: item.evidence_status || item.current?.evidence_status || "no_evidence",
    })),
    ...overrides,
  };
}

describe("domain presentation", () => {
  it("uses one vocabulary and stable capability order", () => {
    const hoyo = domain("hoyo", ["packages", "patches", "chunks", "archive"], "hk4e");
    const android = domain("android", ["apk"], "hk4e", "android");
    expect(domainModeLabel(hoyo, "packages")).toBe("完整包");
    expect(domainModeLabel(hoyo, "patches")).toBe("更新补丁");
    expect(domainModeLabel(domain("aethergazer-resources", ["resources"], "aethergazer"), "resources")).toBe("运行时资源");
    expect(availableArchiveModes([android, hoyo]).map((item) => item.capability)).toEqual(["packages", "patches", "chunks", "apk"]);
  });

  it("deduplicates compare mode across multiple domains of the same game", () => {
    const hoyo = domain("hoyo", ["packages", "patches", "chunks", "archive", "compare"], "hk4e", "windows", "hk4e-pc");
    const android = domain("android", ["apk", "compare"], "hk4e", "android", "hk4e-android");
    const modes = availableArchiveModes([android, hoyo]);
    const compareModes = modes.filter((item) => item.capability === "compare");
    expect(compareModes).toHaveLength(1);
    expect(compareModes[0].domain.id).toBe("hk4e-pc");
    expect(modes.map((item) => item.capability)).toEqual(["packages", "patches", "chunks", "compare", "apk"]);
  });

  it("uses the server capability contract for Endfield modes and field visibility", () => {
    const current = domain("endfield", ["packages", "patches", "archive", "compare"], "endfield");
    current.capability_contract = {
      artifact_fields: { size: "supported", checksum: "supported", urls: "supported", availability: "supported" },
      version_fields: { source_released_at: "supported", archived_at: "unsupported" },
      url_source_kinds: ["official", "mirror"], availability_source_kinds: ["upstream_archive"], live_probe: false,
    };
    expect(availableArchiveModes([current]).map((item) => item.capability)).toEqual(["packages", "patches", "compare"]);
    expect(domainFieldSupport(current, "artifact_fields", "availability")).toBe("supported");
    expect(domainFieldSupport(current, "version_fields", "archived_at")).toBe("unsupported");
    expect(domainFieldSupport(current, "artifact_fields", "made_up")).toBe("unsupported");
  });

  it("keeps every current server registry game in the capability navigation", () => {
    const registryDomains = [
      domain("endfield-resources", ["resources"], "endfield", "windows", "endfield-resources"),
      domain("arknights", ["packages"], "arknights", "windows", "arknights-pc"),
      domain("endfield", ["packages", "patches"], "endfield", "windows", "endfield-pc"),
      domain("hoyo", ["packages", "chunks", "archive"], "bh3", "windows", "bh3-pc"),
      domain("hoyo", ["packages", "patches", "chunks", "archive"], "hk4e", "windows", "hk4e-pc"),
      domain("hoyo", ["packages", "patches", "chunks", "archive"], "hkrpg", "windows", "hkrpg-pc"),
      domain("hoyo", ["packages", "patches", "chunks", "archive"], "nap", "windows", "nap-pc"),
      domain("nte", ["files", "patches", "manifest"], "nte", "windows", "nte-pc"),
      domain("patchersdk", ["files", "patches", "manifest"], "p5x", "windows", "p5x-pc"),
      domain("patchersdk", ["files", "patches", "manifest"], "tof", "windows", "tof-pc"),
      domain("wuwa", ["files", "patches"], "wuwa", "windows", "wuwa-pc"),
      domain("aethergazer-resources", ["resources"], "aethergazer", "android", "aethergazer-resources"),
    ];
    const expectedDomains = [
      ["endfield-resources", ["resources"]],
      ["arknights-pc", ["packages"]],
      ["endfield-pc", ["packages", "patches"]],
      ["bh3-pc", ["packages", "chunks", "archive"]],
      ["hk4e-pc", ["packages", "patches", "chunks", "archive"]],
      ["hkrpg-pc", ["packages", "patches", "chunks", "archive"]],
      ["nap-pc", ["packages", "patches", "chunks", "archive"]],
      ["nte-pc", ["files", "patches", "manifest"]],
      ["p5x-pc", ["files", "patches", "manifest"]],
      ["tof-pc", ["files", "patches", "manifest"]],
      ["wuwa-pc", ["files", "patches"]],
      ["aethergazer-resources", ["resources"]],
    ];
    expect(registryDomains.map((item) => [item.id, item.capabilities])).toEqual(expectedDomains);
    expect([...new Set(availableArchiveModes(registryDomains).map((item) => item.domain.id))].sort()).toEqual([
      "aethergazer-resources", "arknights-pc", "bh3-pc", "endfield-pc", "endfield-resources", "hk4e-pc", "hkrpg-pc", "nap-pc", "nte-pc", "p5x-pc", "tof-pc", "wuwa-pc",
    ]);
  });

  it("always returns the same six overview slots and uses the selected mode kind", () => {
    const result = overview(domain("patchersdk", ["files", "patches"], "tof"), "patches");
    expect(result.overviewMetrics.map((item) => item.label)).toEqual(["当前版本", "数据模块", "文件时间", "条目数", "总大小", "可用性"]);
    expect(result.overviewMetrics).toHaveLength(6);
    expect(result.overviewMetrics[3].value).toBe("3 个");
    expect(result.overviewMetrics[4].value).toBe("300 B");
    expect(result.artifactKind).toBe("patch");
  });

  it.each([
    [domain("patchersdk", ["files", "patches"], "tof"), ["2026/7/3", "完整文件", "含更新补丁"]],
    [domain("android", ["apk"], "bh3", "android"), ["2026/7/3"]],
    [domain("hoyo", ["packages", "patches", "chunks", "archive"], "hk4e"), ["2026/7/3", "完整包 + Chunk", "含更新包"]],
    [domain("arknights", ["packages"], "arknights"), ["2026/7/3", "完整包"]],
    [domain("endfield", ["packages", "patches"], "endfield"), ["2026/7/3", "完整包", "含更新补丁"]],
    [domain("wuwa", ["files", "patches"], "wuwa"), ["2026/7/3", "文件清单"]],
    [domain("aethergazer-resources", ["resources"], "aethergazer", "android"), ["2026/7/3", "运行时资源"]],
  ])("uses the same compact version-row contract for %s", (current, expected) => {
    const attrs: Record<string, string | number | boolean | null> = current.adapter === "wuwa"
      ? { archived_at: "2026-07-03T00:00:00Z", time_kind: "archive", source: "tomyjan-import" }
      : { last_modified: "2026-07-03T00:00:00Z" };
    const item = summary({ attributes: attrs });
    expect(buildVersionBadges(current, item, () => "2026/7/3").map((badge) => badge.label)).toEqual(expected);
  });

  it("uses one HoYo distribution vocabulary everywhere", () => {
    expect(distributionProfile(summary({ attributes: { decompressed_path: "/PC/unzip/", has_chunk: true } }))).toBe("完整包 + 直链 + Chunk");
  });

  it("renders HoYo language data only when the per-game capability declares it", () => {
    const voiced = domain("hoyo", ["packages", "patches", "chunks", "archive"], "hk4e");
    voiced.capability_contract = { features: { voice_language: "supported" } };
    const withoutVoice = domain("hoyo", ["packages", "chunks", "archive"], "bh3");
    withoutVoice.capability_contract = { features: { voice_language: "unsupported" } };
    const item = summary({ attributes: { voice_languages: ["zh-cn", "en-us", "ja-jp", "ko-kr"] } });

    expect(overview(voiced, "packages", item).moduleDetails).toContainEqual({ label: "语音语言", value: "中文 / 英语 / 日语 / 韩语" });
    expect(overview(withoutVoice, "packages", item).moduleDetails.some((row) => row.label === "语音语言")).toBe(false);
    expect(availableArchiveModes([withoutVoice]).map((row) => row.capability)).toEqual(["packages", "chunks"]);
  });

  it("renders HoYo package and patch cards from the normalized artifact contract", () => {
    const voicePackage = artifact([], {
      kind: "package", part: 4, size: 456789000,
      attributes: { component: "voice", package_type: "optional_component", language: "ja-jp" },
    });
    const gamePackage = artifact([], {
      kind: "package", part: 2, size: 1073741824,
      attributes: { component: "game", package_type: "segment", route_part: 2 },
    });
    const voicePatch = artifact([], {
      kind: "patch", part: 6, size: 204800,
      attributes: {
        component: "voice", package_type: "differential_optional_component", language: "zh-cn",
        route_from: "5.4.0", route_to: "5.5.0",
      },
    });

    expect(hoyoArtifactCardPresentation(voicePackage, "5.5.0", 3, 12)).toEqual({ label: "日语语音", subtitle: "日语 / 435.63 MB / 未验证" });
    expect(hoyoArtifactCardPresentation(gamePackage, "5.5.0", 1, 12)).toEqual({ label: "游戏包分卷", subtitle: "2/12 / 1.00 GB / 未验证" });
    expect(hoyoArtifactCardPresentation(voicePatch, "5.5.0", 5, 10)).toEqual({ label: "中文语音更新", subtitle: "中文 5.4.0 -> 5.5.0 / 200.00 KB / 未验证" });
  });

  it("keeps PatcherSDK manifest artifacts distinct from full files", () => {
    expect(artifactKindForMode("manifest")).toBe("manifest");
    expect(artifactKindForMode("files")).toBe("file");
  });

  it("uses each PatcherSDK domain capability without inventing history or compare controls", () => {
    const tof = domain("patchersdk", ["files", "patches", "manifest"], "tof");
    tof.capability_contract = { features: { history: "unsupported", compare: "unsupported" }, url_providers: ["htcdn1.wmupd.com"] };
    const p5x = domain("patchersdk", ["files", "patches", "manifest"], "p5x");
    p5x.capability_contract = { features: { history: "unsupported", compare: "unsupported" }, url_providers: ["nsywl-client-dev1.wmupd.com"] };
    expect(availableArchiveModes([tof, p5x]).map((item) => [item.domain.game_id, item.capability])).toEqual([
      ["p5x", "files"], ["tof", "files"], ["p5x", "patches"], ["tof", "patches"], ["p5x", "manifest"], ["tof", "manifest"],
    ]);
    expect(domainFeatureSupport(tof, "compare")).toBe(false);
    expect(domainFeatureSupport(p5x, "history")).toBe(false);
    expect(tof.capability_contract.url_providers).not.toEqual(p5x.capability_contract.url_providers);
  });

  it("enables PatcherSDK history and compare only after the full-history contract is published", () => {
    const tof = domain("patchersdk", ["files", "patches", "manifest", "archive", "compare"], "tof", "windows", "tof-pc");
    tof.version_count = 41;
    tof.latest_version = "6.2.2";
    tof.capability_contract = {
      features: { version_selector: "supported", history: "supported", compare: "supported" },
      url_providers: ["htcdn1.wmupd.com"],
    };
    expect(availableArchiveModes([tof]).map((item) => item.capability)).toEqual([
      "files", "patches", "manifest", "compare",
    ]);
    expect(domainFeatureSupport(tof, "history")).toBe(true);
    expect(domainFeatureSupport(tof, "compare")).toBe(true);
  });

  it("renders NTE from its independent capability without inventing helper or history controls", () => {
    const nte = domain("nte", ["files", "patches", "manifest"], "nte", "windows", "nte-pc");
    nte.capability_contract = {
      artifact_fields: {
        path: "supported", size: "supported", checksum: "supported", urls: "supported",
        provider: "supported", availability: "supported", patch_route: "unsupported",
      },
      version_fields: { source_released_at: "unsupported", source_updated_at: "supported", archived_at: "unsupported" },
      features: {
        artifact_list: "supported", version_selector: "supported", history: "unsupported", compare: "unsupported",
      },
      actions: { open: "conditional", copy: "conditional", download: "conditional" },
      url_providers: ["yhcdn1.wmupd.com"],
      live_probe: false,
    };
    expect(availableArchiveModes([nte]).map((item) => item.capability)).toEqual(["files", "patches", "manifest"]);
    expect(domainFieldSupport(nte, "artifact_fields", "checksum")).toBe("supported");
    expect(domainFieldSupport(nte, "version_fields", "source_released_at")).toBe("unsupported");
    expect(domainFeatureSupport(nte, "history")).toBe(false);
    expect(nte.capability_contract?.features).not.toHaveProperty("helper_export");
    expect(nte.capability_contract?.features).not.toHaveProperty("aria2_export");
    expect(domainActionSupport(nte, "download")).toBe(true);
    expect(overview(nte, "files").moduleDetails[0]).toEqual({ label: "版本族", value: "1.2" });
  });

  it("enables NTE archive, compare and candidate evidence only for the full-history contract", () => {
    const nte = domain("nte", ["files", "patches", "manifest", "archive", "compare", "legacy"], "nte", "windows", "nte-pc");
    nte.version_count = 43;
    nte.latest_version = "1.2.12";
    nte.source_current_version = null;
    nte.catalog_version_count = 78;
    nte.capability_contract = {
      features: {
        version_selector: "supported", history: "supported", compare: "supported",
        archive_classification: "supported", historical_404: "supported",
      },
      url_providers: ["yhcdn1.wmupd.com"],
      live_probe: false,
    };
    expect(availableArchiveModes([nte]).map((item) => item.capability)).toEqual([
      "files", "patches", "manifest", "compare", "legacy",
    ]);
    expect(domainFeatureSupport(nte, "history")).toBe(true);
    expect(domainFeatureSupport(nte, "historical_404")).toBe(true);
    expect(nte.source_current_version).toBeNull();
    expect(nte.capability_contract?.features).not.toHaveProperty("helper_export");
    expect(nte.capability_contract?.features).not.toHaveProperty("aria2_export");
  });

  it.each([
    ["android", ["apk"], "apk", "渠道标识"],
    ["hoyo", ["packages", "patches", "chunks", "archive"], "packages", "分发架构"],
    ["patchersdk", ["files", "patches"], "files", "版本族"],
    ["arknights", ["packages"], "packages", "接口体积"],
    ["endfield", ["packages", "patches"], "packages", "解压大小"],
    ["wuwa", ["files", "patches"], "files", "区服"],
    ["aethergazer-resources", ["resources"], "resources", "资源快照"],
  ])("builds a bounded module detail profile for %s", (adapter, capabilities, mode, firstLabel) => {
    const result = overview(domain(adapter, capabilities, adapter), mode);
    expect(result.overviewMetrics).toHaveLength(6);
    expect(result.moduleDetails.length).toBeGreaterThan(0);
    expect(result.moduleDetails.length).toBeLessThanOrEqual(4);
    expect(result.moduleDetails[0].label).toBe(firstLabel);
  });

  it("derives availability only from the version summary", () => {
    expect(availabilityLabel({ available: 3 })).toBe("可用");
    expect(availabilityLabel({ unavailable: 3 })).toBe("链接失效");
    expect(availabilityLabel({ available: 2, unavailable: 1 })).toBe("部分可达");
    expect(availabilityLabel({ unknown: 8 })).toBe("未判定");
  });

  it("requires complete availability provenance before exposing a URL action", () => {
    const current = availability({ source_confidence: "" });
    expect(isAvailabilityActionable(current, "https://cdn.example/game.zip", Date.parse("2026-07-17T01:00:00Z"))).toBe(false);
  });

  it("fails closed when an action contract is missing or unknown", () => {
    const current = domain("generic", ["packages"]);
    current.capability_contract = { actions: { open: "conditional" } };
    expect(domainActionSupport(current, "open")).toBe(true);
    expect(domainActionSupport(current, "copy")).toBe(false);
    expect(domainActionSupport(current, "made_up")).toBe(false);
    expect(domainActionSupport(undefined, "open")).toBe(false);
  });

  it("requires both the domain action contract and verified evidence", () => {
    const current = domain("generic", ["packages"]);
    const value = artifact([{ id: 1, url: "https://cdn.example/game.zip", priority: 0, source_kind: "official", current: availability() }]);
    current.capability_contract = { actions: { open: "conditional", copy: "unsupported" } };
    expect(preferredDomainArtifactAction(current, value, "open", Date.parse("2026-07-17T01:00:00Z"))?.url).toBe("https://cdn.example/game.zip");
    expect(preferredDomainArtifactAction(current, value, "copy", Date.parse("2026-07-17T01:00:00Z"))).toBeNull();
  });

  it("allows unsigned metadata-only URLs when the domain has no live probe", () => {
    const current = domain("hoyo", ["packages", "chunks"], "bh3");
    current.capability_contract = {
      actions: { open: "conditional", copy: "conditional", download: "conditional" },
      availability_source_kinds: ["metadata_inference"],
      live_probe: false,
    };
    const value = artifact([{
      id: 1,
      url: "https://cdn.example/chunk-manifest",
      priority: 0,
      source_kind: "official",
      evidence_status: "no_evidence",
      current: null,
    }]);

    expect(preferredDomainArtifactAction(current, value, "download")?.url).toBe("https://cdn.example/chunk-manifest");
  });

  it("requires verified evidence even when the canonical state is available", () => {
    const current = availability({ evidence_status: "unverified" });
    const value = artifact([{ id: 1, url: "https://cdn.example/game.zip", priority: 0, source_kind: "official", current }]);
    expect(isAvailabilityActionable(current, value.urls[0].url, Date.parse("2026-07-17T01:00:00Z"))).toBe(false);
    expect(preferredArtifactAction(value, Date.parse("2026-07-17T01:00:00Z"))).toBeNull();
    expect(artifactActionLabel(value, Date.parse("2026-07-17T01:00:00Z"))).toBe("未验证");
  });

  it("exposes only verified and unexpired availability as an action", () => {
    const current = artifact([{ id: 1, url: "https://cdn.example/game.zip", priority: 0, source_kind: "official", current: availability() }]);
    expect(preferredArtifactAction(current, Date.parse("2026-07-17T01:00:00Z"))?.url).toBe("https://cdn.example/game.zip");
    expect(artifactActionLabel(current, Date.parse("2026-07-17T01:00:00Z"))).toBe("可用");
  });

  it.each([
    ["unavailable", availability({ state: "unavailable", reason: "http_404" }), "不可用"],
    ["failed live probe", availability({ state: "unknown", reason: "probe_failed" }), "探测失败"],
    ["unknown", availability({ state: "unknown", reason: "not_probed" }), "探测未判定"],
    ["available but not probed", availability({ reason: "not_probed" }), "未验证"],
  ])("does not expose %s evidence as an action", (_name, current, label) => {
    const value = artifact([{ id: 1, url: "https://cdn.example/game.zip", priority: 0, source_kind: "official", current }]);
    expect(preferredArtifactAction(value, Date.parse("2026-07-17T01:00:00Z"))).toBeNull();
    expect(artifactActionLabel(value, Date.parse("2026-07-17T01:00:00Z"))).toBe(label);
  });

  it("does not expose expired signed URLs or signed URLs without expiry evidence", () => {
    const signedUrl = `https://cdn.example/game.zip?${["auth", "key"].join("_")}=1-a-b`;
    const expired = artifact([{ id: 1, url: signedUrl, priority: 0, source_kind: "official", current: availability({ expires_at: "2026-07-17T00:30:00Z" }) }]);
    const missingExpiry = artifact([{ id: 2, url: signedUrl, priority: 0, source_kind: "official", current: availability() }]);
    const now = Date.parse("2026-07-17T01:00:00Z");
    expect(preferredArtifactAction(expired, now)).toBeNull();
    expect(artifactActionLabel(expired, now)).toBe("链接已过期");
    expect(preferredArtifactAction(missingExpiry, now)).toBeNull();
  });

  it("falls back to a verified mirror when the official candidate is unavailable", () => {
    const value = artifact([
      { id: 1, url: "https://official.example/game.zip", priority: 0, source_kind: "official", current: availability({ state: "unavailable", reason: "http_404" }) },
      { id: 2, url: "https://mirror.example/game.zip", priority: 1, source_kind: "mirror", current: availability() },
    ]);
    expect(preferredArtifactAction(value, Date.parse("2026-07-17T01:00:00Z"))?.source_kind).toBe("mirror");
    expect(artifactActionLabel(value, Date.parse("2026-07-17T01:00:00Z"))).toBe("镜像可用");
  });

  it("uses availability counts for the selected artifact kind", () => {
    const item = summary({
      availability_states: { available: 8, unknown: 2 },
      artifact_kinds: {
        package: { count: 2, size: 500, availability_states: { available: 2 } },
        chunk: { count: 4, size: 400, availability_states: { unknown: 4 } },
      },
    });
    expect(availabilityStatesForMode(item, "packages")).toEqual({ available: 2 });
    expect(availabilityStatesForMode(item, "chunks")).toEqual({ unknown: 4 });
    expect(overview(domain("hoyo", ["packages", "chunks"], "hk4e"), "chunks", item).overviewMetrics[5].value).toBe("未判定");
  });

  it("summarizes every URL candidate instead of only the first CDN", () => {
    expect(artifactUrlStateCounts({
      id: 1, kind: "file", name: "game.bin", part: 1, size: 1,
      checksum_type: null, checksum_value: null, attributes: {},
      urls: [
        { id: 1, url: "https://a.example/game.bin", priority: 0, source_kind: "official", evidence_status: "verified", current: availability() },
        { id: 2, url: "https://b.example/game.bin", priority: 1, source_kind: "official", evidence_status: "verified", current: availability({ state: "unavailable", reason: "http_404" }) },
        { id: 3, url: "https://c.example/game.bin", priority: 2, source_kind: "official", evidence_status: "no_evidence", current: null },
        { id: 4, url: "https://d.example/game.bin", priority: 3, source_kind: "official", evidence_status: "unverified", current: availability({ evidence_status: "unverified", reason: "not_probed", source_kind: "metadata_inference" }) },
      ],
    })).toEqual({ available: 1, unavailable: 1, unknown: 2 });
  });

  it("drives WuWa split, provider and action rendering from the capability contract", () => {
    const current = domain("generic", ["files", "patches", "archive", "compare"], "capability-game");
    current.capability_contract = {
      features: { split_versions: "supported", package_file_list: "supported", multi_cdn: "supported", provenance: "supported" },
      actions: { open: "conditional", copy: "conditional", download: "conditional" },
      url_providers: ["cdn-a.example", "cdn-b.example", "cdn-c.example"],
    };
    const item = summary({
      provenance: { source_kind: "tomyjan-import", publication_state: "promoted" },
      attributes: { region: "cn", channel: "live", cdn_count: 3, patch_route_count: 1 },
      artifact_kinds: { file: { count: 696, size: 100 }, patch: { count: 40, size: 20 } },
    });
    expect(domainFeatureSupport(current, "multi_cdn")).toBe(true);
    expect(domainActionSupport(current, "open")).toBe(true);
    expect(buildVersionBadges(current, item, (value) => value)).toEqual([
      { label: "文件清单", tone: "blue" },
    ]);
    expect(overview(current, "files", item).moduleDetails).toEqual([
      { label: "区服", value: "CN · live" },
      { label: "文件清单", value: "696 个" },
      { label: "更新路线", value: "1 条" },
    ]);
  });

  it("prefers an explicit file creation time", () => {
    const item = summary({ attributes: { file_created_at: "2025-01-02T03:04:05+08:00", decompressed_path: "/20250321105946/build/", last_modified: "Sat, 09 May 2026 10:31:05 GMT" } });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2025-01-02T03:04:05+08:00", source: "created" });
  });

  it("prefers an official build-path timestamp over a mutable Last-Modified header", () => {
    const item = summary({ attributes: { decompressed_path: "/game/20250717152657_HmMWzKltujR0bm3L/client/", last_modified: "Sat, 09 May 2026 10:30:35 GMT" } });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2025-07-17T15:26:57+08:00", source: "created" });
  });

  it("uses server upload time when no creation or official path timestamp exists", () => {
    const item = summary({ attributes: { last_modified: "Mon, 20 Jan 2025 02:57:34 GMT" } });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2025-01-20T02:57:34.000Z", source: "uploaded" });
  });

  it("prefers explicit API time fields over timestamps embedded in paths", () => {
    const item = summary({
      source_updated_at: "2025-07-11T03:25:37+00:00",
      attributes: { decompressed_path: "/client/20260717152657/" },
    });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2025-07-11T03:25:37.000Z", source: "uploaded" });
  });

  it("extracts a timestamp from other official filename or path evidence", () => {
    const item = summary({ attributes: { source_file: "launcher_manifest_20250321.json" } });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2025-03-21T00:00:00+08:00", source: "extracted" });
  });

  it("does not fall back to the archive observation time", () => {
    const item = summary({ observed_at: "2026-07-11T05:53:30Z", attributes: {} });
    expect(fileTimestampEvidence(item)).toEqual({ value: null, source: "unknown" });
    expect(overview(domain("hoyo", ["packages"], "bh3"), "packages", item).overviewMetrics[2]).toEqual({ label: "文件时间", value: "—" });
  });

  it("labels explicit archive evidence without calling it file time", () => {
    const item = summary({ attributes: { archived_at: "2026-05-29T02:05:32Z", time_kind: "archive" } });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2026-05-29T02:05:32.000Z", source: "archived" });
    expect(overview(domain("endfield", ["packages"], "endfield"), "packages", item).overviewMetrics[2]).toEqual({ label: "归档时间", value: "2026-05-29T02:05:32.000Z" });
  });

  it("labels sourced release evidence as release time instead of file time", () => {
    const item = summary({ attributes: {
      release_date: "2020-04-16", release_precision: "date", time_kind: "release",
      release_source_kind: "mirrored_official_announcement",
    } });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2020-04-16", source: "released" });
    expect(overview(domain("hoyo", ["packages"], "bh3"), "packages", item).overviewMetrics[2]).toEqual({ label: "发布时间", value: "2020-04-16" });
  });

  it("still prefers a real file time over release evidence", () => {
    const item = summary({ attributes: { file_created_at: "2020-04-15T09:00:00+08:00", release_date: "2020-04-16" } });
    expect(fileTimestampEvidence(item)).toEqual({ value: "2020-04-15T09:00:00+08:00", source: "created" });
  });

});


describe("sync status presentation", () => {
  it("uses Android as the primary latest metric for Android-only games", () => {
    const android = domain("android", ["apk"], "snowbreak", "android", "snowbreak-android");
    android.kind = "apk";
    android.latest_version = "4.7.0";

    const result = buildSyncStatusPresentation({
      domains: [android],
      currentDomain: android,
      currentLatest: summary({ version: "4.7.0", artifact_kinds: { apk: { count: 1, size: 1000 } } }),
    });

    expect(result.primaryLabel).toBe("最新 Android 版本");
    expect(result.primaryLatest).toBe("4.7.0");
    expect(result.primaryDomain?.adapter).toBe("android");
    expect(result.androidSecondary).toBeNull();
  });

  it("keeps the PC label for Windows-only games", () => {
    const windows = domain("hoyo", ["packages"], "hk4e", "windows", "hk4e-pc");
    windows.latest_version = "6.0.0";

    const result = buildSyncStatusPresentation({
      domains: [windows],
      currentDomain: windows,
      currentLatest: summary({ version: "6.0.0" }),
    });

    expect(result.primaryLabel).toBe("最新 PC 版本");
    expect(result.primaryLatest).toBe("6.0.0");
    expect(result.androidSecondary).toBeNull();
  });

  it("uses Windows as primary and shows Android secondary when both exist", () => {
    const windows = domain("hoyo", ["packages"], "hkrpg", "windows", "hkrpg-pc");
    windows.latest_version = "4.8.0";
    const android = domain("android", ["apk"], "hkrpg", "android", "hkrpg-android");
    android.kind = "apk";
    android.latest_version = "4.7.0";

    const result = buildSyncStatusPresentation({
      domains: [android, windows],
      currentDomain: android,
      currentLatest: summary({ version: "4.7.0", artifact_kinds: { apk: { count: 1, size: 1000 } } }),
    });

    expect(result.primaryLabel).toBe("最新 PC 版本");
    expect(result.primaryLatest).toBe("4.8.0");
    expect(result.primaryDomain?.id).toBe("hkrpg-pc");
    expect(result.androidSecondary).toBe("4.7.0");
  });

  it("uses the actual platform label for future non-standard platforms", () => {
    const linux = domain("generic", ["packages"], "future", "linux", "future-linux");
    linux.latest_version = "1.0.0";

    const result = buildSyncStatusPresentation({
      domains: [linux],
      currentDomain: linux,
      currentLatest: summary({ version: "1.0.0" }),
    });

    expect(result.primaryLabel).toBe("最新 linux 版本");
    expect(result.primaryLatest).toBe("1.0.0");
    expect(result.primaryLabel).not.toContain("PC");
  });

  it("uses an em dash when primary latest is missing", () => {
    const windows = domain("hoyo", ["packages"], "hk4e", "windows", "hk4e-pc");
    windows.latest_version = null;

    const result = buildSyncStatusPresentation({
      domains: [windows],
      currentDomain: windows,
      currentLatest: null,
    });

    expect(result.primaryLabel).toBe("最新 PC 版本");
    expect(result.primaryLatest).toBe("—");
  });

  it("falls back to the Android adapter when legacy data has no platform", () => {
    const android = domain("android", ["apk"], "legacy", "", "legacy-android");
    android.kind = "apk";
    android.latest_version = "4.7.0";

    const result = buildSyncStatusPresentation({
      domains: [android],
      currentDomain: android,
      currentLatest: summary({ version: "4.7.0" }),
    });

    expect(result.primaryLabel).toBe("最新 Android 版本");
    expect(result.primaryLatest).toBe("4.7.0");
  });
});


describe("displayVersionLabel", () => {
  it("shows plain version numbers for multi-channel Android identities", () => {
    expect(displayVersionLabel("1.2.0@mihoyo")).toBe("1.2.0");
    expect(displayVersionLabel("1.2.0@mihoyo_8")).toBe("1.2.0");
    expect(displayVersionLabel("4.4.0")).toBe("4.4.0");
  });

  it("prefers the backend display_version attribute", () => {
    expect(displayVersionLabel("1.2.0@mihoyo", { display_version: "1.2.0", channel: "mihoyo" })).toBe("1.2.0");
  });

  it("keeps plain versions untouched", () => {
    expect(displayVersionLabel("2.7.6.1", null)).toBe("2.7.6.1");
    expect(displayVersionLabel("1.6.0", { channel: "gw" })).toBe("1.6.0");
  });
});


describe("version row availability badges", () => {
  const domain = { id: "hkrpg-android", game_id: "hkrpg", kind: "apk", platform: "android", capabilities: ["apk"], capability_contract: {}, adapter: "android", version_count: 3, latest_version: "4.4.0" };
  const base = (over: Record<string, unknown>) => ({
    version: "1.2.0@mihoyo", current_revision_id: 1, revision_count: 1, observed_at: "2026-07-03T00:00:00Z",
    packed_size: 1, unpacked_size: 1, artifact_count: 2,
    artifact_kinds: { apk: { count: 2, size: 1 } },
    availability_states: { available: 2 }, attributes: { channel: "mihoyo" }, provenance: {},
    ...over,
  });

  it("shows 不可用 in red when every URL is unavailable", () => {
    const badges = buildVersionBadges(domain, base({ artifact_count: 2, availability_states: { unavailable: 2 } }) as VersionSummary, () => "");
    const failed = badges.find((b) => b.label === "不可用");
    expect(failed?.tone).toBe("red");
  });

  it("does not warn when at least one collapsed URL remains available", () => {
    const badges = buildVersionBadges(domain, base({ artifact_count: 2, availability_states: { available: 1, unavailable: 1 } }) as VersionSummary, () => "");
    expect(badges.some((b) => b.label.includes("不可用") || b.label.includes("失效"))).toBe(false);
  });

  it("omits the availability badge when every channel is available", () => {
    const badges = buildVersionBadges(domain, base({ artifact_count: 2, availability_states: { available: 2 } }) as VersionSummary, () => "");
    expect(badges.some((b) => b.label.includes("失效"))).toBe(false);
  });

  it("omits the channel count badge", () => {
    const badges = buildVersionBadges(domain, base({}) as VersionSummary, () => "");
    expect(badges.some((b) => b.label.includes("渠道"))).toBe(false);
  });

  it("omits URL availability badges for fragment file catalogs", () => {
    const fileDomain = { id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows", capabilities: ["files", "patches"], capability_contract: {}, adapter: "wuwa", version_count: 1, latest_version: "1.0" } as ArchiveDomain;
    const item = summary({
      artifact_count: 2,
      artifact_kinds: { file: { count: 2, size: 2, availability_states: { unavailable: 2 } } },
      availability_states: { unavailable: 2 },
    });
    const badges = buildVersionBadges(fileDomain, item, () => "", false);
    expect(badges.map((badge) => badge.label)).toContain("文件清单");
    expect(badges.some((badge) => badge.label.includes("失效"))).toBe(false);
    expect(buildVersionBadges(fileDomain, item, () => "").map((badge) => badge.label)).toContain("链接失效");
  });

  it("scopes availability badge by the active mode kind", () => {
    const hoyoDomain = { id: "hk4e-pc", game_id: "hk4e", kind: "mixed", platform: "windows", capabilities: ["packages", "patches"], capability_contract: {}, adapter: "hoyo", version_count: 1, latest_version: "3.4.0" } as ArchiveDomain;
    const version340 = summary({
      artifact_count: 20,
      artifact_kinds: {
        package: { count: 10, size: 100, availability_states: { available: 0, unavailable: 10, unknown: 0 } },
        patch: { count: 10, size: 50, availability_states: { available: 8, unavailable: 2, unknown: 0 } },
      },
      availability_states: { available: 8, unavailable: 12, unknown: 0 },
    });
    // Non-WuWa modes retain the version-level summary stats.
    const packageBadges = buildVersionBadges(hoyoDomain, version340, () => "", true, "packages");
    expect(packageBadges.map((b) => b.label)).toContain("含失效 12");

    // Patches mode follows the same legacy version-level behavior.
    const patchBadges = buildVersionBadges(hoyoDomain, version340, () => "", true, "patches");
    expect(patchBadges.map((b) => b.label)).toContain("含失效 12");
  });

  it.each([
    ["package only", { package: { count: 2, size: 10, availability_states: { available: 2 } } }, false],
    ["patch only", { patch: { count: 2, size: 10, availability_states: { available: 2 } } }, false],
    ["package and patch preserve unavailable counts", {
      package: { count: 1, size: 10, availability_states: { available: 1 } },
      patch: { count: 1, size: 10, availability_states: { unavailable: 1 } },
    }, true],
    ["no package or patch", {}, false],
  ])("uses package/patch summary stats for WuWa files (%s)", (_name, artifact_kinds, hasUnavailable) => {
    const wuwaDomain = { id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows", capabilities: ["files", "patches"], capability_contract: {}, adapter: "wuwa", version_count: 1, latest_version: "1.0" } as ArchiveDomain;
    const badges = buildVersionBadges(wuwaDomain, summary({ artifact_count: 0, artifact_kinds, availability_states: {} }), () => "", true, "files");
    const labels = badges.map((badge) => badge.label);
    expect(labels).not.toContain("无数据");
    if (hasUnavailable) expect(labels).toContain("含失效 1");
  });

  it("treats a local-only WuWa file manifest as archived", () => {
    const wuwaDomain = { id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows", capabilities: ["files", "patches"], capability_contract: {}, adapter: "wuwa", version_count: 1, latest_version: "2.6.0" } as ArchiveDomain;
    const item = summary({
      artifact_count: 1,
      artifact_kinds: { package: { count: 1, size: 10, availability_states: { unknown: 1 } } },
      availability_states: { unknown: 1 },
      attributes: { delivery_mode: "file_manifest", local_manifest: "kuro/wuwa/pc/manifests/2.6.0.json", manifest_urls: [] },
    });
    const labels = buildVersionBadges(wuwaDomain, item, () => "", true, "files").map((badge) => badge.label);
    expect(labels).toContain("已归档");
    expect(labels).not.toContain("未判定");
    expect(availabilityStatesForMode(item, "files", "wuwa")).toEqual({});
  });

  it.each([
    ["remote package and patch are available", {
      artifact_kinds: {
        package: { count: 1, size: 10, availability_states: { available: 1 } },
        patch: { count: 1, size: 5, availability_states: { available: 1 } },
      },
      attributes: { delivery_mode: "file_manifest", manifest_urls: ["https://cdn.test/indexFile.json"] },
    }, "可用"],
    ["local package does not hide an unprobed remote patch", {
      artifact_kinds: {
        package: { count: 1, size: 10, availability_states: { unknown: 1 } },
        patch: { count: 1, size: 5, availability_states: { unknown: 1 } },
      },
      attributes: { delivery_mode: "file_manifest", local_manifest: "kuro/wuwa/pc/manifests/2.6.0.json", manifest_urls: [] },
    }, "未判定"],
    ["all remote candidates failing remains unavailable", {
      artifact_kinds: {
        package: { count: 1, size: 10, availability_states: { unavailable: 1 } },
        patch: { count: 1, size: 5, availability_states: { unavailable: 1 } },
      },
      attributes: { delivery_mode: "file_manifest", manifest_urls: ["https://cdn.test/indexFile.json"] },
    }, "链接失效"],
  ])("preserves WuWa manifest status semantics (%s)", (_name, over, expected) => {
    const wuwaDomain = { id: "wuwa-pc", game_id: "wuwa", kind: "mixed", platform: "windows", capabilities: ["files", "patches"], capability_contract: {}, adapter: "wuwa", version_count: 1, latest_version: "3.6.0" } as ArchiveDomain;
    const item = summary({ ...over, artifact_count: 2, availability_states: {} });
    const labels = buildVersionBadges(wuwaDomain, item, () => "", true, "files").map((badge) => badge.label);
    if (expected === "可用") {
      expect(availabilityStatesForMode(item, "files", "wuwa")).toEqual({ available: 2 });
    } else if (expected === "未判定") {
      expect(availabilityStatesForMode(item, "files", "wuwa")).toEqual({ unknown: 1 });
    } else {
      expect(labels).toContain(expected);
    }
  });
});


describe("multi-channel module details", () => {
  const domain = { id: "hkrpg-android", game_id: "hkrpg", kind: "apk", platform: "android", capabilities: ["apk"], capability_contract: {}, adapter: "android", version_count: 3, latest_version: "4.4.0" };
  const item = (over: Record<string, unknown>) => ({
    version: "1.2.0@mihoyo", current_revision_id: 1, revision_count: 1, observed_at: "2026-07-03T00:00:00Z",
    packed_size: 1, unpacked_size: 1, artifact_count: 1,
    artifact_kinds: { apk: { count: 1, size: 1 } },
    availability_states: { available: 1 }, attributes: { channel: "mihoyo" }, provenance: {},
    ...over,
  });

  it("aggregates channel ids and availability across channel summaries", () => {
    const overview = buildArchiveOverview({
      domain,
      summary: item({}) as VersionSummary,
      mode: "apk",
      version: "1.2.0@mihoyo",
      displayVersion: "1.2.0",
      channelSummaries: [
        item({ version: "1.2.0@mihoyo_8", attributes: { channel: "mihoyo_8" }, availability_states: { unavailable: 1 } }) as VersionSummary,
      ],
      formatBytes: (n: number) => String(n),
      formatDate: () => "",
    });
    const channelRow = overview.moduleDetails.find((row) => row.label === "渠道标识");
    expect(channelRow?.value).toBe("mihoyo / mihoyo_8");
    const linkRow = overview.moduleDetails.find((row) => row.label === "链接状态");
    expect(linkRow?.value).toBe("部分可达");
  });
});
