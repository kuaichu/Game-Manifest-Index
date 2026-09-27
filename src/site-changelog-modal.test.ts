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
    expect(dialog?.textContent).toContain("原神更新至 6.7.0 版本");
    expect(dialog?.textContent).toContain("原神的 5.5.0 版本不可用了");
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
});
