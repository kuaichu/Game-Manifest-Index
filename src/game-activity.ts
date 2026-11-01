import type { GameActivityEvent } from "./types";

export function gameActivityTitle(event: GameActivityEvent, gameName: string): string {
  return event.type === "version_update"
    ? `${gameName}更新至 ${event.version} 版本`
    : `${gameName}的 ${event.version} 版本不可用了`;
}

export function gameActivityTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export function gameActivityPlatform(event: GameActivityEvent): string {
  return event.platform === "android" ? "Android" : "PC";
}

function activityTimestamp(value: string): number {
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

export interface ActivityReleaseRow {
  key: string;
  gameId: string;
  type: GameActivityEvent["type"];
  occurredAt: string;
  platforms: { platform: string; version: string }[];
}

export function activityDateKey(value: string): string {
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return "unknown";
  return `${time.getFullYear()}-${String(time.getMonth() + 1).padStart(2, "0")}-${String(time.getDate()).padStart(2, "0")}`;
}

/**
 * `/3.3.0` and `/3.3` describe the same rollout on two platforms, so trailing
 * zero segments are dropped before comparing versions.
 */
export function normalizeReleaseVersion(version: string): string {
  const trimmed = version.trim();
  return trimmed.replace(/(?:\.0)+$/, "") || trimmed;
}

/**
 * Fold the flat activity feed into one row per rollout.
 *
 * The backend stores one event per platform and platform version strings are
 * not always written the same way, so PC `3.3.0` and Android `3.3` must land in
 * the same row: same game, same day, same type and same normalized version.
 */
export function groupActivityReleases(events: readonly GameActivityEvent[]): ActivityReleaseRow[] {
  const rows = new Map<string, ActivityReleaseRow>();
  for (const event of events) {
    const key = [
      event.game_id,
      activityDateKey(event.occurred_at),
      normalizeReleaseVersion(event.version),
      event.type,
    ].join("|");
    const platform = gameActivityPlatform(event);
    const existing = rows.get(key);
    if (!existing) {
      rows.set(key, {
        key,
        gameId: event.game_id,
        type: event.type,
        occurredAt: event.occurred_at,
        platforms: [{ platform, version: event.version }],
      });
      continue;
    }
    if (!existing.platforms.some((item) => item.platform === platform)) {
      existing.platforms.push({ platform, version: event.version });
    }
    if (activityTimestamp(event.occurred_at) > activityTimestamp(existing.occurredAt)) {
      existing.occurredAt = event.occurred_at;
    }
  }
  return [...rows.values()].sort((left, right) => activityTimestamp(right.occurredAt) - activityTimestamp(left.occurredAt));
}

/**
 * Collapse a game's activity feed to its newest release.
 *
 * The backend records one event per platform, so a version that shipped on PC
 * and Android arrives as two events. Older releases are dropped, but every
 * event belonging to the newest release is kept - at most one per platform - so
 * a simultaneous PC + Android rollout still shows two lines, while a
 * single-platform release shows only its own line. Versions are compared after
 * normalization, so PC `3.3.0` and Android `3.3` count as the same release.
 */
export function latestReleaseActivity(events: GameActivityEvent[]): GameActivityEvent[] {
  if (events.length === 0) return [];
  const newestFirst = [...events].sort(
    (left, right) => activityTimestamp(right.occurred_at) - activityTimestamp(left.occurred_at),
  );
  const anchor = newestFirst[0];
  const anchorVersion = normalizeReleaseVersion(anchor.version);
  const perPlatform = new Map<string, GameActivityEvent>();
  for (const event of newestFirst) {
    if (normalizeReleaseVersion(event.version) !== anchorVersion || event.type !== anchor.type) continue;
    if (!perPlatform.has(event.platform)) perPlatform.set(event.platform, event);
  }
  return [...perPlatform.values()].sort(
    (left, right) => activityTimestamp(right.occurred_at) - activityTimestamp(left.occurred_at),
  );
}
