import { describe, expect, it } from "vitest";

import { formatBytes, formatSyncTime, getFileTimeSourceDescription } from "./admin-format";

describe("formatBytes", () => {
  it("formats byte counts with binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512.00 B");
    expect(formatBytes(1024)).toBe("1.00 KB");
    expect(formatBytes(82.83 * 1024 ** 3)).toBe("82.83 GB");
  });

  it("returns a dash for missing values", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
    expect(formatBytes(Number.NaN)).toBe("—");
  });

  it("caps oversized values at the largest unit", () => {
    expect(formatBytes(2048 * 1024 ** 4)).toBe("2048.00 TB");
  });
});

describe("formatSyncTime", () => {
  it("formats an ISO timestamp as local zh-CN date and time", () => {
    const formatted = formatSyncTime("2026-10-17T05:48:35Z");
    expect(formatted).toMatch(/^2026\/10\/17 \d{2}:\d{2}$/);
  });

  it("returns an empty string for blank or invalid input", () => {
    expect(formatSyncTime("")).toBe("");
    expect(formatSyncTime(null)).toBe("");
    expect(formatSyncTime("not-a-date")).toBe("");
  });
});

describe("getFileTimeSourceDescription", () => {
  it("explains the empty state", () => {
    expect(getFileTimeSourceDescription("", "https://example.com/a.zip")).toBe(
      "留空（保存后由后端自动识别）",
    );
  });

  it("recognises a full timestamp inside the URL", () => {
    expect(getFileTimeSourceDescription("2026-08-03 15:53", "https://cdn.example.com/20260803155301/a.zip")).toBe(
      "URL 时间",
    );
  });

  it("recognises a date stamp inside the URL", () => {
    expect(getFileTimeSourceDescription("2026-08-03", "https://cdn.example.com/20260803/a.zip")).toBe(
      "URL 时间",
    );
  });

  it("falls back to manual entry when the URL disagrees", () => {
    expect(getFileTimeSourceDescription("2024-01-02 10:00", "https://cdn.example.com/20260803/a.zip")).toBe(
      "人工填写",
    );
  });
});
