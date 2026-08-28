import { describe, expect, it } from "vitest";
import {
  discoverItemState,
  discoverSkippedCount,
  operationControlsDisabled,
  operationScopeLabel,
  probeAvailableUrls,
  probeCheckedUrls,
  probeUnavailableUrls,
  probeUnknownUrls,
  probeItemKey,
  probeFailedUrls,
  restoredOperationScope,
} from "./operation-scope";

describe("operation scope UI state", () => {
  it("restores only a valid scope returned by the operation job", () => {
    expect(restoredOperationScope("pc")).toBe("pc");
    expect(restoredOperationScope("android")).toBe("android");
    expect(restoredOperationScope("all")).toBe("all");
    expect(restoredOperationScope(undefined)).toBeNull();
  });

  it("labels PC scope without claiming every game supports it", () => {
    expect(operationScopeLabel("pc")).toContain("已接入适配器");
    expect(operationScopeLabel("all")).toContain("已接入的 PC");
  });

  it("locks scope controls while a task is loading or active", () => {
    expect(operationControlsDisabled(true, null)).toBe(true);
    expect(operationControlsDisabled(false, "running")).toBe(true);
    expect(operationControlsDisabled(false, "cancelling")).toBe(true);
    expect(operationControlsDisabled(false, "finished")).toBe(false);
  });

  it("treats an unsupported discover result as skipped even when the backend marks it ok", () => {
    expect(discoverItemState({ ok: true, status: "skipped", supported: false })).toBe("skipped");
    expect(discoverItemState({ ok: true, status: "ok", supported: true })).toBe("success");
    expect(discoverItemState({ ok: false, status: "failed" })).toBe("failed");
  });

  it("falls back to unsupported count when older results omit skipped", () => {
    expect(discoverSkippedCount({ skipped: undefined, unsupported: 2 })).toBe(2);
  });

  it("uses URL-level probe metrics and a key containing artifact/url indices", () => {
    expect(probeCheckedUrls({ checked: 2, checked_urls: 9 })).toBe(9);
    expect(probeAvailableUrls({ available: 1, available_urls: 7 })).toBe(7);
    expect(probeItemKey({ game_id: "hk4e", version: "6.0.0", platform: "pc", artifact_index: 3, url_index: 2 }))
      .toContain("pc-3-2");
  });

  it("counts unavailable strictly from available=false so the card matches its filter", () => {
    expect(probeUnavailableUrls({
      checked: 4,
      available: 1,
      unavailable: 99,
      unknown: 2,
      failed: 1,
      items: [
        { game_id: "hk4e", version: "6.0.0", ok: true, available: false, adapter: null, error: null },
        { game_id: "hk4e", version: "6.0.0", ok: true, available: null, adapter: null, error: null },
        { game_id: "hk4e", version: "6.0.0", ok: false, available: null, adapter: null, error: "timeout" },
      ],
    })).toBe(1);
  });

  it("keeps the unavailable card at zero for an empty result and supports legacy summaries", () => {
    expect(probeUnavailableUrls({
      checked: 0,
      available: 0,
      unavailable: 0,
      unknown: 0,
      failed: 0,
      items: [],
    })).toBe(0);
    expect(probeUnavailableUrls({
      checked: 2,
      available: 1,
      unavailable: 1,
      unknown: 0,
      failed: 0,
    })).toBe(1);
  });

  it("counts unknown urls strictly from items where available is neither true nor false", () => {
    expect(probeUnknownUrls({
      checked: 4,
      available: 1,
      unavailable: 1,
      unknown: 99,
      items: [
        { ok: true, available: true },
        { ok: true, available: false },
        { ok: true, available: null },
        { ok: false, available: undefined },
      ],
    })).toBe(1);
    expect(probeUnknownUrls({ unknown: 5, items: [] })).toBe(0);
    expect(probeUnknownUrls({ unknown: 5 })).toBe(5);
  });

  it("counts probe exceptions strictly from ok=false", () => {
    expect(probeFailedUrls({
      failed: 99,
      items: [
        { ok: true, available: null },
        { ok: false, available: null },
        { ok: true, available: false },
      ],
    })).toBe(1);
    expect(probeFailedUrls({ failed: 7, items: [] })).toBe(0);
    expect(probeFailedUrls({ failed: 7 })).toBe(7);
  });
});
