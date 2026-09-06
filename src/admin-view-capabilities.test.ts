import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { adminApi } from "./api";
import AdminView from "./views/AdminView.vue";

async function flushUpdates(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await Promise.resolve();
    await nextTick();
  }
  await new Promise((resolve) => window.setTimeout(resolve, 0));
}

function mockAdminApi(platform: "android" | "windows", pcAvailability: "available" | "unavailable" | "unknown" | "none" = "unknown") {
  const pcStates = pcAvailability === "available"
    ? { available: 1, unknown: 0, unavailable: 0 }
    : pcAvailability === "unavailable"
      ? { available: 0, unknown: 0, unavailable: 1 }
      : { available: 0, unknown: 1, unavailable: 0 };
  const pcArtifactKinds = pcAvailability === "none"
    ? {}
    : { package: { count: 1, size: 1024, availability_states: pcStates } };
  const pcSummaryStates = pcAvailability === "none" ? {} : pcStates;
  vi.spyOn(adminApi, "catalog").mockResolvedValue({
    games: [{
      id: "demo",
      name: "演示游戏",
      sub_name: "Demo Game",
      platform: platform === "android" ? "Android" : "PC",
      icon_source: "",
      version_count: 1,
      latest_version: "1.0.0",
      is_enabled: true,
      sort_order: 0,
    }],
    domains: [{
      id: `demo-${platform === "android" ? "android" : "pc"}`,
      game_id: "demo",
      kind: platform === "android" ? "apk" : "packages",
      platform,
      capabilities: platform === "android" ? ["apk"] : ["packages", "patches"],
      adapter: platform === "android" ? "android" : "generic",
      version_count: 1,
      latest_version: "1.0.0",
      is_enabled: true,
      sort_order: 0,
    }],
  } as never);
  vi.spyOn(adminApi, "syncStatus").mockResolvedValue(null as never);
  vi.spyOn(adminApi, "syncRunStatus").mockResolvedValue(null as never);
  vi.spyOn(adminApi, "versions").mockResolvedValue({
    items: [{
      version: "1.0.0",
      is_visible: true,
      packed_size: 1024,
      artifact_kinds: platform === "android"
        ? { apk: { count: 1, size: 1024, availability_states: { available: 1, unknown: 0, unavailable: 0 } } }
        : pcArtifactKinds,
      availability_states: platform === "android"
        ? { available: 1, unknown: 0, unavailable: 0 }
        : pcSummaryStates,
    }],
  } as never);
  vi.spyOn(adminApi, "editableVersion").mockImplementation((async () => {
    if (platform === "windows") {
      return {
        version: "1.0.0",
        client_version: "1.0.0",
        observed_at: null,
        file_created_at_override: "2026-08-29T00:00:00Z",
        file_path: "",
        unpacked_size: 0,
        files_checksum_type: null,
        files_checksum_value: null,
        attributes: { channel: "official", version_code: null },
        is_visible: true,
        artifacts: [{
          kind: "package",
          name: "pkg_1.zip",
          part: 1,
          size: 1024,
          checksum_type: "md5",
          checksum_value: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          attributes: {
            component: "game",
            package_type: "segment",
            delivery_mode: "direct",
          },
          urls: [{ id: 1, url: "https://example.com/pkg_1.zip", priority: 0, source_kind: "official" }],
        }],
      };
    }
    return {
      version: "1.0.0",
      client_version: "1.0.0",
      observed_at: null,
      file_created_at_override: "2026-08-29T00:00:00Z",
      file_path: "base.apk",
      unpacked_size: 0,
      files_checksum_type: null,
      files_checksum_value: null,
      attributes: { channel: "official", version_code: 1 },
      is_visible: true,
      artifacts: [{
        kind: "file",
        name: "base.apk",
        part: 1,
        size: 1024,
        checksum_type: "md5",
        checksum_value: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        attributes: {},
        urls: [{ id: 1, url: "https://example.com/base.apk", priority: 0, source_kind: "official" }],
      }],
    };
  }) as never);
  vi.spyOn(adminApi, "updateEditableVersion").mockResolvedValue({
    domain_id: "demo-pc",
    version: "1.0.0",
    revisions_created: 1,
    revisions_reused: 0,
    capture_event_id: 1,
    changed: true,
  } as never);
  vi.spyOn(adminApi, "addVersion").mockResolvedValue({
    domain_id: "demo-android",
    version: "2.0.0",
    revisions_created: 1,
    revisions_reused: 0,
    capture_event_id: 1,
    changed: true,
  } as never);
  vi.spyOn(adminApi, "probeVersion").mockResolvedValue({} as never);
  vi.spyOn(adminApi, "probeStatus").mockResolvedValue({ running: false, log: [] } as never);
  vi.spyOn(adminApi, "probeSchedule").mockResolvedValue({ enabled: false, interval_hours: 24, mode: "normal" });
  vi.spyOn(adminApi, "syncSchedule").mockResolvedValue({ enabled: false, times: ["04:45", "14:00"] });
}

