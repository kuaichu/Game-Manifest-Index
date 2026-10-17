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
