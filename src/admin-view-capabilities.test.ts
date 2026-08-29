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

function mockAdminApi(platform: "android" | "windows") {
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
    items: [{ version: "1.0.0", is_visible: true }],
  } as never);
  vi.spyOn(adminApi, "editableVersion").mockRejectedValue(new Error("APK editor must stay gated"));
  vi.spyOn(adminApi, "probeStatus").mockResolvedValue({ running: false, log: [] } as never);
  vi.spyOn(adminApi, "probeSchedule").mockResolvedValue({ enabled: false, interval_hours: 24, mode: "normal" });
  vi.spyOn(adminApi, "syncSchedule").mockResolvedValue({ enabled: false, times: ["04:45", "14:00"] });
}

async function mountAdmin(platform: "android" | "windows") {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
  });
  mockAdminApi(platform);
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

  it("renders the catalog as read-only and disables unavailable retention", async () => {
    const { app, root } = await mountAdmin("android");
    expect(root.textContent).toContain("游戏目录由当前 V5 静态注册关系和数据投影生成");
    expect(root.textContent).not.toContain("新增游戏");
    expect(root.textContent).not.toContain("保存游戏设置");
    expect(root.textContent).not.toContain("删除空游戏");
    expect(buttonByText(root, "未接入").disabled).toBe(true);
    app.unmount();
  });

  it("does not expose the APK-only add/edit workspace for PC domains", async () => {
    const { app, root } = await mountAdmin("windows");
    buttonByText(root, "版本").click();
    await flushUpdates();
    expect(root.textContent).toContain("PC 版本只读");
    expect(root.textContent).toContain("当前单 APK 表单不适用于 PC 资源");
    expect(root.textContent).not.toContain("新建版本");
    expect(root.textContent).not.toContain("APK 文件");
    expect(adminApi.editableVersion).not.toHaveBeenCalled();
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
