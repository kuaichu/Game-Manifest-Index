import { createApp, h, ref, type App } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import { useModalScrollLock } from "./useModalScrollLock";

const apps: App[] = [];

function mountLock(initiallyOpen = false) {
  const open = ref(initiallyOpen);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const app = createApp({
    setup() {
      useModalScrollLock(() => open.value);
      return () => h("div");
    },
  });
  apps.push(app);
  app.mount(host);
  return {
    open,
    unmount() {
      app.unmount();
      apps.splice(apps.indexOf(app), 1);
    },
  };
}

function expectLocked() {
  expect(document.documentElement.style.overflow).toBe("hidden");
  expect(document.body.style.overflow).toBe("hidden");
}

afterEach(() => {
  apps.splice(0).forEach((app) => app.unmount());
  document.documentElement.removeAttribute("style");
  document.body.removeAttribute("style");
  document.body.innerHTML = "";
});

describe("modal page scroll lock", () => {
  it("locks html and body immediately when mounted open and keeps scroll offsets", () => {
    document.documentElement.scrollTop = 320;
    document.body.scrollTop = 80;
    const modal = mountLock(true);
    expectLocked();
    expect(document.documentElement.style.getPropertyValue("scrollbar-gutter")).toBe("stable");
    expect(document.documentElement.scrollTop).toBe(320);
    expect(document.body.scrollTop).toBe(80);
    modal.open.value = false;
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
    expect(document.documentElement.scrollTop).toBe(320);
    expect(document.body.scrollTop).toBe(80);
  });

  it("restores existing overflow declarations, priorities and gutter without changing unrelated styles", () => {
    const root = document.documentElement.style;
    root.setProperty("overflow-x", "clip", "important");
    root.setProperty("overflow-y", "scroll");
    root.setProperty("scrollbar-gutter", "auto", "important");
    document.body.style.setProperty("overflow", "auto", "important");
    document.body.style.color = "red";
    const modal = mountLock(true);
    expectLocked();
    document.body.style.color = "blue";
    modal.unmount();
    expect(root.getPropertyValue("overflow-x")).toBe("clip");
    expect(root.getPropertyPriority("overflow-x")).toBe("important");
    expect(root.getPropertyValue("overflow-y")).toBe("scroll");
    expect(root.getPropertyPriority("overflow-y")).toBe("");
    expect(root.getPropertyValue("scrollbar-gutter")).toBe("auto");
    expect(root.getPropertyPriority("scrollbar-gutter")).toBe("important");
    expect(document.body.style.overflow).toBe("auto");
    expect(document.body.style.getPropertyPriority("overflow")).toBe("important");
    expect(document.body.style.color).toBe("blue");
  });

  it("keeps an existing stable both-edges gutter while locked", () => {
    document.documentElement.style.setProperty("scrollbar-gutter", "stable both-edges", "important");
    mountLock(true);
    expect(document.documentElement.style.getPropertyValue("scrollbar-gutter")).toBe("stable both-edges");
    expect(document.documentElement.style.getPropertyPriority("scrollbar-gutter")).toBe("important");
  });

  it("waits for the last modal after interleaved closing, reopening and unmounting", () => {
    document.body.style.overflow = "auto";
    const first = mountLock(true);
    const second = mountLock(true);
    first.open.value = false;
    expectLocked();
    first.open.value = true;
    second.unmount();
    expectLocked();
    first.open.value = false;
    expect(document.body.style.overflow).toBe("auto");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.documentElement.style.getPropertyValue("scrollbar-gutter")).toBe("");
  });

  it("never releases another modal's lock when a closed instance unmounts", () => {
    const first = mountLock(true);
    const closed = mountLock();
    closed.unmount();
    expectLocked();
    first.unmount();
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.body.style.overflow).toBe("");
  });

  it("captures fresh styles for each new locking session", () => {
    const modal = mountLock(true);
    modal.open.value = false;
    document.documentElement.style.overflowY = "scroll";
    modal.open.value = true;
    expectLocked();
    modal.open.value = false;
    expect(document.documentElement.style.overflowY).toBe("scroll");
  });
});