async function mountAdmin(platform: "android" | "windows", pcAvailability: "available" | "unavailable" | "unknown" | "none" = "unknown") {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
  mockAdminApi(platform, pcAvailability);
  localStorage.setItem("game-manifest-index-web-admin-token-v1", "test-admin-token");
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/admin", component: { template: "<div />" } },
    ],
  });
  await router.push("/admin");
  await router.isReady();
  const root = document.createElement("div");
  document.body.appendChild(root);
  const app = createApp(AdminView);
  app.use(router);
  app.mount(root);
  await flushUpdates();
  return { app, root };
}

function buttonByText(root: HTMLElement, text: string): HTMLButtonElement {
  const button = [...root.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => item.textContent?.includes(text));
  if (!button) throw new Error(`button not found: ${text}`);
  return button;
}

function operationJob(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    job_id: "probe-job-1", status: "finished", phase: null,
    actions: ["probe"], game_ids: ["demo"], scope: "all",
    completed: 1, total: 1, phase_completed: 1, phase_total: 1,
    succeeded: 1, failed: 0, current: null,
    started_at: "2026-08-29T00:00:00Z", finished_at: "2026-08-29T00:01:00Z",
    result: {}, error: null, logs: [],
    ...overrides,
  };
}

async function mountResumedOperation(jobFactory: () => Record<string, unknown>): Promise<{ app: ReturnType<typeof createApp>; root: HTMLElement }> {
  let calls = 0;
  vi.spyOn(adminApi, "operationStatus").mockImplementation((async () => {
    calls += 1;
    return calls === 1
      ? jobFactory()
      : { ...jobFactory(), status: "finished", phase: null, finished_at: "2026-08-29T00:01:00Z" };
  }) as never);
  sessionStorage.setItem("game-manifest-index-web-operation-job-v1", "probe-job-1");
  const { app, root } = await mountAdmin("windows");
  await vi.advanceTimersByTimeAsync(1100);
  await vi.advanceTimersByTimeAsync(1100);
  return { app, root };
}

