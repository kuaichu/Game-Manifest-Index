import { createApp, h, nextTick, ref } from "vue";
import { expect, it } from "vitest";
import SourceProvenanceModal from "./components/SourceProvenanceModal.vue";

it("locks a provenance modal mounted open and releases the page on close", async () => {
  const open = ref(true);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp({
    render: () => h(SourceProvenanceModal, { open: open.value, onClose: () => { open.value = false; } }),
  });
  app.mount(host);
  try {
    expect(document.body.querySelector(".provenance-modal-dialog")).not.toBeNull();
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(document.body.style.overflow).toBe("hidden");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await nextTick();
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  } finally {
    app.unmount();
    host.remove();
  }
});

it("keeps current PC collection links separate from historical import sources", () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp(SourceProvenanceModal, { open: true });
  app.mount(host);
  try {
    const modal = Array.from(document.body.querySelectorAll(".provenance-modal-dialog")).at(-1)!;
    const cards = Array.from(modal.querySelectorAll(".game-provenance-card"));
    for (const id of ["hk4e", "hkrpg", "nap", "bh3", "wuwa"]) {
      const card = cards.find((item) => item.querySelector(".game-id-tag")?.textContent === id)!;
      const currentLink = card.querySelector<HTMLAnchorElement>(".upstream-link-badge")!;
      const expectedHost = id === "wuwa" ? "prod-cn-alicdn-gamestarter.kurogame.com" : "hyp-api.mihoyo.com";
      expect(new URL(currentLink.href).hostname).toBe(expectedHost);
      const history = Array.from(card.querySelectorAll(".provenance-row"))
        .find((row) => row.querySelector(".row-label")?.textContent?.includes("历史来源"));
      expect(history).toBeDefined();
      expect(history!.contains(currentLink)).toBe(false);
    }
  } finally {
    app.unmount();
    host.remove();
  }
});

it("includes archived games and filters vendors without inventing an Android source for PC-only archives", async () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp(SourceProvenanceModal, { open: true });
  app.mount(host);
  try {
    const modal = Array.from(document.body.querySelectorAll(".provenance-modal-dialog")).at(-1)!;
    const ids = () => Array.from(modal.querySelectorAll(".game-id-tag"), (item) => item.textContent);
    expect(ids().sort()).toEqual([
      "abc", "arknights", "azurpromilia", "bh2", "bh3", "endfield", "hk4e",
      "hkrpg", "nap", "nte", "p5x", "pns", "tof", "wuwa",
    ]);
    for (const tab of Array.from(modal.querySelectorAll<HTMLButtonElement>(".filter-tab"))) {
      tab.click();
      await nextTick();
      const count = Number(tab.textContent!.match(/\((\d+)\)/)![1]);
      expect(ids()).toHaveLength(count);
    }
    expect(ids()).toEqual(["azurpromilia"]);
    modal.querySelector<HTMLButtonElement>(".filter-tab")!.click();
    await nextTick();
    const search = modal.querySelector<HTMLInputElement>('input[type="search"]')!;
    search.value = "abc";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    await nextTick();
    expect(ids()).toEqual(["abc"]);
    const labels = Array.from(modal.querySelectorAll(".row-label"), (row) => row.textContent);
    expect(labels.some((label) => label?.includes("Android"))).toBe(false);
    expect(labels.some((label) => label?.includes("PC"))).toBe(true);
  } finally {
    app.unmount();
    host.remove();
  }
});
