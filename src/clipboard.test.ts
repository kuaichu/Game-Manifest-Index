import { afterEach, describe, expect, it, vi } from "vitest";

import { copyTextToClipboard } from "./clipboard";

const originalClipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const originalExecCommandDescriptor = Object.getOwnPropertyDescriptor(document, "execCommand");

function stubClipboard(value: Clipboard | undefined): void {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value });
}

function stubExecCommand(value: Document["execCommand"]): void {
  Object.defineProperty(document, "execCommand", { configurable: true, value });
}

function restoreDomClipboardState(): void {
  if (originalClipboardDescriptor) {
    Object.defineProperty(navigator, "clipboard", originalClipboardDescriptor);
  } else {
    Reflect.deleteProperty(navigator, "clipboard");
  }
  if (originalExecCommandDescriptor) {
    Object.defineProperty(document, "execCommand", originalExecCommandDescriptor);
  } else {
    Reflect.deleteProperty(document, "execCommand");
  }
  document.body.innerHTML = "";
}

describe("copyTextToClipboard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    restoreDomClipboardState();
  });

  it("uses navigator.clipboard.writeText first when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const execCommand = vi.fn();
    stubClipboard({ writeText } as unknown as Clipboard);
    stubExecCommand(execCommand);

    await expect(copyTextToClipboard("https://example.test/game.zip")).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith("https://example.test/game.zip");
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("falls back when navigator.clipboard.writeText rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const execCommand = vi.fn().mockReturnValue(true);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubClipboard({ writeText } as unknown as Clipboard);
    stubExecCommand(execCommand);

    await expect(copyTextToClipboard("https://example.test/fallback.zip")).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith("https://example.test/fallback.zip");
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(consoleError).not.toHaveBeenCalled();
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("returns false without logging when the fallback copy command fails", async () => {
    const execCommand = vi.fn().mockReturnValue(false);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubClipboard(undefined);
    stubExecCommand(execCommand);

    await expect(copyTextToClipboard("https://example.test/manual.zip")).resolves.toBe(false);

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(consoleError).not.toHaveBeenCalled();
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("returns false without logging when the fallback copy command throws", async () => {
    const execCommand = vi.fn(() => { throw new Error("copy failed"); });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    stubClipboard(undefined);
    stubExecCommand(execCommand);

    await expect(copyTextToClipboard("https://example.test/throws.zip")).resolves.toBe(false);

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(consoleError).not.toHaveBeenCalled();
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("does nothing for an empty URL", async () => {
    const writeText = vi.fn();
    const execCommand = vi.fn();
    stubClipboard({ writeText } as unknown as Clipboard);
    stubExecCommand(execCommand);

    await expect(copyTextToClipboard("")).resolves.toBe(false);

    expect(writeText).not.toHaveBeenCalled();
    expect(execCommand).not.toHaveBeenCalled();
  });
});