describe("AdminView capability alignment", () => {
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    document.body.innerHTML = "";
    Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
    vi.restoreAllMocks();
  });

  it("exposes catalog mutation controls and disables unavailable retention", async () => {
    const { app, root } = await mountAdmin("android");
    expect(root.textContent).not.toContain("游戏目录由当前 V5 静态注册关系和数据投影生成");
    expect(root.textContent).toContain("新增游戏");
    expect(root.textContent).toContain("保存游戏设置");
    expect(root.textContent).toContain("删除空游戏");
    expect(buttonByText(root, "未接入").disabled).toBe(true);
    app.unmount();
  });

  it("passes edited game fields from the catalog component to the save API", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const update = vi.spyOn(adminApi, "updateGame").mockResolvedValue({} as never);
    const { app, root } = await mountAdmin("android");
    const form = root.querySelector<HTMLFormElement>(".game-form-pane");
    if (!form) throw new Error("game catalog form not found");
    const name = [...form.querySelectorAll<HTMLInputElement>("input")]
      .find((input) => input.value === "演示游戏");
    const order = form.querySelector<HTMLInputElement>("input[type='number']");
    const enabled = form.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (!name || !order || !enabled) throw new Error("game catalog fields not found");
    name.value = "修改后的游戏名称";
    name.dispatchEvent(new Event("input"));
    await flushUpdates();
    order.value = "7";
    order.dispatchEvent(new Event("input"));
    await flushUpdates();
    enabled.checked = false;
    enabled.dispatchEvent(new Event("change"));
    await flushUpdates();
    buttonByText(root, "保存游戏设置").click();
    await flushUpdates();
    expect(update).toHaveBeenCalledTimes(1);
    expect(update.mock.calls[0][0]).toBe("demo");
    expect(update.mock.calls[0][1]).toMatchObject({
      id: "demo", name: "修改后的游戏名称", sort_order: 7, is_enabled: false,
    });
    app.unmount();
  });

  it("passes edited module fields to the existing save API", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const update = vi.spyOn(adminApi, "updateDomain").mockResolvedValue({} as never);
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "模块").click();
    await flushUpdates();
    const form = root.querySelector<HTMLFormElement>(".domain-form-pane");
    if (!form) throw new Error("module form not found");
    const adapter = form.querySelector<HTMLInputElement>("input[placeholder^='hoyo /']");
    const capabilities = form.querySelector<HTMLInputElement>(".raw-cap-input");
    const order = form.querySelector<HTMLInputElement>("input[type='number']");
    const enabled = form.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (!adapter || !capabilities || !order || !enabled) throw new Error("module fields not found");
    for (const [input, value] of [[adapter, "hoyo"], [capabilities, "packages, archive"], [order, "7"]] as const) {
      input.value = value;
      input.dispatchEvent(new Event("input"));
      await flushUpdates();
    }
    enabled.checked = false;
    enabled.dispatchEvent(new Event("change"));
    await flushUpdates();
    buttonByText(root, "保存模块配置").click();
    await flushUpdates();
    expect(update).toHaveBeenCalledTimes(1);
    expect(update.mock.calls[0][0]).toBe("demo-pc");
    expect(update.mock.calls[0][1]).toMatchObject({
      id: "demo-pc", game_id: "demo", platform: "windows", adapter: "hoyo",
      capabilities: ["packages", "archive"], sort_order: 7, is_enabled: false,
    });
    app.unmount();
  });

  it("keeps module game filtering and search when switching tabs", async () => {
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "模块").click();
    await flushUpdates();
    const pane = root.querySelector<HTMLElement>(".domain-list-pane");
    if (!pane) throw new Error("module list not found");
    pane.querySelector<HTMLButtonElement>(".custom-select-trigger")?.click();
    await flushUpdates();
    buttonByText(pane, "演示游戏 (1)").click();
    await flushUpdates();
    const search = pane.querySelector<HTMLInputElement>("input[type='search']");
    if (!search) throw new Error("module search not found");
    search.value = "no-match";
    search.dispatchEvent(new Event("input"));
    await flushUpdates();
    expect(pane.textContent).toContain("未找到匹配的数据模块");
    buttonByText(root, "游戏").click();
    await flushUpdates();
    buttonByText(root, "模块").click();
    await flushUpdates();
    expect(root.querySelector<HTMLInputElement>(".domain-list-pane input[type='search']")?.value).toBe("no-match");
    expect(root.querySelector(".domain-list-pane .trigger-label")?.textContent).toContain("演示游戏 (1)");
    expect(root.querySelectorAll(".domain-list-pane .domain-item")).toHaveLength(0);
    app.unmount();
  });

  it("keeps the game catalog search query when switching tabs", async () => {
    const { app, root } = await mountAdmin("android");
    const search = root.querySelector<HTMLInputElement>(".game-list-pane input[type='search']");
    if (!search) throw new Error("game catalog search input not found");
    search.value = "no-match";
    search.dispatchEvent(new Event("input"));
    await flushUpdates();
    expect(root.textContent).toContain("未找到匹配的游戏入口");

    buttonByText(root, "模块").click();
    await flushUpdates();
    buttonByText(root, "游戏").click();
    await flushUpdates();
    const restoredSearch = root.querySelector<HTMLInputElement>(".game-list-pane input[type='search']");
    expect(restoredSearch?.value).toBe("no-match");
    app.unmount();
  });

  it("uses version summary availability for the edit health banner", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "版本").click();
    await flushUpdates();
    expect(root.textContent).toContain("链接可用");
    expect(root.textContent).not.toContain("待探活");
    app.unmount();
  });

  it("exposes a PC artifact edit workspace without the APK-only create flow", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "版本").click();
    await flushUpdates();
    expect(root.textContent).not.toContain("PC 版本只读");
    expect(root.textContent).toContain("PC 资源文件");
    expect(root.textContent).toContain("添加资源");
    expect(root.textContent).toContain("尚未探活");
    expect(root.querySelector(".version-status-dot.unknown")).not.toBeNull();
    expect(root.querySelector(".version-status-dot.available")).toBeNull();
    expect(root.textContent).not.toContain("新建版本");
    expect(root.textContent).not.toContain("APK 文件");
    expect(adminApi.editableVersion).toHaveBeenCalledWith("demo-pc", "1.0.0", "test-admin-token");

    const nameInput = [...root.querySelectorAll<HTMLInputElement>("input")]
      .find((input) => input.value === "pkg_1.zip");
    if (!nameInput) throw new Error("PC artifact name input not found");
    nameInput.value = "pkg_1_v2.zip";
    nameInput.dispatchEvent(new Event("input"));
    await flushUpdates();

    buttonByText(root, "保存更改").click();
    await flushUpdates();

    expect(adminApi.updateEditableVersion).toHaveBeenCalled();
    const payload = vi.mocked(adminApi.updateEditableVersion).mock.calls[0][2];
    expect(payload.file_path).toBeUndefined();
    expect(payload.artifacts?.[0]).toMatchObject({
      kind: "package",
      name: "pkg_1_v2.zip",
      attributes: {
        component: "game",
        package_type: "segment",
        delivery_mode: "direct",
      },
    });
    app.unmount();
  });

  it("keeps edit and create URL filename inference behavior aligned", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { app, root } = await mountAdmin("android");
    const updateVersion = vi.mocked(adminApi.updateEditableVersion);
    const addVersion = vi.mocked(adminApi.addVersion);
    buttonByText(root, "版本").click();
    await flushUpdates();

    const editForm = root.querySelector<HTMLFormElement>(".version-edit-form");
    if (!editForm) throw new Error("edit form not found");
    const editName = editForm.querySelector<HTMLInputElement>(".apk-file-card input[placeholder^='例如']");
    const editUrl = editForm.querySelector<HTMLInputElement>(".apk-file-card input.url-long-input");
    if (!editName || !editUrl) throw new Error("edit artifact fields not found");
    editName.value = "custom-name.apk";
    editName.dispatchEvent(new Event("input"));
    editUrl.value = "https://example.com/renamed.apk";
    editUrl.dispatchEvent(new Event("input"));
    await flushUpdates();
    expect(editName.value).toBe("custom-name.apk");
    buttonByText(root, "根据 URL 填写文件名").click();
    await flushUpdates();
    expect(editName.value).toBe("renamed.apk");
    buttonByText(root, "保存并探活").click();
    await flushUpdates();
    expect(localStorage.getItem("gmi-availability-invalidated-at")).toContain("version-probe:demo-android:1.0.0");
    expect(updateVersion).toHaveBeenCalledWith("demo-android", "1.0.0", expect.objectContaining({
      artifacts: [expect.objectContaining({ kind: "apk", name: "renamed.apk" })],
    }), "test-admin-token", expect.anything());

    buttonByText(root, "新建版本").click();
    await flushUpdates();
    const createForm = root.querySelector<HTMLFormElement>(".version-create-form");
    if (!createForm) throw new Error("create form not found");
    const version = createForm.querySelector<HTMLInputElement>("input[placeholder^='例如: 7.1.0']");
    const createUrl = createForm.querySelector<HTMLInputElement>("input.url-long-input");
    if (!version || !createUrl) throw new Error("create artifact fields not found");
    version.value = "2.0.0";
    version.dispatchEvent(new Event("input"));
    createUrl.value = "https://example.com/new.apk";
    createUrl.dispatchEvent(new Event("input"));
    await flushUpdates();
    expect(createForm.querySelector<HTMLInputElement>(".apk-file-card input[placeholder^='例如']")?.value).toBe("new.apk");
    buttonByText(root, "保存并录入新版本").click();
    await flushUpdates();
    expect(addVersion).toHaveBeenCalledWith("demo-android", expect.objectContaining({
      artifacts: [expect.objectContaining({ kind: "apk", name: "new.apk", urls: [expect.objectContaining({ url: "https://example.com/new.apk" })] })],
    }), "test-admin-token", expect.anything());
    app.unmount();
  });

  it("uses aggregate PC availability states for available and unavailable versions", async () => {
    const available = await mountAdmin("windows", "available");
    buttonByText(available.root, "版本").click();
    await flushUpdates();
    expect(available.root.querySelector(".version-status-dot.available")).not.toBeNull();
    expect(available.root.querySelector(".version-status-dot.unknown")).toBeNull();
    expect(available.root.textContent).toContain("链接可用");
    available.app.unmount();

    document.body.innerHTML = "";
    const unavailable = await mountAdmin("windows", "unavailable");
    buttonByText(unavailable.root, "版本").click();
    await flushUpdates();
    expect(unavailable.root.querySelector(".version-status-dot.unavailable")).not.toBeNull();
    expect(unavailable.root.querySelector(".version-status-dot.unknown")).toBeNull();
    expect(unavailable.root.textContent).toContain("链接不可用");
    unavailable.app.unmount();
  });

  it("keeps a PC version unknown when availability counts are absent", async () => {
    const { app, root } = await mountAdmin("windows", "none");
    buttonByText(root, "版本").click();
    await flushUpdates();
    expect(root.querySelector(".version-status-dot.unknown")).not.toBeNull();
    expect(root.querySelector(".version-status-dot.available")).toBeNull();
    app.unmount();
  });

  it("blocks a PC patch without both route versions before sending the update", async () => {
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "版本").click();
    await flushUpdates();

    const artifactSection = root.querySelectorAll<HTMLElement>(".pc-artifact-section")[0];
    const kind = root.querySelector<HTMLSelectElement>(".pc-artifact-section select");
    const packageType = artifactSection.querySelector<HTMLInputElement>("input[placeholder^='full / segment']");
    if (!kind || !packageType) throw new Error("PC artifact type fields not found");
    kind.value = "patch";
    kind.dispatchEvent(new Event("change"));
    packageType.value = "differential";
    packageType.dispatchEvent(new Event("input"));
    await flushUpdates();

    buttonByText(root, "保存更改").click();
    await flushUpdates();
    expect(adminApi.updateEditableVersion).not.toHaveBeenCalled();
    expect(root.textContent).toContain("必须使用 differential 并填写 route_from、route_to");
    app.unmount();
  });

  it("describes schedule values as external configuration without an internal timer", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "监控").click();
    await flushUpdates();
    expect(root.textContent).toContain("这里只保存计划参数");
    expect(root.textContent).toContain("服务不会启动内置计时器");
    expect(root.textContent).toContain("时区、漏跑策略及采集动作由外部计划任务决定");
    expect(root.textContent).not.toContain("北京时间");
    app.unmount();
  });

  it("sends one availability invalidation when a probe operation finishes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const events: CustomEvent[] = [];
      const listener = (event: Event): void => { events.push(event as CustomEvent); };
      window.addEventListener("gmi-availability-invalidated", listener);
      const { app } = await mountResumedOperation(() => operationJob({ status: "running", phase: "probe", finished_at: null }));
      expect(events).toHaveLength(1);
      expect(events[0].detail).toEqual({ jobId: "probe-job-1" });
      expect(localStorage.getItem("gmi-availability-invalidated-at")).toContain("probe-job-1");
      app.unmount();
      window.removeEventListener("gmi-availability-invalidated", listener);
    } finally {
      vi.useRealTimers();
    }
  });

  it("sends a fresh availability invalidation after every successful direct version probe", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const events: CustomEvent[] = [];
    const listener = (event: Event): void => { events.push(event as CustomEvent); };
    window.addEventListener("gmi-availability-invalidated", listener);
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "版本").click();
    await flushUpdates();

    buttonByText(root, "探活并保存").click();
    await flushUpdates();
    buttonByText(root, "探活并保存").click();
    await flushUpdates();

    expect(events).toHaveLength(2);
    expect(events[0].detail.jobId).not.toBe(events[1].detail.jobId);
    app.unmount();
    window.removeEventListener("gmi-availability-invalidated", listener);
  });

  it("does not report failed save-and-probe as a completed probe", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "版本").click();
    await flushUpdates();
    const url = root.querySelector<HTMLInputElement>(".apk-file-card input.url-long-input")!;
    url.value = "https://example.com/updated.apk";
    url.dispatchEvent(new Event("input"));
    await flushUpdates();
    vi.mocked(adminApi.probeVersion).mockRejectedValueOnce(new Error("network failed"));
    buttonByText(root, "保存并探活").click();
    await flushUpdates();
    expect(root.textContent).toContain("修改已保存，但探活失败");
    expect(root.textContent).not.toContain("修改已保存并已完成探活");
    expect(localStorage.getItem("gmi-availability-invalidated-at")).toBeNull();
    app.unmount();
  });

  it("does not send availability invalidation for discovery-only operations", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const events: CustomEvent[] = [];
      const listener = (event: Event): void => { events.push(event as CustomEvent); };
      window.addEventListener("gmi-availability-invalidated", listener);
      const { app } = await mountResumedOperation(() => operationJob({ status: "running", phase: "discover", actions: ["discover"], finished_at: null }));
      expect(events).toHaveLength(0);
      expect(localStorage.getItem("gmi-availability-invalidated-at")).toBeNull();
      app.unmount();
      window.removeEventListener("gmi-availability-invalidated", listener);
    } finally {
      vi.useRealTimers();
    }
  });
});
