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
