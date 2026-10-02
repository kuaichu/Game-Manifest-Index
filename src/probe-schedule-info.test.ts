import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import ProbeScheduleInfo from "./components/ProbeScheduleInfo.vue";
import type { PublicProbeScheduleStatus } from "./types";

const status: PublicProbeScheduleStatus = {
  running: true, enabled: true, interval_hours: 1, mode: "normal", error: null,
  last_started_at: "2026-10-02T16:32:03Z", next_run_at: "2026-10-02T17:32:03Z",
  evidence_ttl_hours: 20,
};
let unmount: (() => void) | null = null;
afterEach(() => {
  unmount?.(); unmount = null;
  document.body.innerHTML = "";
  vi.restoreAllMocks(); vi.useRealTimers();
});
async function mount(globalTime = true) {
  const root = document.createElement("div"); document.body.append(root);
  const refresh = vi.fn();
  const app = createApp(ProbeScheduleInfo, { checkedTime: "22:32 (3 小时前)", globalTime, onRefresh: refresh });
  app.mount(root); unmount = () => app.unmount();
  await Promise.resolve(); await nextTick();
  return { root, refresh };
}
describe("probe schedule explanation", () => {
  it("separates hourly task starts from old global URL evidence", async () => {
    vi.spyOn(api, "probeScheduleStatus").mockResolvedValue(status);
    const { root } = await mount();
    expect(root.textContent).toContain("每 1 小时检查新版本");
    expect(root.textContent).toContain("最近任务启动：2026.10.03 00:32");
    expect(root.textContent).toContain("下次计划：2026.10.03 01:32");
    expect(root.textContent).toContain("全站链接最近实际检测：22:32 (3 小时前)");
    expect(root.textContent).toContain("跳过 20 小时");
    const help = root.querySelector("details")!;
    expect(help.open).toBe(false);
    expect(root.querySelector("summary")?.textContent).toBe("为什么链接检测时间没有变化？");
    help.open = true;
    expect(help.querySelector("p")?.textContent).toContain("跳过 20 小时");
    expect(root.textContent).not.toContain("当前资源最近探活");
  });
  it("shows disabled, stopped and failed scheduling without claiming success", async () => {
    const mock = vi.spyOn(api, "probeScheduleStatus");
    mock.mockResolvedValue({ ...status, enabled: false, next_run_at: null });
    let view = await mount(false);
    expect(view.root.textContent).toContain("定时检查未开启");
    expect(view.root.textContent).not.toContain("下次计划");
    expect(view.root.textContent).toContain("当前页面链接最近实际检测");
    unmount?.();
    mock.mockResolvedValue({ ...status, running: false });
    view = await mount(); expect(view.root.textContent).toContain("定时检查未运行");
    unmount?.();
    mock.mockResolvedValue({ ...status, error: "scheduler_state_invalid" });
    view = await mount(); expect(view.root.textContent).toContain("定时检查异常");
  });
  it("handles an older/unavailable API without hiding URL evidence", async () => {
    vi.spyOn(api, "probeScheduleStatus").mockRejectedValue(new Error("not found"));
    const { root } = await mount();
    expect(root.textContent).toContain("定时检查状态暂不可用");
    expect(root.textContent).toContain("链接检测时间记录实际检测");
    expect(root.textContent).toContain("3 小时前");
    expect(root.textContent).not.toContain("每 1 小时");
  });
  it("refreshes status and evidence each minute and stops on unmount", async () => {
    vi.useFakeTimers();
    const mock = vi.spyOn(api, "probeScheduleStatus").mockResolvedValue(status);
    const { refresh } = await mount();
    await vi.advanceTimersByTimeAsync(60000);
    expect(mock).toHaveBeenCalledTimes(2); expect(refresh).toHaveBeenCalledTimes(2);
    const signal = mock.mock.calls[1][0]!;
    unmount?.(); unmount = null;
    expect(signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60000);
    expect(mock).toHaveBeenCalledTimes(2);
  });
  it("does not display the normal-mode TTL for full mode", async () => {
    vi.spyOn(api, "probeScheduleStatus").mockResolvedValue({ ...status, mode: "full" });
    const { root } = await mount();
    expect(root.textContent).toContain("每轮复查已验证可用的链接");
    expect(root.textContent).not.toContain("跳过 20 小时");
  });
});
