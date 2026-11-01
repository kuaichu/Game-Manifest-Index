import { describe, expect, it } from "vitest";

import { gameActivityPlatform, groupActivityReleases, latestReleaseActivity, normalizeReleaseVersion } from "./game-activity";
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

  it("treats platform version spellings like 3.3.0 and 3.3 as the same release", () => {
    const result = latestReleaseActivity([
      event({ id: 4, game_id: "nap", domain_id: "nap-pc", version: "3.3.0", occurred_at: "2026-10-20T14:52:51Z" }),
      event({ id: 3, game_id: "nap", domain_id: "nap-android", platform: "android", version: "3.3", occurred_at: "2026-10-20T14:52:51Z" }),
      event({ id: 2, game_id: "nap", domain_id: "nap-pc", version: "3.2.0", occurred_at: "2026-09-01T00:00:00Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([4, 3]);
    expect(result.map(gameActivityPlatform)).toEqual(["PC", "Android"]);
  });

  it("does not fold genuinely different versions together", () => {
    const result = latestReleaseActivity([
      event({ id: 2, version: "3.3.1", occurred_at: "2026-10-21T00:00:00Z" }),
      event({ id: 1, version: "3.3", platform: "android", domain_id: "nte-android", occurred_at: "2026-10-20T00:00:00Z" }),
    ]);
    expect(result.map((item) => item.id)).toEqual([2]);
  });
});

describe("normalizeReleaseVersion", () => {
  it("drops trailing zero segments so platform spellings compare equal", () => {
    expect(normalizeReleaseVersion("3.3.0")).toBe("3.3");
    expect(normalizeReleaseVersion("3.3")).toBe("3.3");
    expect(normalizeReleaseVersion("2.0.0.0")).toBe("2");
    expect(normalizeReleaseVersion("1.4.17")).toBe("1.4.17");
  });

  it("keeps a bare zero and tolerates surrounding spaces", () => {
    expect(normalizeReleaseVersion(" 1.0 ")).toBe("1");
    expect(normalizeReleaseVersion("0")).toBe("0");
  });
});

describe("groupActivityReleases", () => {
  it("folds one rollout shipped under two version spellings into a single row", () => {
    const rows = groupActivityReleases([
      event({ id: 2, version: "3.3.0", occurred_at: "2026-10-21T06:52:00Z" }),
      event({ id: 1, version: "3.3", platform: "android", domain_id: "zzz-android", occurred_at: "2026-10-21T06:52:30Z" }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].platforms).toEqual([
      { platform: "PC", version: "3.3.0" },
      { platform: "Android", version: "3.3" },
    ]);
  });

  it("keeps releases on different days apart and sorts newest first", () => {
    const rows = groupActivityReleases([
      event({ id: 1, version: "3.3", occurred_at: "2026-10-20T06:00:00Z" }),
      event({ id: 2, version: "3.4", occurred_at: "2026-10-21T06:00:00Z" }),
    ]);
    expect(rows.map((row) => row.occurredAt)).toEqual(["2026-10-21T06:00:00Z", "2026-10-20T06:00:00Z"]);
  });

  it("never merges a rollout with an availability change of the same version", () => {
    const rows = groupActivityReleases([
      event({ id: 2, version: "3.3", type: "version_unavailable", occurred_at: "2026-10-21T08:00:00Z" }),
      event({ id: 1, version: "3.3", occurred_at: "2026-10-21T06:00:00Z" }),
    ]);
    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.type)).toEqual(["version_unavailable", "version_update"]);
  });

  it("takes the newest timestamp but the first spelling when platforms repeat", () => {
    const rows = groupActivityReleases([
      event({ id: 2, version: "3.3.0", occurred_at: "2026-10-21T09:00:00Z" }),
      event({ id: 1, version: "3.3", occurred_at: "2026-10-21T06:00:00Z" }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].platforms).toEqual([{ platform: "PC", version: "3.3.0" }]);
    expect(rows[0].occurredAt).toBe("2026-10-21T09:00:00Z");
  });
});
