export async function copyTextToClipboard(text?: string): Promise<boolean> {
  if (!text) return false;

  const writeText = navigator.clipboard?.writeText?.bind(navigator.clipboard);
  if (writeText) {
    try {
      await writeText(text);
      return true;
    } catch {
      // Fall through to the legacy path for insecure HTTP pages or denied writes.
    }
  }

  try {
    return fallbackCopyText(text);
  } catch {
    return false;
  }
}

function fallbackCopyText(text: string): boolean {
  if (!document.body || typeof document.execCommand !== "function") return false;

  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const selection = document.getSelection();
  const ranges: Range[] = [];
  if (selection) {
    for (let index = 0; index < selection.rangeCount; index += 1) {
      ranges.push(selection.getRangeAt(index).cloneRange());
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.readOnly = true;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);

  try {
    textarea.focus();
    textarea.select();
    return document.execCommand("copy");
  } finally {
    textarea.remove();
    try {
      if (selection) {
        selection.removeAllRanges();
        ranges.forEach((range) => selection.addRange(range));
      }
    } catch {
      // Selection restoration is best-effort only.
    }
    try {
      activeElement?.focus();
    } catch {
      // Focus restoration is best-effort only.
    }
  }
}
