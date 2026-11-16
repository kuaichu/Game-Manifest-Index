// @vitest-environment jsdom
import { createApp, h, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import ArchiveControlStrip from "./components/archive/ArchiveControlStrip.vue";
import type { ArchiveDomain } from "./types";

const domain = { id: "hsr-pc", game_id: "hsr", kind: "client", platform: "pc", adapter: "hoyo", capabilities: ["packages", "files", "compare"] } as unknown as ArchiveDomain;
const modes = ["packages", "files", "compare"].map((capability) => ({ domain, capability }));

function pointer(type: string, x: number, y = 10): Event {
  const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 });
  Object.defineProperty(event, "pointerId", { value: 1 });
  return event;
}

let root: HTMLElement | null = null;
afterEach(() => { root?.remove(); root = null; });

async function mount(searchableMode: boolean, selected: string[] = []) {
  root = document.createElement("div");
  document.body.append(root);
  const app = createApp({
    render: () => h(ArchiveControlStrip, {
      versions: [], selectedVersion: "", domain, domainId: domain.id, mode: "packages", visibleModes: modes,
      controlStripDensity: "modes-few", searchableMode, query: "", suppressAvailabilityPresentation: false,
      onSelectMode: (_: ArchiveDomain, capability: string) => selected.push(capability),
    }),
  });
  app.mount(root);
  await nextTick();
  return root;
}

describe("ArchiveControlStrip", () => {
  it("keeps a placeholder where the search box was so the tabs do not shift", async () => {
    const el = await mount(false);
    expect(el.querySelector("input")).toBeNull();
    expect(el.querySelector(".search-box-spacer")).not.toBeNull();
  });

  it("switches mode when the active tab is dragged onto another tab", async () => {
    const selected: string[] = [];
    const el = await mount(true, selected);
    const tabs = [...el.querySelectorAll<HTMLElement>(".mode-tab")];
    tabs.forEach((tab, index) => {
      tab.getBoundingClientRect = () => ({ left: index * 100, right: index * 100 + 90, top: 0, bottom: 34, width: 90, height: 34, x: index * 100, y: 0, toJSON: () => ({}) });
    });
    expect(el.querySelector(".mode-tab-indicator")).not.toBeNull();

    tabs[0].dispatchEvent(pointer("pointerdown", 40));
    tabs[0].dispatchEvent(pointer("pointermove", 150));
    await nextTick();
    expect(tabs[1].classList.contains("drop-target")).toBe(true);
    tabs[0].dispatchEvent(pointer("pointerup", 150));
    tabs[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(selected).toEqual(["files"]);
  });

  it("still treats a press without movement as a normal click", async () => {
    const selected: string[] = [];
    const el = await mount(true, selected);
    const tabs = [...el.querySelectorAll<HTMLElement>(".mode-tab")];
    tabs[2].click();
    expect(selected).toEqual(["compare"]);
  });
});
