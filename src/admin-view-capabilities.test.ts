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
          artifact_id: "a1_pc_fixture",
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
  vi.spyOn(adminApi, "saveProbeSchedule").mockResolvedValue({ enabled: false, interval_hours: 24, mode: "normal" });
  vi.spyOn(adminApi, "probeScheduler").mockResolvedValue({
    driver: "apscheduler", running: true, enabled: false,
    next_run_at: "2026-09-15T12:00:00Z", last_started_at: "2026-09-14T12:00:00Z",
    last_job_id: "probe-job-1", error: null,
  });
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

async function acceptConfirm(): Promise<void> {
  const accept = document.querySelector<HTMLButtonElement>('[data-testid="admin-confirm-accept"]');
  if (!accept) throw new Error("confirm dialog not shown");
  accept.click();
  await flushUpdates();
  expect(document.querySelector('[data-testid="admin-confirm-backdrop"]')).toBeNull();
}

async function clickAndConfirm(root: HTMLElement, text: string): Promise<void> {
  buttonByText(root, text).click();
  await flushUpdates();
  await acceptConfirm();
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

  it("exposes catalog mutation controls without a read-only fallback", async () => {
    const { app, root } = await mountAdmin("android");
    expect(root.textContent).not.toContain("游戏目录由当前 V5 静态注册关系和数据投影生成");
    expect(root.textContent).toContain("新增游戏");
    expect(root.textContent).toContain("保存游戏设置");
    expect(root.textContent).toContain("删除空游戏");
    const deleteButton = buttonByText(root, "删除空游戏");
    expect(deleteButton.disabled).toBe(true);
    expect(deleteButton.title).toContain("不可直接删除");
    expect(root.textContent).not.toContain("未接入");
    app.unmount();
  });

  it("keeps config sections free of numbering and English kickers", async () => {
    const { app, root } = await mountAdmin("android");
    const titles = [...root.querySelectorAll(".game-form-pane .section-card-title")].map((node) =>
      node.textContent?.trim() ?? "",
    );
    expect(titles).toEqual(["基础信息", "图标", "发布"]);
    titles.forEach((title) => expect(title).not.toMatch(/^\d+\./));
    expect(root.querySelectorAll(".kicker-tag").length).toBe(0);
    expect(root.querySelectorAll(".block-tag-pill").length).toBe(0);
    app.unmount();
  });

  it("passes edited game fields from the catalog component to the save API", async () => {
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
    await clickAndConfirm(root, "保存游戏设置");
    expect(update).toHaveBeenCalledTimes(1);
    expect(update.mock.calls[0][0]).toBe("demo");
    expect(update.mock.calls[0][1]).toMatchObject({
      id: "demo", name: "修改后的游戏名称", sort_order: 7, is_enabled: false,
    });
    app.unmount();
  });

  it("asks for confirmation in an in-page dialog and honours cancel and Escape", async () => {
    const update = vi.spyOn(adminApi, "updateGame").mockResolvedValue({} as never);
    const { app, root } = await mountAdmin("android");

    buttonByText(root, "保存游戏设置").click();
    await flushUpdates();
    const backdrop = root.querySelector<HTMLElement>('[data-testid="admin-confirm-backdrop"]');
    if (!backdrop) throw new Error("confirm dialog not shown");
    expect(backdrop.textContent).toContain("保存游戏配置");

    buttonByText(backdrop, "取消").click();
    await flushUpdates();
    expect(root.querySelector('[data-testid="admin-confirm-backdrop"]')).toBeNull();
    expect(update).not.toHaveBeenCalled();

    buttonByText(root, "保存游戏设置").click();
    await flushUpdates();
    const reopened = root.querySelector<HTMLElement>('[data-testid="admin-confirm-backdrop"]');
    if (!reopened) throw new Error("confirm dialog not shown again");
    reopened.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await flushUpdates();
    expect(root.querySelector('[data-testid="admin-confirm-backdrop"]')).toBeNull();
    expect(update).not.toHaveBeenCalled();

    await clickAndConfirm(root, "保存游戏设置");
    expect(update).toHaveBeenCalledTimes(1);
    app.unmount();
  });

  it("passes edited module fields to the existing save API", async () => {
    const update = vi.spyOn(adminApi, "updateDomain").mockResolvedValue({} as never);
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "模块").click();
    await flushUpdates();
    const form = root.querySelector<HTMLFormElement>(".domain-form-pane");
    if (!form) throw new Error("module form not found");
    const capabilities = form.querySelector<HTMLInputElement>(".raw-cap-input");
    const order = form.querySelector<HTMLInputElement>("input[type='number']");
    const enabled = form.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (!capabilities || !order || !enabled) throw new Error("module fields not found");
    buttonByText(form, "hoyo").click();
    await flushUpdates();
    for (const [input, value] of [[capabilities, "packages, archive"], [order, "7"]] as const) {
      input.value = value;
      input.dispatchEvent(new Event("input"));
      await flushUpdates();
    }
    enabled.checked = false;
    enabled.dispatchEvent(new Event("change"));
    await flushUpdates();
    await clickAndConfirm(root, "保存模块配置");
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

  it("opens the version editor without reporting phantom unsaved changes", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "版本").click();
    await flushUpdates();
    expect(root.querySelector(".sticky-save-bar")).not.toBeNull();
    expect(root.querySelector(".save-status-badge.dirty")).toBeNull();
    expect(root.textContent).toContain("没有未保存修改");
    // 表单自带校验提示，必须关闭浏览器原生校验，否则提交会被静默拦截
    expect(root.querySelector<HTMLFormElement>(".version-edit-form")!.noValidate).toBe(true);
    expect(buttonByText(root, "实时探活")).toBeTruthy();
    app.unmount();
  });

  it("cancels a pending new game entry and returns to the saved record", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "新增游戏").click();
    await flushUpdates();
    expect(root.textContent).toContain("创建新游戏入口");
    expect(root.textContent).toContain("立即创建游戏入口");
    buttonByText(root, "取消新建").click();
    await flushUpdates();
    expect(root.textContent).not.toContain("创建新游戏入口");
    expect(root.textContent).toContain("保存游戏设置");
    app.unmount();
  });

  it("exposes a PC artifact edit workspace without the APK-only create flow", async () => {
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

    await clickAndConfirm(root, "保存更改");

    expect(adminApi.updateEditableVersion).toHaveBeenCalled();
    const payload = vi.mocked(adminApi.updateEditableVersion).mock.calls[0][2];
    expect(payload.file_path).toBeUndefined();
    expect(payload.artifacts?.[0]).toMatchObject({
      artifact_id: "a1_pc_fixture",
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

  it("preserves artifact ownership through JSON and visual editing", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { app, root } = await mountAdmin("windows");
    try {
      buttonByText(root, "版本").click();
      await flushUpdates();
      buttonByText(root, "JSON").click();
      await flushUpdates();
      const editor = root.querySelector<HTMLTextAreaElement>(".pc-json-editor textarea");
      if (!editor) throw new Error("Artifact JSON editor not found");
      const artifacts = JSON.parse(editor.value);
      expect(artifacts[0].artifact_id).toBe("a1_pc_fixture");
      artifacts[0].name = "edited-in-json.zip";
      editor.value = JSON.stringify(artifacts);
      editor.dispatchEvent(new Event("input"));
      await flushUpdates();
      buttonByText(root, "列表").click();
      await flushUpdates();
      await clickAndConfirm(root, "保存更改");
      const payload = vi.mocked(adminApi.updateEditableVersion).mock.calls[0][2];
      expect(payload.artifacts?.[0]).toMatchObject({
        artifact_id: "a1_pc_fixture", name: "edited-in-json.zip",
      });
    } finally {
      app.unmount();
    }
  });

  it("keeps edit and create URL filename inference behavior aligned", async () => {
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
    await clickAndConfirm(root, "保存并探活");
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
    await clickAndConfirm(root, "保存并录入新版本");
    expect(addVersion).toHaveBeenCalledWith("demo-android", expect.objectContaining({
      artifacts: [expect.objectContaining({ kind: "apk", name: "new.apk", urls: [expect.objectContaining({ url: "https://example.com/new.apk" })] })],
    }), "test-admin-token", expect.anything());
    app.unmount();
  });

  it("renders one version form whose action bar follows the create tab", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "版本").click();
    await flushUpdates();
    expect(root.querySelectorAll(".version-edit-form").length).toBe(1);
    expect(root.querySelectorAll(".sticky-save-bar").length).toBe(1);
    expect(root.querySelectorAll(".form-actions-bar").length).toBe(0);
    expect(root.querySelector("input[placeholder^='例如: 7.1.0']")).toBeNull();

    buttonByText(root, "新建版本").click();
    await flushUpdates();
    expect(root.querySelectorAll(".version-edit-form").length).toBe(1);
    expect(root.querySelectorAll(".form-actions-bar").length).toBe(1);
    expect(root.querySelectorAll(".sticky-save-bar").length).toBe(0);
    expect(root.querySelector("input[placeholder^='例如: 7.1.0']")).not.toBeNull();

    buttonByText(root, "编辑版本").click();
    await flushUpdates();
    expect(root.querySelectorAll(".sticky-save-bar").length).toBe(1);
    expect(root.querySelectorAll(".form-actions-bar").length).toBe(0);
    app.unmount();
  });

  it("renders rail navigation with vector icons instead of emoji", async () => {
    const { app, root } = await mountAdmin("android");
    const rail = root.querySelector(".admin-rail");
    expect(rail).not.toBeNull();
    expect(rail!.querySelectorAll(".admin-icon").length).toBe(5);
    expect(rail!.querySelectorAll(".rail-icon").length).toBe(0);
    expect(rail!.textContent).not.toMatch(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
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

  it("shows built-in probe scheduler status while keeping daily collection external", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "监控").click();
    await flushUpdates();
    expect(root.textContent).toContain("这里只保存每日采集计划参数");
    expect(root.textContent).toContain("时区、漏跑策略及采集动作由外部计划任务决定");
    expect(root.textContent).toContain("内置探活计时器：运行中");
    expect(root.textContent).toContain("下次任务计划：");
    expect(root.textContent).toContain("最近任务启动：");
    expect(root.textContent).toContain("内置计时器先从官方来源采集新 URL");
    expect(root.textContent).toContain("Android+PC 新发现或上次探活可用的官方与历史 URL");
    expect(root.textContent).toContain("仅发送新版本更新");
    expect(root.textContent).toContain("启动新的间隔周期");
    expect(root.textContent).not.toContain("北京时间");
    expect(adminApi.probeScheduler).toHaveBeenCalled();
    app.unmount();
  });

  it("checks official updates before a batch probe selected in the console", async () => {
    vi.spyOn(adminApi, "latestOperation").mockRejectedValue(new Error("no previous operation"));
    const start = vi.spyOn(adminApi, "startOperation").mockResolvedValue(operationJob({
      status: "running", phase: "discover", actions: ["discover", "probe"],
      result: null, finished_at: null,
    }) as never);
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "监控").click();
    await flushUpdates();
    expect(root.querySelectorAll(".op-action-card").length).toBe(2);
    const batchOption = root.querySelector<HTMLInputElement>('input[type="radio"][value="both"]');
    expect(batchOption).not.toBeNull();
    batchOption!.click();
    await flushUpdates();
    await clickAndConfirm(root, "启动运维任务");
    expect(start).toHaveBeenCalledWith(expect.objectContaining({
      actions: ["discover", "probe"], scope: "all", all_games: true,
    }), "test-admin-token", expect.any(AbortSignal));
    expect(root.textContent).toContain("仅发送新版本更新");
    app.unmount();
  });

  it("refreshes built-in scheduler status after saving probe schedule", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "监控").click();
    await flushUpdates();
    const scheduler = vi.mocked(adminApi.probeScheduler);
    const callsBeforeSave = scheduler.mock.calls.length;
    await clickAndConfirm(root, "保存定时探活计划");
    expect(scheduler.mock.calls.length).toBeGreaterThan(callsBeforeSave);
    app.unmount();
  });

  it("does not retain a running scheduler claim when status refresh fails", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "监控").click();
    await flushUpdates();
    expect(root.textContent).toContain("内置探活计时器：运行中");
    vi.mocked(adminApi.probeScheduler).mockRejectedValueOnce(new Error("status unavailable"));
    await clickAndConfirm(root, "保存定时探活计划");
    expect(root.textContent).toContain("内置探活计时器：状态未知");
    expect(root.textContent).not.toContain("内置探活计时器：运行中");
    app.unmount();
  });

  it("keeps unknown probe rows separate from failures and explains their results", async () => {
    const items = [
      { game_id: "demo", version: "403", ok: true, available: null, adapter: "demo", error: null, reason: "HTTP 403" },
      { game_id: "demo", version: "200", ok: true, available: null, adapter: "demo", error: null, reason: "HTTP 200" },
      { game_id: "demo", version: "archive", ok: true, available: false, adapter: "demo", error: null, reason: "oss_archive_not_restored" },
      { game_id: "demo", version: "error", ok: false, available: null, adapter: "demo", error: "ProbeError", reason: "probe_failed" },
    ];
    vi.spyOn(adminApi, "operationStatus").mockResolvedValue(operationJob({
      result: { actions: ["probe"], game_ids: ["demo"], scope: "all", probe: {
        checked: 4, available: 0, unavailable: 1, unknown: 2, failed: 1, items,
      } },
    }) as never);
    sessionStorage.setItem("game-manifest-index-web-operation-job-v1", "probe-job-1");
    const { app, root } = await mountAdmin("windows");
    try {
      buttonByText(root, "监控").click();
      await flushUpdates();
      buttonByText(root, "? 未知 (2)").click();
      await flushUpdates();
      const table = root.querySelector(".op-table-section");
      expect(table?.querySelectorAll("tbody tr")).toHaveLength(2);
      expect(table?.textContent).toContain("仅显示未知: 2 条");
      expect(table?.textContent).toContain("上游拒绝访问（HTTP 403）");
      expect(table?.textContent).toContain("已响应，但未取得有效文件证据（HTTP 200）");
      expect(table?.textContent).not.toContain("正常");
      expect(table?.textContent).not.toContain("ProbeError");
      buttonByText(root, "✕ 失效 (1)").click();
      await flushUpdates();
      expect(table?.textContent).toContain("对象已归档，尚未恢复下载");
      buttonByText(root, "⚠ 异常 (1)").click();
      await flushUpdates();
      expect(table?.querySelectorAll("tbody tr")).toHaveLength(1);
      expect(table?.textContent).toContain("ProbeError");
    } finally {
      app.unmount();
    }
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

  it("resumes compacted logs with the absolute cursor and keeps a bounded terminal", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    let app: ReturnType<typeof createApp> | undefined;
    try {
      const mounted = await mountResumedOperation(() => {
        calls += 1;
        return operationJob({
          status: "running", phase: "probe", finished_at: null,
          result: null,
          log_offset: calls === 1 ? 744 : 1000,
          log_total: calls === 1 ? 1000 : 1010,
          logs: Array.from({ length: calls === 1 ? 256 : 10 }, (_, index) => `audit-log-${(calls === 1 ? 744 : 1000) + index}`),
        });
      });
      app = mounted.app;
      expect(vi.mocked(adminApi.operationStatus).mock.calls[1]?.[3]).toBe(1000);
      buttonByText(mounted.root, "监控").click();
      await flushUpdates();
      expect(mounted.root.querySelectorAll(".terminal-row").length).toBeLessThanOrEqual(256);
      expect(mounted.root.textContent).toContain("audit-log-1009");
      expect(mounted.root.textContent).not.toContain("audit-log-744");
    } finally {
      app?.unmount();
      vi.useRealTimers();
    }
  });

  it("explains when probe details are bounded while keeping the complete totals", async () => {
    vi.spyOn(adminApi, "operationStatus").mockResolvedValue(operationJob({
      result: { actions: ["probe"], game_ids: ["demo"], probe: {
        checked: 5000, available: 5000, unavailable: 0, unknown: 0, failed: 0,
        items_truncated: true, items_total: 5000, items_omitted: 4999,
        items: [{ game_id: "demo", version: "1.0.0", ok: true, available: true }],
      } },
    }) as never);
    sessionStorage.setItem("game-manifest-index-web-operation-job-v1", "probe-job-1");
    const { app, root } = await mountAdmin("windows");
    try {
      buttonByText(root, "监控").click();
      await flushUpdates();
      expect(root.textContent).toContain("本次探活共 5000 条结果，下方保留 1 条明细");
      expect(root.textContent).toContain("上方统计包含全部结果");
      expect(buttonByText(root, "✓ 可用 (5000)")).toBeTruthy();
    } finally {
      app.unmount();
    }
  });

  it("sends a fresh availability invalidation after every successful direct version probe", async () => {
    const events: CustomEvent[] = [];
    const listener = (event: Event): void => { events.push(event as CustomEvent); };
    window.addEventListener("gmi-availability-invalidated", listener);
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "版本").click();
    await flushUpdates();

    await clickAndConfirm(root, "实时探活");
    await clickAndConfirm(root, "实时探活");

    expect(events).toHaveLength(2);
    expect(events[0].detail.jobId).not.toBe(events[1].detail.jobId);
    app.unmount();
    window.removeEventListener("gmi-availability-invalidated", listener);
  });

  it("does not report failed save-and-probe as a completed probe", async () => {
    const { app, root } = await mountAdmin("android");
    buttonByText(root, "版本").click();
    await flushUpdates();
    const url = root.querySelector<HTMLInputElement>(".apk-file-card input.url-long-input")!;
    url.value = "https://example.com/updated.apk";
    url.dispatchEvent(new Event("input"));
    await flushUpdates();
    vi.mocked(adminApi.probeVersion).mockRejectedValueOnce(new Error("network failed"));
    await clickAndConfirm(root, "保存并探活");
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
