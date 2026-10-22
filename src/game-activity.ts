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

/**
 * Collapse a game's activity feed to its newest release.
 *
 * The backend records one event per platform, so a version that shipped on PC
 * and Android arrives as two events. Older releases are dropped, but every
 * event belonging to the newest release is kept - at most one per platform - so
 * a simultaneous PC + Android rollout still shows two lines, while a
 * single-platform release shows only its own line.
 */
export function latestReleaseActivity(events: GameActivityEvent[]): GameActivityEvent[] {
  if (events.length === 0) return [];
  const newestFirst = [...events].sort(
    (left, right) => activityTimestamp(right.occurred_at) - activityTimestamp(left.occurred_at),
  );
  const anchor = newestFirst[0];
  const perPlatform = new Map<string, GameActivityEvent>();
  for (const event of newestFirst) {
    if (event.version !== anchor.version || event.type !== anchor.type) continue;
    if (!perPlatform.has(event.platform)) perPlatform.set(event.platform, event);
  }
  return [...perPlatform.values()].sort(
    (left, right) => activityTimestamp(right.occurred_at) - activityTimestamp(left.occurred_at),
  );
}
