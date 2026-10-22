import { describe, expect, it } from "vitest";

import { gameActivityPlatform, latestReleaseActivity } from "./game-activity";
import type { GameActivityEvent } from "./types";

function event(overrides: Partial<GameActivityEvent> = {}): GameActivityEvent {
  return {
    id: 1,
    game_id: "nte",
    domain_id: "nte-pc",
    platform: "windows",
    version: "1.4.15",
    type: "version_update",
    occurred_at: "2026-10-17T05:48:35Z",
    ...overrides,
  };
}

describe("latestReleaseActivity", () => {
  it("returns nothing for an empty feed", () => {
    expect(latestReleaseActivity([])).toEqual([]);
  });

  it("keeps only the newest release when a single platform shipped", () => {
    const result = latestReleaseActivity([
      event({ id: 3, version: "1.4.15", occurred_at: "2026-10-17T05:48:35Z" }),
      event({ id: 2, version: "1.4.14", occurred_at: "2026-10-16T05:47:16Z" }),
      event({ id: 1, version: "1.4.13", occurred_at: "2026-10-15T09:46:24Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([3]);
  });

  it("drops older releases once both platforms moved to the newest version", () => {
    const result = latestReleaseActivity([
      event({ id: 5, version: "1.5.0", occurred_at: "2026-10-18T02:01:00Z" }),
      event({ id: 4, version: "1.5.0", platform: "android", domain_id: "nte-android", occurred_at: "2026-10-18T02:00:00Z" }),
      event({ id: 3, version: "1.4.15", occurred_at: "2026-10-17T05:48:35Z" }),
      event({ id: 2, version: "1.4.15", platform: "android", domain_id: "nte-android", occurred_at: "2026-10-17T05:44:02Z" }),
      event({ id: 1, version: "1.4.14", occurred_at: "2026-10-16T05:47:16Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([5, 4]);
  });

  it("lists both platforms of the newest release, newest first", () => {
    const result = latestReleaseActivity([
      event({ id: 3, version: "1.5.0", occurred_at: "2026-10-18T02:00:00Z" }),
      event({ id: 4, version: "1.5.0", platform: "android", domain_id: "nte-android", occurred_at: "2026-10-18T02:06:00Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([4, 3]);
    expect(result.map(gameActivityPlatform)).toEqual(["Android", "PC"]);
  });

  it("ignores older records for the same version and type", () => {
    const result = latestReleaseActivity([
      event({ id: 5, version: "1.4.15", occurred_at: "2026-10-17T05:48:35Z" }),
      event({ id: 4, version: "1.4.15", type: "version_unavailable", occurred_at: "2026-10-16T05:47:16Z" }),
      event({ id: 3, version: "1.4.14", type: "version_unavailable", occurred_at: "2026-10-15T05:47:16Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([5]);
  });

  it("shows the newest availability change when it is the latest release", () => {
    const result = latestReleaseActivity([
      event({ id: 2, version: "1.4.15", type: "version_unavailable", occurred_at: "2026-10-18T08:00:00Z" }),
      event({ id: 1, version: "1.4.15", occurred_at: "2026-10-17T05:48:35Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([2]);
  });

  it("keeps one line per platform even if the feed repeats it", () => {
    const result = latestReleaseActivity([
      event({ id: 3, version: "1.4.15", occurred_at: "2026-10-17T05:48:35Z" }),
      event({ id: 2, version: "1.4.15", occurred_at: "2026-10-17T05:40:00Z" }),
      event({ id: 1, version: "1.4.15", platform: "android", domain_id: "nte-android", occurred_at: "2026-10-17T05:30:00Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([3, 1]);
  });
});
