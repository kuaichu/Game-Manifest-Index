import { onBeforeUnmount, watch } from "vue";

interface SavedProperty {
  name: string;
  value: string;
  priority: string;
}

const overflowProperties = ["overflow", "overflow-x", "overflow-y"];
const holders = new Set<symbol>();
let restoreStyles: (() => void) | null = null;

function preserveProperties(style: CSSStyleDeclaration, names: string[]): () => void {
  const saved: SavedProperty[] = [];
  for (let index = 0; index < style.length; index += 1) {
    const name = style.item(index);
    if (names.includes(name)) {
      saved.push({ name, value: style.getPropertyValue(name), priority: style.getPropertyPriority(name) });
    }
  }
  return () => {
    names.forEach((name) => style.removeProperty(name));
    saved.forEach(({ name, value, priority }) => style.setProperty(name, value, priority));
  };
}

/** Keep the page locked until the last open modal closes, without changing its scroll position. */
export function useModalScrollLock(enabled: () => boolean): void {
  const token = Symbol("modal-scroll-lock");

  function release(): void {
    if (!holders.delete(token) || holders.size > 0) return;
    restoreStyles?.();
    restoreStyles = null;
  }

  watch(enabled, (isOpen) => {
    if (!isOpen) {
      release();
      return;
    }
    if (holders.has(token) || typeof document === "undefined") return;
    if (holders.size === 0) {
      const root = document.documentElement;
      const body = document.body;
      const restoreRoot = preserveProperties(root.style, [...overflowProperties, "scrollbar-gutter"]);
      const restoreBody = preserveProperties(body.style, overflowProperties);
      restoreStyles = () => {
        restoreRoot();
        restoreBody();
      };
      if (!getComputedStyle(root).getPropertyValue("scrollbar-gutter").includes("stable")) {
        root.style.setProperty("scrollbar-gutter", "stable");
      }
      overflowProperties.forEach((name) => {
        root.style.removeProperty(name);
        body.style.removeProperty(name);
      });
      root.style.setProperty("overflow", "hidden", "important");
      body.style.setProperty("overflow", "hidden", "important");
    }
    holders.add(token);
  }, { immediate: true, flush: "sync" });

  onBeforeUnmount(release);
}
