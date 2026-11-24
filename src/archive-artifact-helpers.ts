import {
  domainActionSupport,
  hoyoArtifactCardPresentation,
  isAvailabilityActionable,
  preferredArtifactAction,
  preferredDomainArtifactAction,
} from "./domain-presentation";
import { gameIcons } from "./game-icons";
import type { ArchiveDomain, Artifact, Game, VersionSummary } from "./types";

export function iconForGame(games: readonly Game[], id: string): string | undefined {
  const source = games.find((item) => item.id === id)?.icon_source?.trim();
  if (source?.startsWith("builtin:")) return gameIcons[source.slice("builtin:".length)] || gameIcons[id];
  return source || gameIcons[id];
}

export function candidateUrl(artifact: Artifact, sourceKind: string) {
  return artifact.urls.find((item) => item.source_kind === sourceKind);
}

export function rawArtifactUrl(artifact: Artifact): string | undefined {
  return artifact.urls[0]?.url;
}

export function isFileManifestArtifact(artifact: Artifact): boolean {
  return artifact.attributes?.delivery_mode === "file_manifest";
}

export function manifestUrlFor(artifact: Artifact): string | undefined {
  const urls = artifact.attributes?.manifest_urls;
  return Array.isArray(urls) && typeof urls[0] === "string"
    ? urls[0]
    : (typeof artifact.attributes?.manifest_url === "string" ? artifact.attributes.manifest_url : undefined);
}

export function baseUrlFor(artifact: Artifact): string | undefined {
  const urls = artifact.attributes?.base_urls;
  return Array.isArray(urls) && typeof urls[0] === "string" ? urls[0] : undefined;
}

export function preferredAvailableUrl(
  domain: ArchiveDomain | null | undefined,
  artifact: Artifact,
  action: "open" | "copy" | "download" = "download",
): string | undefined {
  return preferredDomainArtifactAction(domain, artifact, action)?.url;
}

export function actionableCandidate(
  domain: ArchiveDomain | null | undefined,
  artifact: Artifact,
  sourceKind: string,
) {
  const candidate = candidateUrl(artifact, sourceKind);
  return domainActionSupport(domain, "open") &&
    candidate &&
    isAvailabilityActionable(candidate.current, candidate.url)
    ? candidate
    : undefined;
}

export function artifactIsAvailable(domain: ArchiveDomain | null | undefined, artifact: Artifact): boolean {
  const current = preferredArtifactAction(artifact)?.current || artifact.urls[0]?.current;
  if (current?.state === "available") return true;
  if (preferredAvailableUrl(domain, artifact) || actionableCandidate(domain, artifact, "official")) return true;
  return false;
}

export function artifactDownloadUrl(domain: ArchiveDomain | null | undefined, artifact: Artifact): string | undefined {
  if (!artifactIsAvailable(domain, artifact)) return undefined;
  return preferredAvailableUrl(domain, artifact)
    || actionableCandidate(domain, artifact, "official")?.url
    || artifact.urls.find((u) => u.current?.state === "available")?.url
    || rawArtifactUrl(artifact);
}

export function formatChecksum(artifact: Artifact): string {
  if (!artifact.checksum_value) return "—";
  const type = (artifact.checksum_type || (artifact.checksum_value.length === 32 ? "MD5" : "CRC64")).toUpperCase();
  return `${type}: ${artifact.checksum_value}`;
}

export function apkSourceSize(artifact: Artifact): number | null {
  const value = artifact.attributes.source_size;
  return typeof value === "number" && value > 0 ? value : null;
}

export function patchRouteText(artifact: Artifact): string {
  const from = String(artifact.attributes.route_from || "");
  const to = String(artifact.attributes.route_to || "");
  return from && to ? `${from} -> ${to}` : String(artifact.attributes.route || "更新路线未知");
}

export function patchRouteLabel(name: string): string {
  return name.replace("→", "->");
}

export function patchBasePath(artifact: Artifact): string {
  const raw = artifact.urls[0]?.url;
  if (!raw) return "—";
  try {
    const path = decodeURIComponent(new URL(raw, window.location.origin).pathname).replace(/^\/+/, "");
    return path.replace(/indexFile\.json$/i, "resources/");
  } catch {
    return raw;
  }
}

export function packageLabel(
  domain: ArchiveDomain | null | undefined,
  selectedSummary: VersionSummary | null | undefined,
  selectedVersion: string,
  artifact?: Artifact,
): string {
  if (selectedSummary?.provenance?.source_kind === "legacy_migration") return "历史归档资源清单";
  if (domain?.adapter === "arknights") return "官方完整分卷";
  if (domain?.adapter === "hoyo" && artifact) return hoyoArtifactCardPresentation(artifact, selectedVersion).label;
  if (domain?.adapter === "wuwa" || (artifact && isFileManifestArtifact(artifact))) return "官方资源清单";
  return "官方完整包";
}

export function hoyoPatchLabel(selectedVersion: string, artifact: Artifact): string {
  return hoyoArtifactCardPresentation(artifact, selectedVersion).label;
}

export function observedDate(value?: string | null): Date | null {
  if (!value) return null;
  const normalized = /(?:z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((result, part) => {
      if (part.type !== "literal") result[part.type] = part.value;
      return result;
    }, {});
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
}

export function formatRelativeTime(value?: string | null, now = Date.now()): string {
  const date = observedDate(value);
  if (!date) return "-";
  const seconds = Math.max(0, Math.round((now - date.getTime()) / 1000));
  if (seconds < 60) return "刚刚";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} 天前`;
  return formatDate(value);
}
