export type OperationPlatformScope = "all" | "android" | "pc";
export type OperationJobState = "running" | "cancelling" | "cancelled" | "finished" | "failed";

import type { DiscoverResultItem, ProbeResultItem, ProbeResultSummary } from "./types";

export function operationScopeLabel(scope: OperationPlatformScope | null | undefined): string {
  if (scope === "android") return "仅 Android (APK)";
  if (scope === "pc") return "仅 PC 客户端（已接入适配器）";
  if (scope === "all") return "全量数据 (APK + 已接入的 PC)";
  return "数据范围未返回";
}

export function restoredOperationScope(
  scope: OperationPlatformScope | null | undefined,
): OperationPlatformScope | null {
  return scope === "all" || scope === "android" || scope === "pc" ? scope : null;
}

export function operationControlsDisabled(loading: boolean, state: OperationJobState | null | undefined): boolean {
  return loading || state === "running" || state === "cancelling";
}

export function discoverItemState(item: Pick<DiscoverResultItem, "ok" | "status" | "supported" | "skipped" | "unsupported">): "success" | "skipped" | "failed" {
  if (item.status === "skipped" || item.skipped === true || item.unsupported === true || item.supported === false) {
    return "skipped";
  }
  return item.ok ? "success" : "failed";
}

export function discoverSkippedCount(summary: Pick<import("./types").DiscoverResultSummary, "skipped" | "unsupported">): number {
  return summary.skipped ?? summary.unsupported ?? 0;
}

export function probeCheckedUrls(summary: Pick<ProbeResultSummary, "checked" | "checked_urls">): number {
  return summary.checked_urls ?? summary.checked;
}

export function probeAvailableUrls(summary: Pick<ProbeResultSummary, "available" | "available_urls">): number {
  return summary.available_urls ?? summary.available;
}

export function probeUnavailableUrls(summary: {
  unavailable?: number;
  items?: Array<{ available: boolean | null; [key: string]: unknown }>;
  [key: string]: unknown;
}): number {
  if (Array.isArray(summary.items)) {
    return summary.items.filter((item) => item.available === false).length;
  }
  return summary.unavailable ?? 0;
}

export function probeUnknownUrls(summary: {
  unknown?: number;
  items?: Array<{ available?: boolean | null; [key: string]: unknown }>;
  [key: string]: unknown;
}): number {
  if (Array.isArray(summary.items)) {
    return summary.items.filter(isProbeUnknownItem).length;
  }
  return summary.unknown ?? 0;
}

export function isProbeUnknownItem(item: { ok?: boolean; available?: boolean | null }): boolean {
  return item.ok === true && item.available !== true && item.available !== false;
}

export function probeResultReason(item: Pick<ProbeResultItem, "ok" | "available" | "error" | "reason">): string {
  if (item.error) return `探活失败：${item.error}`;
  if (!item.ok) return "探活失败，未取得有效结果";
  const reason = item.reason?.trim();
  if (reason === "oss_archive_not_restored") return "对象已归档，尚未恢复下载";
  if (isProbeUnknownItem(item)) {
    if (reason === "HTTP 401" || reason === "HTTP 403") return `上游拒绝访问（${reason}）`;
    if (reason === "HTTP 200" || reason === "HTTP 206") return `已响应，但未取得有效文件证据（${reason}）`;
    return reason ? `无法确认资源状态（${reason}）` : "探活完成，但未取得有效文件证据";
  }
  return reason || (item.available ? "探活判定可用" : "探活判定不可用");
}

export function probeFailedUrls(summary: {
  failed?: number;
  items?: Array<{ ok: boolean; [key: string]: unknown }>;
  [key: string]: unknown;
}): number {
  if (Array.isArray(summary.items)) {
    return summary.items.filter((item) => item.ok === false).length;
  }
  return summary.failed ?? 0;
}

export function probeItemKey(item: Pick<ProbeResultItem, "game_id" | "version" | "platform" | "artifact_index" | "url_index">): string {
  const artifact = item.artifact_index ?? "artifact";
  const url = item.url_index ?? "url";
  return `${item.game_id}-${item.version}-${item.platform || "unknown"}-${artifact}-${url}`;
}
