import { afterEach, describe, expect, it, vi } from "vitest";
import { api, apiBase, apiUrl, adminApi, requestJson } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("API client", () => {
  it("checks HTTP status and reads structured messages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: { code: "version_not_found", message: "Version not found", details: null } }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    )));
    await expect(requestJson("/missing")).rejects.toMatchObject({ status: 404, message: "Version not found" });
  });

  it("passes cancellation to fetch", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await requestJson("/games", controller.signal);
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it("preserves AbortError instead of wrapping it as a network failure", async () => {
    const aborted = Object.assign(new Error("aborted"), { name: "AbortError" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(aborted));
    await expect(requestJson("/games")).rejects.toBe(aborted);
  });

  it("builds source and request URLs from the one public API base", () => {
    expect(apiUrl("/games")).toBe("/api/v1/games");
    expect(apiUrl("domains/demo/versions")).toBe("/api/v1/domains/demo/versions");
  });

  it("loads an APK index as its raw version.json record", async () => {
    const record = {
      vendor: "mihoyo", game_id: "hk4e", platform: "android", channel: "official",
      version: "7.0.0", version_code: null, filename: "yuanshen_7.0.0.apk",
      url: "https://example.test/yuanshen_7.0.0.apk", size: 478735343,
      checksum: { etag: "etag", crc64: null, md5: null },
      file_time: "2026-08-03T07:53:01Z",
      status: { http_code: 206, available: true, last_checked_at: "2026-08-23T13:41:20Z" },
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(record), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.versionRecord("hk4e-android", "7.0.0")).resolves.toEqual(record);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/domains/hk4e-android/versions/7.0.0");
  });

  it("loads the per-game small index and adapts it for the existing picker UI", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      vendor: "mihoyo", game_id: "hk4e", platform: "android",
      versions: [{ version: "7.0.0", updated_at: "2026-08-03T07:53:01Z", available: true, size: 478735343 }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const versions = await api.versions("hk4e-android");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/domains/hk4e-android/versions");
    expect(versions[0]).toMatchObject({
      version: "7.0.0",
      source_released_at: "2026-08-03T07:53:01Z",
      packed_size: 478735343,
      availability_states: { available: 1, unavailable: 0, unknown: 0 },
    });
  });

  it("keeps a missing version time empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      versions: [{ version: "1.0.0", updated_at: null, available: null, size: null }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    const versions = await api.versions("demo-android");
    expect(versions[0].observed_at).toBeNull();
    expect(versions[0].source_released_at).toBeNull();
  });

  it("uses a configured external API base for public, admin, and export URLs", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test/gmi/api/v1/");
    expect(apiBase()).toBe("https://api.example.test/gmi/api/v1");
    expect(apiUrl("/games")).toBe("https://api.example.test/gmi/api/v1/games");
    expect(apiUrl("/domains/demo/leads")).toBe("https://api.example.test/gmi/api/v1/domains/demo/leads");

    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await adminApi.catalog("test-token");
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example.test/gmi/api/v1/admin/catalog");
  });

  it("passes availability filters to the remote artifact tree", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      prefix: "", folders: [], items: [], next_cursor: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await api.artifactTree("wuwa-pc", "3.5.0", { kind: "file", state: "available" });
    expect(fetchMock.mock.calls[0][0]).toContain("availability_state=available");
  });

  it("requests server-side comparisons with filters and cursor pagination", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      from_version: "1.0", to_version: "2.0",
      summary: { added: 1, removed: 0, changed: 0, size_delta: 10 },
      items: [], next_cursor: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await api.compare("demo-pc", {
      fromVersion: "1.0", toVersion: "2.0", kind: "file", change: "added", cursor: "next", limit: 25,
    });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/domains/demo-pc/compare?");
    expect(url).toContain("from_version=1.0");
    expect(url).toContain("to_version=2.0");
    expect(url).toContain("change=added");
    expect(url).toContain("cursor=next");
  });

  it("sends PATCH to updateEditableVersion with payload and token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ domain_id: "hkrpg-pc", version: "2.0.0" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    await adminApi.updateEditableVersion("hkrpg-pc", "2.0.0", {
      client_version: "2.0.0",
      file_path: "Games/StarRail",
      source_note: "手工修正",
    }, "admin-secret-token");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/admin/domains/hkrpg-pc/versions/2.0.0/editable");
    expect(options.method).toBe("PATCH");
    expect(options.headers.Authorization).toBe("Bearer admin-secret-token");
    expect(JSON.parse(options.body)).toEqual({
      client_version: "2.0.0",
      file_path: "Games/StarRail",
      source_note: "手工修正",
    });
  });

  it("sends PUT to saveSyncSchedule with JSON headers and payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ enabled: true, times: ["04:45", "14:00"] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));

    vi.stubGlobal("fetch", fetchMock);
    await adminApi.saveSyncSchedule({ enabled: true, times: ["04:45", "14:00"] }, "admin-secret-token");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/admin/sync/schedule");
    expect(options.method).toBe("PUT");
    expect(options.headers.Authorization).toBe("Bearer admin-secret-token");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({
      enabled: true,
      times: ["04:45", "14:00"],
    });
  });

  it("sends PUT to saveProbeSchedule with JSON headers and payload", async () => {
    const payload = { enabled: true, interval_hours: 12, mode: "full" as const };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));

    vi.stubGlobal("fetch", fetchMock);
    await adminApi.saveProbeSchedule(payload, "admin-secret-token");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/admin/probe/schedule");
    expect(options.method).toBe("PUT");
    expect(options.headers.Authorization).toBe("Bearer admin-secret-token");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual(payload);
  });

  it("uses authenticated retention config/run/status endpoints", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ cache_days: 30, observation_days: 90, interval_hours: 24 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ cache_days: 7, observation_days: 180, interval_hours: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ source: "manual", result: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ source: "manual", result: null }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await adminApi.getRetentionConfig("admin-secret-token");
    await adminApi.updateRetentionConfig({ cache_days: 7, observation_days: 180, interval_hours: 1 }, "admin-secret-token");
    await adminApi.runRetention("admin-secret-token");
    await adminApi.getRetentionStatus("admin-secret-token");
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[0][0]).toContain("/admin/retention/config");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer admin-secret-token");
    expect(fetchMock.mock.calls[1][1].method).toBe("PUT");
    expect(fetchMock.mock.calls[2][0]).toContain("/admin/retention/run");
    expect(fetchMock.mock.calls[3][0]).toContain("/admin/retention/status");
  });

  it("adds the operation log cursor only for incremental status requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ logs: ["new"], log_offset: 1, log_total: 2 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await adminApi.operationStatus("job-1", "admin-secret-token", undefined, 1);
    expect(fetchMock.mock.calls[0][0]).toContain("/admin/operations/job-1?after=1");
  });

  it("sends DELETE to deleteVersion with auth token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await adminApi.deleteVersion("hkrpg-pc", "2.0.0", "admin-secret-token");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/admin/domains/hkrpg-pc/versions/2.0.0");
    expect(options.method).toBe("DELETE");
    expect(options.headers.Authorization).toBe("Bearer admin-secret-token");
  });

  it("sends POST to probeUrl and probeUrls with JSON body", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ url: "https://example.com/test.zip", ok: true, status: 200, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);

    const res = await adminApi.probeUrl("https://example.com/test.zip", "test-token", 10, 42);
    expect(res.ok).toBe(true);
    expect(res.status).toBe(200);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/admin/probe/url");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ url: "https://example.com/test.zip", timeout: 10, artifact_url_id: 42 });

    await adminApi.probeUrls(["https://example.com/test.zip"], "test-token", 10, [42]);
    const [batchUrl, batchOptions] = fetchMock.mock.calls[1];
    expect(batchUrl).toContain("/admin/probe/urls");
    expect(JSON.parse(batchOptions.body)).toEqual({
      urls: ["https://example.com/test.zip"],
      timeout: 10,
      artifact_url_ids: [42],
    });
  });

  it("starts, polls, and cancels an admin operation", async () => {
    const mockJob = {
      job_id: "job-1",
      status: "running",
      phase: "discover",
      actions: ["discover", "probe"],
      game_ids: ["hk4e"],
      completed: 0,
      total: 6,
      phase_completed: 0,
      phase_total: 1,
      succeeded: 0,
      failed: 0,
      current: null,
      started_at: "2026-08-24T00:00:00Z",
      finished_at: null,
      result: null,
      error: null,
      logs: [],
    };
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(mockJob), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);

    const res = await adminApi.startOperation(
      { actions: ["discover", "probe"], scope: "pc", game_ids: ["hk4e"], timeout: 15, workers: 4 },
      "test-token",
    );
    expect(res.job_id).toBe("job-1");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain("/admin/operations/start");
    expect(options.method).toBe("POST");
    expect(options.headers.Authorization).toBe("Bearer test-token");
    expect(JSON.parse(options.body)).toEqual({
      actions: ["discover", "probe"],
      scope: "pc",
      game_ids: ["hk4e"],
      timeout: 15,
      workers: 4,
    });

    await adminApi.operationStatus("job-1", "test-token");
    expect(fetchMock.mock.calls[1][0]).toContain("/admin/operations/job-1");
    expect(fetchMock.mock.calls[1][1].method).toBeUndefined();

    await adminApi.cancelOperation("job-1", "test-token");
    expect(fetchMock.mock.calls[2][0]).toContain("/admin/operations/job-1/cancel");
    expect(fetchMock.mock.calls[2][1].method).toBe("POST");
  });

  it("queries chunkFiles with search parameters and path", async () => {
    const mockFiles = {
      identity: "game",
      path: "YuanShen_Data",
      q: "global",
      items: [{ name: "global-metadata.dat", path: "YuanShen_Data/global-metadata.dat", size: 1024, hash: "abc", chunk_count: 1, type: "file" as const }],
      total: 1,
      next_cursor: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(mockFiles), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await api.chunkFiles("hk4e-pc", "7.0.0", "game", { path: "YuanShen_Data", q: "global", limit: 50, cursor: "0" });
    expect(res.items.length).toBe(1);
    expect(res.items[0].name).toBe("global-metadata.dat");

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/domains/hk4e-pc/versions/7.0.0/chunk-manifests/game/files");
    expect(url).toContain("path=YuanShen_Data");
    expect(url).toContain("q=global");
    expect(url).toContain("limit=50");
    expect(url).toContain("cursor=0");
  });

  it("fetches chunkFileDetail for a single file", async () => {
    const mockDetail = {
      identity: "game",
      name: "YuanShen.exe",
      path: "YuanShen.exe",
      size: 431085976,
      hash: "e1114eb3dd032ff9162fbd97e252f717",
      chunk_count: 308,
      chunks: [{ name: "chunk_1", hash: "hash_1", offset: 0, size: 12345, size_decompressed: 23456 }],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(mockDetail), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await api.chunkFileDetail("hk4e-pc", "7.0.0", "game", "YuanShen.exe");
    expect(res.name).toBe("YuanShen.exe");
    expect(res.chunks?.length).toBe(1);

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/domains/hk4e-pc/versions/7.0.0/chunk-manifests/game/file");
    expect(url).toContain("path=YuanShen.exe");
  });

  it("queries versionFiles with source and identity parameters", async () => {
    const mockFiles = {
      source: "package_pkg_version",
      fetch_mode: "official_scattered_files",
      identity: "game",
      path: "",
      q: null,
      items: [{ name: "YuanShen.exe", path: "YuanShen.exe", size: 5382648, md5: "abc", download_url: "https://dl.com/YuanShen.exe", type: "file" as const }],
      total: 1,
      next_cursor: null,
      network_bytes: 0,
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(mockFiles), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await api.versionFiles("hk4e-pc", "4.5.0", { source: "package", identity: "game", path: "YuanShen_Data", q: "exe" });
    expect(res.source).toBe("package_pkg_version");
    expect(res.items[0].download_url).toBe("https://dl.com/YuanShen.exe");

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/domains/hk4e-pc/versions/4.5.0/files");
    expect(url).toContain("source=package");
    expect(url).toContain("identity=game");
    expect(url).toContain("path=YuanShen_Data");
    expect(url).toContain("q=exe");
  });

  it("queries versionFileDetail for a single package file", async () => {
    const mockDetail = {
      source: "package_pkg_version",
      name: "YuanShen.exe",
      path: "YuanShen.exe",
      size: 5382648,
      md5: "55d27e108ff16e2fcdd8bade44431e1d",
      download_url: "https://autopatchcn.yuanshen.com/.../YuanShen.exe",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(mockDetail), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await api.versionFileDetail("hk4e-pc", "4.5.0", { source: "package", identity: "game", path: "YuanShen.exe" });
    expect(res.name).toBe("YuanShen.exe");
    expect(res.download_url).toBe("https://autopatchcn.yuanshen.com/.../YuanShen.exe");

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/domains/hk4e-pc/versions/4.5.0/file");
    expect(url).toContain("source=package");
    expect(url).toContain("path=YuanShen.exe");
  });
});
