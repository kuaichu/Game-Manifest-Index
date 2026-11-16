// @vitest-environment jsdom
import { type App, createApp, h, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import ArchiveGameSidebar from "./components/archive/ArchiveGameSidebar.vue";
import type { Game } from "./types";

const games = [
  { id: "hsr", name: "崩坏：星穹铁道", sub_name: "Star Rail", publisher: "miHoYo" },
  { id: "wuwa", name: "鸣潮", sub_name: "Wuthering Waves", publisher: "Kuro" },
] as unknown as Game[];

let app: App | null = null;
let root: HTMLElement | null = null;
afterEach(() => {
  app?.unmount();
  app = null;
  root?.remove();
  root = null;
  document.body.innerHTML = "";
});

async function mount(selected: string[]) {
  root = document.createElement("div");
  document.body.append(root);
  app = createApp({ render: () => h(ArchiveGameSidebar, { games, gameId: "hsr", onSelectGame: (id: string) => selected.push(id) }) });
  app.mount(root);
  await nextTick();
  return root;
}

describe("ArchiveGameSidebar mobile drawer", () => {
  it("shows the current game and picks another one from the searchable drawer", async () => {
    const selected: string[] = [];
    const el = await mount(selected);
    const trigger = el.querySelector<HTMLButtonElement>(".mobile-game-trigger")!;
    expect(trigger.textContent).toContain("崩坏：星穹铁道");

    trigger.click();
    await nextTick();
    const input = document.querySelector<HTMLInputElement>(".mobile-drawer-search input")!;
    input.value = "wuthering";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    const options = [...document.querySelectorAll<HTMLButtonElement>(".mobile-drawer-game")];
    expect(options.map((item) => item.textContent)).toEqual([expect.stringContaining("鸣潮")]);

    options[0].click();
    await nextTick();
    expect(selected).toEqual(["wuwa"]);
    expect(document.querySelector(".mobile-game-drawer")).toBeNull();
  });

  it("keeps the desktop game list inside the sidebar while teleporting the mobile drawer", async () => {
    const el = await mount([]);
    expect(el.querySelector(".game-sidebar .sidebar-games-scroll")).not.toBeNull();
    el.querySelector<HTMLButtonElement>(".mobile-game-trigger")!.click();
    await nextTick();
    expect(el.querySelector(".mobile-game-drawer")).toBeNull();
    expect(document.body.querySelector(".mobile-game-drawer")).not.toBeNull();
  });

  it("closes on Escape", async () => {
    const el = await mount([]);
    el.querySelector<HTMLButtonElement>(".mobile-game-trigger")!.click();
    await nextTick();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await nextTick();
    expect(document.querySelector(".mobile-game-drawer")).toBeNull();
  });
});
