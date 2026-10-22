import { describe, expect, it } from "vitest";

import { formatFileTimeLabel, isoToLocalInput, localInputToIso } from "./admin-date-time";

describe("admin date time helpers", () => {
  it("keeps the same minute when converting an ISO value into a local input value", () => {
    const iso = "2026-08-03T07:53:01Z";
    const local = isoToLocalInput(iso);
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    const minuteOf = (value: string | number): number => Math.floor(new Date(value).getTime() / 60000);
    expect(minuteOf(local)).toBe(minuteOf(iso));
  });

  it("converts a local input value back to a UTC ISO string", () => {
    const iso = localInputToIso("2026-08-03T15:53");
    expect(iso.endsWith("Z")).toBe(true);
    expect(new Date(iso).getTime()).toBe(new Date("2026-08-03T15:53").getTime());
  });

  it("returns empty strings for missing or unparsable values", () => {
    expect(isoToLocalInput("")).toBe("");
    expect(isoToLocalInput(null)).toBe("");
    expect(isoToLocalInput("not-a-date")).toBe("");
    expect(localInputToIso("")).toBe("");
    expect(localInputToIso("not-a-date")).toBe("");
  });

  it("describes a stored time with local and UTC labels", () => {
    expect(formatFileTimeLabel("2026-08-03T07:53:01Z")).toMatch(/^2026-08-03 \d{2}:\d{2}（UTC 07:53）$/);
    expect(formatFileTimeLabel("")).toBe("");
    expect(formatFileTimeLabel("not-a-date")).toBe("");
  });
});
