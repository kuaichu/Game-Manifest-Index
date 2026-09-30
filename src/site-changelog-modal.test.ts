import { createApp, h, nextTick, ref } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import SiteChangelogModal from "./components/SiteChangelogModal.vue";
import type { GameActivityEvent } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  document.body.style.overflow = "";
});

describe("site changelog", () => {
  it("separates project updates from verified game events and closes with Escape", async () => {
    const open = ref(false);
    const events: GameActivityEvent[] = [
      { id: 2, game_id: "hk4e", domain_id: "hk4e-android", platform: "android", version: "6.7.0", type: "version_update", occurred_at: "2026-09-28T08:00:00Z" },
      { id: 1, game_id: "hk4e", domain_id: "hk4e-android", platform: "android", version: "5.5.0", type: "version_unavailable", occurred_at: "2026-09-27T08:00:00Z" },
    ];
    vi.spyOn(api, "activity").mockResolvedValue({ items: events });
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({
      setup: () => () => h(SiteChangelogModal, {
        open: open.value,
        initialTab: "system",
        originPos: { x: 80, y: 40 },
        gameNames: { hk4e: "原神" },
        onClose: () => { open.value = false; },
      }),
    });
    app.mount(root);
    open.value = true;
    await nextTick();

    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("PROJECT & GAME UPDATES");
    expect(dialog?.textContent).toContain("2026.09.27");
    expect(dialog?.textContent).not.toContain("原神更新至");
    expect(dialog?.querySelector(".changelog-timeline .changelog-entry")).not.toBeNull();

    (document.getElementById("changelog-data-tab") as HTMLButtonElement).click();
    await Promise.resolve();
    await nextTick();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await nextTick();
    const rows = dialog?.querySelectorAll(".changelog-event");
    expect(rows?.[0].getAttribute("aria-label")).toContain("原神更新至 6.7.0 版本");
    expect(rows?.[1].getAttribute("aria-label")).toContain("原神的 5.5.0 版本不可用了");
    expect(rows?.[1].querySelector(".is-unavailable")?.textContent).toBe("探活确认不可用");
    expect(dialog?.textContent).not.toContain("崩坏：因缘精灵");

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await nextTick();
    expect(open.value).toBe(false);
    app.unmount();
  });

  it("shows an honest idle state and animates the refresh control", async () => {
    const activityRequest = vi.spyOn(api, "activity").mockResolvedValue({ items: [] });
    const open = ref(false);
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({
      setup: () => () => h(SiteChangelogModal, {
        open: open.value,
        initialTab: "data",
        gameNames: {},
        onClose: () => { open.value = false; },
      }),
    });
    app.mount(root);
    open.value = true;
    await nextTick();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await nextTick();

    const idle = document.querySelector(".changelog-empty-idle");
    expect(document.querySelector(".changelog-data-head")?.textContent).toContain("全站最近动态");
    expect(idle?.textContent).toContain("STATUS: AWAITING_NEW_EVENTS");
    expect(idle?.textContent).toContain("暂无数据动态。");
    expect(idle?.textContent).not.toContain("从现在起");
    expect(idle?.querySelector("svg")).not.toBeNull();
    const refresh = document.querySelector(".changelog-data-head button") as HTMLButtonElement;
    expect(refresh.querySelector("svg")).not.toBeNull();
    refresh.click();
    await nextTick();
    await nextTick();
    expect(refresh.classList.contains("is-refreshing")).toBe(true);
    expect(activityRequest).toHaveBeenCalledTimes(2);
    app.unmount();
  });

  it("groups local calendar dates while preserving both platform events and full timestamps", async () => {
    const events: GameActivityEvent[] = [
      { id: 4, game_id: "wuwa", domain_id: "wuwa-pc", platform: "windows", version: "3.7.0", type: "version_update", occurred_at: "2026-09-30T04:28:46Z" },
      { id: 3, game_id: "wuwa", domain_id: "wuwa-android", platform: "android", version: "3.7.0", type: "version_update", occurred_at: "2026-09-30T04:28:46Z" },
      { id: 2, game_id: "other", domain_id: "other-pc", platform: "windows", version: "1.0", type: "version_unavailable", occurred_at: "2026-09-28T06:26:39Z" },
    ];
    vi.spyOn(api, "activity").mockResolvedValue({ items: events });
    const open = ref(false);
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({ setup: () => () => h(SiteChangelogModal, {
      open: open.value, initialTab: "data", gameNames: { wuwa: "鸣潮" },
    }) });
    app.mount(root);
    open.value = true;
    await nextTick();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await nextTick();

    const days = document.querySelectorAll(".changelog-day");
    expect(days).toHaveLength(2);
    expect(days[0].querySelectorAll(".changelog-event")).toHaveLength(2);
    expect(days[0].querySelector(".changelog-day-count")?.textContent).toBe("2 条动态");
    expect([...days[0].querySelectorAll(".changelog-platform")].map((node) => node.textContent)).toEqual(["PC", "Android"]);
    expect([...days[0].querySelectorAll(".changelog-version")].map((node) => node.textContent)).toEqual(["3.7.0", "3.7.0"]);
    const time = days[0].querySelector(".changelog-event-time");
    expect(time?.getAttribute("datetime")).toBe(events[0].occurred_at);
    expect(time?.getAttribute("title")).toContain("46");
    expect(document.querySelector(".changelog-count")?.textContent).toBe("3 条");
    expect(days[1].querySelector(".changelog-game-icon")?.textContent).toBe("o");
    const image = days[0].querySelector(".changelog-game-icon img")!;
    image.dispatchEvent(new Event("error"));
    await nextTick();
    expect(days[0].querySelectorAll(".changelog-game-icon img")).toHaveLength(0);
    expect(days[0].querySelector(".changelog-game-icon")?.textContent).toBe("鸣");
    app.unmount();
  });

  it("keeps the current list visible during refresh and prevents duplicate requests", async () => {
    const event: GameActivityEvent = { id: 1, game_id: "hk4e", domain_id: "hk4e-android", platform: "android", version: "7.1.0", type: "version_update", occurred_at: "2026-09-30T04:00:00Z" };
    let finishRefresh!: (value: { items: GameActivityEvent[] }) => void;
    const request = vi.spyOn(api, "activity").mockResolvedValueOnce({ items: [event] })
      .mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
    const open = ref(false);
    const root = document.createElement("div");
    document.body.appendChild(root);
    const app = createApp({ setup: () => () => h(SiteChangelogModal, {
      open: open.value, initialTab: "data", gameNames: { hk4e: "原神" },
    }) });
    app.mount(root);
    open.value = true;
    await nextTick();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await nextTick();
    const button = document.querySelector<HTMLButtonElement>(".changelog-data-head button")!;
    button.click();
    await nextTick();
    expect(button.disabled).toBe(true);
    expect(document.querySelector(".changelog-event-title")?.textContent).toContain("原神");
    expect(document.querySelector(".changelog-activity-days")?.getAttribute("aria-busy")).toBe("true");
    button.click();
    expect(request).toHaveBeenCalledTimes(2);
    finishRefresh({ items: [event] });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await nextTick();
    expect(button.disabled).toBe(false);
    app.unmount();
  });
});
